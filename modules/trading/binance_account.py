"""Cliente AUTENTICADO de Binance Futuros (USDⓈ-M) — base del bot espejo.

A diferencia de `binance.py` (klines públicas, sin clave), este módulo firma las
peticiones con HMAC-SHA256 para leer/operar la cuenta real.

LECTURA: server_time, balance_usdt, positions, mark_price, symbol_filters, get_order.
EJECUCIÓN: set_leverage, market_order, stop_market, cancel_all_orders.

`get_order` es lectura pero pertenece al camino de ejecución: es lo que permite
saber si una orden que "falló" en realidad se ejecutó. Ver su docstring.

⚠️ Este cliente solo provee la CAPACIDAD de operar; la decisión de mandar o no
una orden (y todos los guardrails: idempotencia, kill-switch, límites, dry-run)
vive en `modules/bot/executor.py`. Nada acá dispara órdenes por su cuenta.

Credenciales (en este orden): BINANCE_TRADE_API_KEY/SECRET (llave dedicada del bot)
o, como fallback, BINANCE_API_KEY/SECRET (la del colector). Hugo reutilizó la llave
del colector ("Nexux") habilitándole Futuros + IP-whitelist al VPS y RETIROS OFF, así
que el bot toma esas credenciales del collector.env que YA vive en el VPS.

Probar a mano (carga el envfile y consulta la cuenta):

    set -a; . deploy/collector.env; set +a
    .venv/bin/python -m modules.trading.binance_account
"""
from __future__ import annotations

import hashlib
import hmac
import json
import math
import os
import time
import urllib.error
import urllib.parse
import urllib.request

FAPI = "https://fapi.binance.com"
TIMEOUT = 15
# Tolerancia de la firma. 5000 era demasiado justo en el camino de ORDEN: un reloj
# corrido o una latencia mala convertían un cierre en un -1021, y un cierre que no
# sale deja una posición viva. Se sube a 10s y además se corrige el desfase (ver
# `_clock_offset_ms`), que ataca la causa en vez del síntoma.
RECV_WINDOW = 10_000


class BinanceError(RuntimeError):
    """Error devuelto por Binance (incluye su código y mensaje crudos)."""


class BinanceFutures:
    """Cliente firmado para la cuenta de futuros USDⓈ-M.

    FASE 1: solo expone lecturas (server_time, balance_usdt, positions).
    """

    def __init__(self, api_key: str | None = None, api_secret: str | None = None,
                 base_url: str | None = None):
        # SOLO llaves de trading dedicadas (BINANCE_TRADE_*). NUNCA cae a las del
        # colector/cuenta principal (BINANCE_API_*): eso violaría la regla de la
        # subcuenta aislada (CLAUDE.md). Mejor fallar que operar la cuenta equivocada.
        self.api_key = (api_key or os.environ.get("BINANCE_TRADE_API_KEY") or "").strip()
        self.api_secret = (api_secret or os.environ.get("BINANCE_TRADE_API_SECRET") or "").strip()
        self.base_url = (
            base_url or os.environ.get("BINANCE_FAPI_BASE_URL") or FAPI
        ).rstrip("/")
        self._filters_cache: dict = {}
        # Desfase con el reloj de Binance, en ms. Se mide solo, y se vuelve a medir
        # cuando el propio Binance rechaza la firma por -1021. Sin esto, un reloj
        # corrido deja al bot sin poder cerrar una posición abierta.
        self._clock_offset_ms = 0
        if not self.api_key or not self.api_secret:
            raise BinanceError(
                "Faltan credenciales de TRADING: define BINANCE_TRADE_API_KEY/SECRET "
                "(subcuenta dedicada, retiros OFF). No se usan las del colector.")

    # ---- plomería HTTP -------------------------------------------------

    def _sign(self, params: dict) -> str:
        """Devuelve el query string con la firma HMAC-SHA256 al final."""
        query = urllib.parse.urlencode(params)
        sig = hmac.new(self.api_secret.encode(), query.encode(),
                       hashlib.sha256).hexdigest()
        return f"{query}&signature={sig}"

    def _request(self, method: str, path: str, params: dict | None = None,
                 signed: bool = False, _reintento_reloj: bool = False) -> object:
        params = dict(params or {})
        headers = {"User-Agent": "Nexus-bot/1.0"}
        url = f"{self.base_url}{path}"
        data = None
        if signed:
            params["timestamp"] = int(time.time() * 1000) + self._clock_offset_ms
            params.setdefault("recvWindow", RECV_WINDOW)
            headers["X-MBX-APIKEY"] = self.api_key
            query = self._sign(params)
            if method == "GET":
                url = f"{url}?{query}"
            else:
                data = query.encode()
                headers["Content-Type"] = "application/x-www-form-urlencoded"
        elif params:
            url = f"{url}?{urllib.parse.urlencode(params)}"

        req = urllib.request.Request(url, data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                return json.load(resp)
        except urllib.error.HTTPError as exc:
            body = exc.read().decode(errors="replace")
            # -1021: la firma llegó fuera de ventana. Es el reloj, no la petición:
            # se remide el desfase y se reintenta UNA vez. Sin esto, un reloj corrido
            # bloquea el camino de orden entero hasta que alguien lo note a mano.
            if "-1021" in body and signed and not _reintento_reloj:
                try:
                    self.sync_clock()
                except BinanceError:
                    pass
                else:
                    return self._request(method, path, params, signed,
                                         _reintento_reloj=True)
            raise BinanceError(f"HTTP {exc.code} en {method} {path}: {body}") from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            raise BinanceError(f"Sin respuesta de Binance en {path}: {exc}") from exc

    def sync_clock(self) -> int:
        """Mide el desfase con el reloj de Binance y lo aplica a las firmas siguientes."""
        local = int(time.time() * 1000)
        self._clock_offset_ms = self.server_time() - local
        return self._clock_offset_ms

    # ---- lecturas (Fase 1) ---------------------------------------------

    def server_time(self) -> int:
        """Hora del servidor en ms (público). Útil para chequear el reloj."""
        return int(self._request("GET", "/fapi/v1/time")["serverTime"])

    def balance_usdt(self) -> dict:
        """Balance del activo USDT en la billetera de futuros.

        Devuelve {balance, available, unrealized_pnl} en USDT.
        """
        rows = self._request("GET", "/fapi/v2/balance", signed=True)
        for r in rows:
            if r.get("asset") == "USDT":
                return {
                    "balance": float(r["balance"]),
                    "available": float(r["availableBalance"]),
                    "unrealized_pnl": float(r.get("crossUnPnl", 0.0)),
                }
        return {"balance": 0.0, "available": 0.0, "unrealized_pnl": 0.0}

    def positions(self, symbols: list[str] | None = None) -> list[dict]:
        """Posiciones ABIERTAS (positionAmt != 0).

        Si `symbols` se entrega, filtra a esos pares (ej: ["BTCUSDT","ETHUSDT"]).
        """
        rows = self._request("GET", "/fapi/v2/positionRisk", signed=True)
        wanted = set(symbols) if symbols else None
        out = []
        for r in rows:
            amt = float(r.get("positionAmt", 0) or 0)
            if amt == 0:
                continue
            if wanted and r.get("symbol") not in wanted:
                continue
            lev = int(float(r.get("leverage", 0) or 0))
            notional = abs(float(r.get("notional", 0) or 0))
            out.append({
                "symbol": r.get("symbol"),
                "side": "LONG" if amt > 0 else "SHORT",
                "position_side": r.get("positionSide", "BOTH"),  # hedge: LONG/SHORT; one-way: BOTH
                "qty": abs(amt),
                "entry": float(r.get("entryPrice", 0) or 0),
                "mark": float(r.get("markPrice", 0) or 0),
                "notional": round(notional, 2),
                "margin": round(notional / lev, 2) if lev else 0.0,
                "leverage": lev,
                "unrealized_pnl": float(r.get("unRealizedProfit", 0) or 0),
                "liq_price": float(r.get("liquidationPrice", 0) or 0),
            })
        return out

    # ---- ejecución (la gobierna modules/bot/executor.py) ----------------

    def mark_price(self, symbol: str) -> float:
        """Precio mark del símbolo (público)."""
        r = self._request("GET", "/fapi/v1/premiumIndex", {"symbol": symbol})
        return float(r["markPrice"])

    def symbol_filters(self, symbol: str) -> dict:
        """Filtros del símbolo (cacheados): step de cantidad, mínimos y precisión.
        Necesario para redondear la qty a un valor que Binance acepte.

        OJO CON `syms[0]`: /fapi/v1/exchangeInfo IGNORA el parámetro `symbol` y
        devuelve los 848 símbolos igual. Tomar el primero devolvía SIEMPRE BTCUSDT,
        así que todos los pares heredaban la precisión de BTC. ADA se opera en
        unidades enteras (stepSize 1, quantityPrecision 0) y el bot habría mandado
        369.803 → -1111 en cada orden. Nunca se vio porque los 27 trades live fueron
        ETH y BTC, que sí comparten la precisión de BTC; V2 opera ADA, XRP y SOL.

        Hay que BUSCAR el símbolo en la lista. Y como la respuesta trae todo, se
        cachean todos de una: 848 símbolos por par era pagar la misma descarga cinco
        veces para quedarse con el dato equivocado.
        """
        if symbol in self._filters_cache:
            return self._filters_cache[symbol]
        info = self._request("GET", "/fapi/v1/exchangeInfo", {"symbol": symbol})
        syms = info.get("symbols") or []
        encontrado = None
        for s in syms:
            f = {"qty_step": 0.0, "min_qty": 0.0, "min_notional": 0.0,
                 "qty_precision": int(s.get("quantityPrecision", 3)),
                 "price_precision": int(s.get("pricePrecision", 2))}
            for flt in s.get("filters", []):
                t = flt.get("filterType")
                if t == "LOT_SIZE":
                    f["qty_step"] = float(flt.get("stepSize", 0) or 0)
                    f["min_qty"] = float(flt.get("minQty", 0) or 0)
                elif t == "MIN_NOTIONAL":
                    f["min_notional"] = float(flt.get("notional", 0) or 0)
            self._filters_cache[s.get("symbol")] = f
            if s.get("symbol") == symbol:
                encontrado = f
        if encontrado is None:
            # Mejor fallar que dimensionar con la precisión de otro símbolo.
            self._filters_cache.pop(symbol, None)
            raise BinanceError(f"{symbol} no está en exchangeInfo ({len(syms)} símbolos)")
        return encontrado

    def round_qty(self, symbol: str, qty: float) -> float:
        """Redondea la cantidad HACIA ABAJO al step del símbolo."""
        f = self.symbol_filters(symbol)
        step = f["qty_step"] or (10 ** -f["qty_precision"])
        n = math.floor(qty / step) * step
        return round(n, f["qty_precision"])

    def set_leverage(self, symbol: str, leverage: int) -> dict:
        return self._request("POST", "/fapi/v1/leverage",
                             {"symbol": symbol, "leverage": int(leverage)}, signed=True)

    def set_position_mode(self, dual: bool) -> dict:
        """Cambia entre one-way (dual=False) y HEDGE (dual=True). Requiere SIN posiciones
        abiertas. Devuelve la respuesta (o lanza si ya está en ese modo / hay posiciones)."""
        return self._request("POST", "/fapi/v1/positionSide/dual",
                             {"dualSidePosition": "true" if dual else "false"}, signed=True)

    def position_mode(self) -> bool:
        """True si la cuenta está en modo HEDGE (dualSidePosition)."""
        r = self._request("GET", "/fapi/v1/positionSide/dual", signed=True)
        return bool(r.get("dualSidePosition"))

    def market_order(self, symbol: str, side: str, qty: float,
                     client_id: str | None = None, reduce_only: bool = False,
                     position_side: str | None = None) -> dict:
        """Orden a mercado. side: 'BUY'|'SELL'. En HEDGE pasar position_side ('LONG'|
        'SHORT') y NO reduceOnly (el par side+positionSide define abrir/cerrar)."""
        # newOrderRespType=RESULT es OBLIGATORIO acá. El default de Binance es ACK, que
        # contesta antes de saber el fill: executedQty="0" y avgPrice="0". Con ACK el bot
        # no puede distinguir un fill total de uno parcial, ni conocer el precio real de
        # entrada — y todo el manejo de parciales que hay aguas abajo queda ciego.
        p = {"symbol": symbol, "side": side, "type": "MARKET", "quantity": qty,
             "newOrderRespType": "RESULT"}
        if position_side:
            p["positionSide"] = position_side
        elif reduce_only:
            p["reduceOnly"] = "true"
        if client_id:
            p["newClientOrderId"] = client_id
        return self._request("POST", "/fapi/v1/order", p, signed=True)

    def stop_market(self, symbol: str, side: str, stop_price: float,
                    qty: float | None = None, client_id: str | None = None,
                    position_side: str | None = None) -> dict:
        """Stop a mercado. `side` es el lado de la ORDEN (opuesto a la posición).
        Si se da `qty` → reduceOnly de esa cantidad; si no → closePosition (toda).
        En HEDGE pasar position_side y NO reduceOnly."""
        f = self.symbol_filters(symbol)
        p = {"symbol": symbol, "side": side, "type": "STOP_MARKET",
             "stopPrice": round(stop_price, f["price_precision"]),
             "workingType": "MARK_PRICE"}
        if position_side:
            p["positionSide"] = position_side
            if qty is not None:
                p["quantity"] = qty
            else:
                # En HEDGE sin qty faltaba esto y la orden salía sin `quantity` NI
                # `closePosition`: Binance la rechazaba con -1102 antes de mirar
                # permisos. Un stop que se cae en la validación de parámetros se ve
                # igual que un stop prohibido, y por eso el bot nunca supo cuál era.
                p["closePosition"] = "true"
        elif qty is not None:
            p["quantity"] = qty
            p["reduceOnly"] = "true"
        else:
            p["closePosition"] = "true"
        if client_id:
            p["newClientOrderId"] = client_id
        return self._request("POST", "/fapi/v1/order", p, signed=True)

    def get_order(self, symbol: str, client_id: str) -> dict | None:
        """Estado REAL de una orden, por el clientOrderId que nosotros generamos.

        Devuelve None si Binance nunca la recibió (-2013).

        ES EL ÁRBITRO DE LAS ÓRDENES AMBIGUAS. Cuando un POST falla no sabemos si
        falló al ir o al volver: la orden pudo ejecutarse igual y perderse la
        respuesta. Un reintento con el mismo id rebota como "duplicate", que se ve
        idéntico a un fallo real. La única fuente de verdad es preguntarle a Binance
        por el id; el código de error no alcanza para distinguir los dos casos.
        """
        try:
            r = self._request("GET", "/fapi/v1/order",
                              {"symbol": symbol, "origClientOrderId": client_id},
                              signed=True)
        except BinanceError as exc:
            if "-2013" in str(exc):  # "Order does not exist" → nunca llegó
                return None
            raise
        return {
            "status": r.get("status"),  # NEW/PARTIALLY_FILLED/FILLED/CANCELED/EXPIRED
            "executed_qty": float(r.get("executedQty") or 0),
            "orig_qty": float(r.get("origQty") or 0),
            "avg_price": float(r.get("avgPrice") or 0),
            "side": r.get("side"),
            "position_side": r.get("positionSide"),
            "client_id": r.get("clientOrderId"),
        }

    # ---- stop NATIVO (Algo Order API) -----------------------------------
    #
    # Binance migró las órdenes condicionales fuera de /fapi/v1/order el 2025-12-09.
    # Mandar STOP_MARKET al endpoint viejo devuelve -4120 apuntando acá. Es EL arreglo
    # del -1R: lo hace cumplir Binance, sin depender del VPS ni del polling del bot.
    # En el libro real, 8 de 11 stops se pasaron del -1R (peor -4.17R).
    #
    # Diferencias con el endpoint viejo, todas fáciles de equivocar:
    #   `triggerPrice`, no `stopPrice`   ·   `clientAlgoId`, no `newClientOrderId`
    #   `reduceOnly` NO se admite en HEDGE   ·   `quantity` y `closePosition` se excluyen
    # Peso 0 contra el límite de IP.

    def algo_stop_market(self, symbol: str, side: str, trigger_price: float,
                         qty: float | None = None, close_position: bool = False,
                         position_side: str | None = None,
                         client_algo_id: str | None = None) -> dict:
        """Stop condicional nativo. `side` es el lado de la ORDEN (opuesto a la posición)."""
        f = self.symbol_filters(symbol)
        p = {"algoType": "CONDITIONAL", "symbol": symbol, "side": side,
             "type": "STOP_MARKET",
             "triggerPrice": round(trigger_price, f["price_precision"]),
             "workingType": "MARK_PRICE", "newOrderRespType": "RESULT"}
        if position_side:
            p["positionSide"] = position_side
        if close_position:
            p["closePosition"] = "true"
        elif qty is not None:
            p["quantity"] = qty
            if not position_side:  # reduceOnly es inválido en HEDGE
                p["reduceOnly"] = "true"
        else:
            raise BinanceError("algo_stop_market necesita qty o close_position")
        if client_algo_id:
            p["clientAlgoId"] = client_algo_id
        return self._request("POST", "/fapi/v1/algoOrder", p, signed=True)

    def get_algo_order(self, client_algo_id: str) -> dict | None:
        """UN stop condicional por su clientAlgoId. None si no existe.

        Es la forma precisa de confirmar que una posición quedó protegida: pregunta
        por el id exacto en vez de listar y buscar.
        """
        try:
            r = self._request("GET", "/fapi/v1/algoOrder",
                              {"clientAlgoId": client_algo_id}, signed=True)
        except BinanceError as exc:
            if "-2013" in str(exc) or "not exist" in str(exc).lower():
                return None
            raise
        if isinstance(r, list):
            r = r[0] if r else None
        return self._norm_algo(r) if r else None

    @staticmethod
    def _norm_algo(r: dict) -> dict:
        close_raw = r.get("closePosition")
        close_position = (
            close_raw if isinstance(close_raw, bool)
            else str(close_raw or "").lower() == "true"
        )
        return {
            "algo_id": r.get("algoId"),
            "client_algo_id": r.get("clientAlgoId"),
            "symbol": r.get("symbol"),
            "side": r.get("side"),
            "position_side": r.get("positionSide"),
            "type": r.get("orderType") or r.get("type"),
            "trigger_price": float(r.get("triggerPrice") or 0),
            "qty": float(r.get("quantity") or 0),
            "close_position": close_position,
            "status": r.get("algoStatus"),
        }

    def algo_open_orders(self, symbol: str) -> list[dict]:
        """Stops condicionales VIVOS del símbolo.

        OJO CON EL PATH: la documentación dice `/fapi/v1/algoOpenOrders` y ese path
        devuelve 404. El real es `/fapi/v1/openAlgoOrders` — verificado contra la API
        el 2026-07-29. Ya van tres veces en este trabajo que la doc no coincide con lo
        que responde Binance; no dar por buena una ruta sin llamarla.
        """
        rows = self._request("GET", "/fapi/v1/openAlgoOrders", {"symbol": symbol},
                             signed=True)
        if isinstance(rows, dict):
            rows = rows.get("orders") or rows.get("algoOrders") or []
        return [self._norm_algo(r) for r in (rows or [])]

    def cancel_algo_order(self, algo_id=None, client_algo_id: str | None = None) -> dict:
        """Cancela UN stop condicional. Deliberadamente sin variante `cancel_all`:
        en HEDGE, barrer todo el símbolo se lleva por delante el stop del lado opuesto."""
        if not algo_id and not client_algo_id:
            raise BinanceError("cancel_algo_order necesita algo_id o client_algo_id")
        p = {"algoId": algo_id} if algo_id else {"clientAlgoId": client_algo_id}
        return self._request("DELETE", "/fapi/v1/algoOrder", p, signed=True)

    def cancel_all_orders(self, symbol: str) -> dict:
        """OJO EN HEDGE: barre TODO el símbolo, incluido el stop del lado opuesto.
        Para cancelar el stop de una posición usar `cancel_algo_order`."""
        return self._request("DELETE", "/fapi/v1/allOpenOrders",
                             {"symbol": symbol}, signed=True)

    def realized_pnl(self, symbol: str, start_ms: int, end_ms: int | None = None) -> dict:
        """P&L realizado REAL + comisiones de Binance (income) para el símbolo en la
        ventana dada. Para que el libro reporte lo real, no una estimación."""
        params = {"symbol": symbol, "startTime": int(start_ms), "limit": 500}
        if end_ms:
            params["endTime"] = int(end_ms)
        rows = self._request("GET", "/fapi/v1/income", params, signed=True)
        pnl = sum(float(r["income"]) for r in rows if r.get("incomeType") == "REALIZED_PNL")
        comm = sum(float(r["income"]) for r in rows if r.get("incomeType") == "COMMISSION")
        return {"pnl_bruto": round(pnl, 6), "commission": round(comm, 6),
                "neto": round(pnl + comm, 6)}

    def open_orders(self, symbol: str | None = None) -> list[dict]:
        """Órdenes ABIERTAS (pendientes), p.ej. el stop de respaldo."""
        params = {"symbol": symbol} if symbol else {}
        rows = self._request("GET", "/fapi/v1/openOrders", params, signed=True)
        out = []
        for r in rows:
            out.append({
                "symbol": r.get("symbol"),
                "type": r.get("type"),
                "side": r.get("side"),
                "stop_price": float(r.get("stopPrice", 0) or 0),
                "qty": float(r.get("origQty", 0) or 0),
                "reduce_only": bool(r.get("reduceOnly")),
                "close_position": bool(r.get("closePosition")),
            })
        return out


def _load_envfile(path: str) -> None:
    """Carga KEY=VALUE de un archivo a os.environ (no pisa lo ya definido)."""
    if not os.path.exists(path):
        return
    with open(path) as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())


if __name__ == "__main__":
    # Prueba de humo de la Fase 1: lee la cuenta real y la imprime. NO opera.
    import sys

    envfile = sys.argv[1] if len(sys.argv) > 1 else "deploy/collector.env"
    _load_envfile(envfile)

    cli = BinanceFutures()
    drift = int(time.time() * 1000) - cli.server_time()
    print(f"✓ Conectado a Binance Futuros · desfase de reloj: {drift} ms")

    bal = cli.balance_usdt()
    print(f"  Balance USDT : {bal['balance']:.2f}  "
          f"(disponible {bal['available']:.2f}, uPnL {bal['unrealized_pnl']:+.2f})")

    pos = cli.positions(["BTCUSDT", "ETHUSDT"])
    if not pos:
        print("  Posiciones   : ninguna abierta en BTC/ETH")
    for p in pos:
        print(f"  {p['side']} {p['symbol']} qty={p['qty']} entry={p['entry']} "
              f"lev={p['leverage']}x uPnL={p['unrealized_pnl']:+.2f}")

    print("\nFASE 1 OK — solo lectura. Ninguna orden enviada.")
