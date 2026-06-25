"""Cliente AUTENTICADO de Binance Futuros (USDⓈ-M) — base del bot espejo.

A diferencia de `binance.py` (klines públicas, sin clave), este módulo firma las
peticiones con HMAC-SHA256 para leer/operar la cuenta real.

LECTURA: server_time, balance_usdt, positions, mark_price, symbol_filters.
EJECUCIÓN: set_leverage, market_order, stop_market, cancel_all_orders.

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
RECV_WINDOW = 5000  # ms de tolerancia para la firma (evita -1021 por reloj)


class BinanceError(RuntimeError):
    """Error devuelto por Binance (incluye su código y mensaje crudos)."""


class BinanceFutures:
    """Cliente firmado para la cuenta de futuros USDⓈ-M.

    FASE 1: solo expone lecturas (server_time, balance_usdt, positions).
    """

    def __init__(self, api_key: str | None = None, api_secret: str | None = None,
                 base_url: str = FAPI):
        self.api_key = (api_key or os.environ.get("BINANCE_TRADE_API_KEY")
                        or os.environ.get("BINANCE_API_KEY") or "").strip()
        self.api_secret = (api_secret or os.environ.get("BINANCE_TRADE_API_SECRET")
                           or os.environ.get("BINANCE_API_SECRET") or "").strip()
        self.base_url = base_url.rstrip("/")
        self._filters_cache: dict = {}
        if not self.api_key or not self.api_secret:
            raise BinanceError(
                "Faltan credenciales: define BINANCE_TRADE_API_KEY/SECRET "
                "(o BINANCE_API_KEY/SECRET del colector). Retiros OFF.")

    # ---- plomería HTTP -------------------------------------------------

    def _sign(self, params: dict) -> str:
        """Devuelve el query string con la firma HMAC-SHA256 al final."""
        query = urllib.parse.urlencode(params)
        sig = hmac.new(self.api_secret.encode(), query.encode(),
                       hashlib.sha256).hexdigest()
        return f"{query}&signature={sig}"

    def _request(self, method: str, path: str, params: dict | None = None,
                 signed: bool = False) -> object:
        params = dict(params or {})
        headers = {"User-Agent": "Nexus-bot/1.0"}
        url = f"{self.base_url}{path}"
        data = None
        if signed:
            params["timestamp"] = int(time.time() * 1000)
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
            raise BinanceError(f"HTTP {exc.code} en {method} {path}: {body}") from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            raise BinanceError(f"Sin respuesta de Binance en {path}: {exc}") from exc

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
        Necesario para redondear la qty a un valor que Binance acepte."""
        if symbol in self._filters_cache:
            return self._filters_cache[symbol]
        info = self._request("GET", "/fapi/v1/exchangeInfo", {"symbol": symbol})
        syms = info.get("symbols") or []
        if not syms:
            raise BinanceError(f"sin exchangeInfo para {symbol}")
        s = syms[0]
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
        self._filters_cache[symbol] = f
        return f

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
        p = {"symbol": symbol, "side": side, "type": "MARKET", "quantity": qty}
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
        elif qty is not None:
            p["quantity"] = qty
            p["reduceOnly"] = "true"
        else:
            p["closePosition"] = "true"
        if client_id:
            p["newClientOrderId"] = client_id
        return self._request("POST", "/fapi/v1/order", p, signed=True)

    def cancel_all_orders(self, symbol: str) -> dict:
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
