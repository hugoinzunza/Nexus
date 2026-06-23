"""Cliente AUTENTICADO de Binance Futuros (USDⓈ-M) — base del bot espejo.

A diferencia de `binance.py` (klines públicas, sin clave), este módulo firma las
peticiones con HMAC-SHA256 para leer/operar la cuenta real.

⚠️ FASE 1 — SOLO LECTURA. Este archivo, por ahora, únicamente CONSULTA la cuenta
(balance y posiciones). No manda órdenes. La ejecución llega en la Fase 2 y vivirá
en otro módulo, con sus propios guardrails (idempotencia, kill-switch, límites).

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
            out.append({
                "symbol": r.get("symbol"),
                "side": "LONG" if amt > 0 else "SHORT",
                "qty": abs(amt),
                "entry": float(r.get("entryPrice", 0) or 0),
                "leverage": int(float(r.get("leverage", 0) or 0)),
                "unrealized_pnl": float(r.get("unRealizedProfit", 0) or 0),
                "liq_price": float(r.get("liquidationPrice", 0) or 0),
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
