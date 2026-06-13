"""Colector del Diario — corre en el Mac mini (IP chilena, no bloqueada).

Binance responde HTTP 451 desde los servidores de Railway (geo-bloqueo), así que
la LECTURA de Binance se hace desde el Mac mini y el resultado se ENVÍA a Railway.

Este proceso:
  1. Lee Futuros USDⓈ-M (income/PnL, posiciones, balance) y Spot con el cliente
     read-only existente (binance_client).
  2. Computa el MISMO JSON del Diario (resumen, equity, posiciones, holdings,
     desgloses por par/sesión/día/hora).
  3. Lo POSTea al endpoint de ingesta de Railway, autenticado con un token
     compartido (X-Nexus-Token).

Se ejecuta periódicamente (launchd, cada ~5 min). SOLO LECTURA de Binance.

Configuración (archivo local NO commiteado, p.ej. ~/.nexus/binance.env o
deploy/collector.env), formato KEY=VALUE:
    BINANCE_API_KEY=...
    BINANCE_API_SECRET=...
    NEXUS_INGEST_URL=https://<tu-app>.up.railway.app/m/journal/api/ingest
    NEXUS_INGEST_TOKEN=...
    BINANCE_LOOKBACK_DAYS=365            # opcional

Uso:  python3 -m modules.trading… no: python3 -m modules.journal.collector
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from modules.journal import binance_client as bc
from modules.journal import stats

DATA_DIR = os.path.join(ROOT, "data")
INCOME_PATH = os.path.join(DATA_DIR, "journal_income.json")
# Forward-test que escribe la app de Nexus (poller de trading) en el Mac mini.
SETUPS_PATH = os.path.join(DATA_DIR, "setups.json")
STABLES = {"USDT", "USDC", "BUSD", "FDUSD", "TUSD", "DAI", "USDP"}

# Rutas candidatas del archivo de credenciales (la primera que exista, gana).
ENV_CANDIDATES = [
    os.environ.get("NEXUS_COLLECTOR_ENV", ""),
    os.path.expanduser("~/.nexus/binance.env"),
    os.path.join(ROOT, "deploy", "collector.env"),
]


def log(m):
    print(f"[{time.strftime('%H:%M:%S')}] {m}", flush=True)


def _env_int(name, default):
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return int(raw.strip())
    except (TypeError, ValueError):
        return default


def load_env_file():
    """Carga el primer archivo de credenciales que exista (sin pisar el entorno real)."""
    for path in ENV_CANDIDATES:
        if path and os.path.isfile(path):
            with open(path, "r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
            log(f"credenciales cargadas de {path}")
            return path
    return None


# --- Construcción del payload (misma lógica que tenía el módulo) ---------
def build_payload(lookback_days: int) -> dict:
    now = int(time.time() * 1000)
    payload = {"configured": True, "generated_at_ms": now,
               "lookback_days": lookback_days,
               "futures": {"ok": False}, "spot": {"ok": False}}
    try:
        income = _load_income(now, lookback_days)
        trades = stats.reconstruct_trades(income)
        payload["futures"] = {
            "ok": True,
            "summary": stats.metrics(trades),
            "equity": stats.equity_curve(trades),
            **stats.breakdowns(trades),
            "trades_count": len(trades),
            "open_positions": _open_positions(),
            "balance": _futures_balance(),
        }
    except Exception as exc:  # noqa: BLE001
        payload["futures"] = {"ok": False, "error": str(exc)}
    try:
        payload["spot"] = _spot_holdings()
    except Exception as exc:  # noqa: BLE001
        payload["spot"] = {"ok": False, "error": str(exc)}
    return payload


def _load_income(now, lookback_days):
    os.makedirs(DATA_DIR, exist_ok=True)
    cached = {"rows": [], "last_time": 0}
    if os.path.isfile(INCOME_PATH):
        try:
            with open(INCOME_PATH, "r", encoding="utf-8") as fh:
                cached = json.load(fh)
        except Exception:  # noqa: BLE001
            cached = {"rows": [], "last_time": 0}
    lookback_start = now - lookback_days * 86_400_000
    since = max(int(cached.get("last_time", 0)) + 1, lookback_start)
    if not cached["rows"] or cached["rows"][0]["time"] > lookback_start:
        since = lookback_start
        cached = {"rows": [], "last_time": 0}
    new_rows = bc.futures_income(since, now)
    seen = {(r.get("tranId"), r.get("time"), r.get("incomeType")) for r in cached["rows"]}
    for r in new_rows:
        k = (r.get("tranId"), r.get("time"), r.get("incomeType"))
        if k not in seen:
            seen.add(k)
            cached["rows"].append(r)
    cached["rows"].sort(key=lambda x: int(x["time"]))
    cached["rows"] = [r for r in cached["rows"] if int(r["time"]) >= lookback_start]
    cached["last_time"] = cached["rows"][-1]["time"] if cached["rows"] else now
    with open(INCOME_PATH, "w", encoding="utf-8") as fh:
        json.dump(cached, fh)
    return cached["rows"]


def _open_positions():
    out = []
    for p in bc.futures_positions():
        amt = float(p.get("positionAmt", 0))
        if amt == 0:
            continue
        out.append({"symbol": p.get("symbol"), "side": "LONG" if amt > 0 else "SHORT",
                    "size": abs(amt), "entry": float(p.get("entryPrice", 0)),
                    "mark": float(p.get("markPrice", 0)),
                    "unrealized": round(float(p.get("unRealizedProfit", 0)), 2),
                    "leverage": p.get("leverage")})
    out.sort(key=lambda x: x["unrealized"])
    return out


def _futures_balance():
    usdt = {"asset": "USDT", "wallet": 0.0, "available": 0.0, "unrealized": 0.0}
    for b in bc.futures_balances():
        if b.get("asset") == "USDT":
            usdt = {"asset": "USDT", "wallet": round(float(b.get("balance", 0)), 2),
                    "available": round(float(b.get("availableBalance", 0)), 2),
                    "unrealized": round(float(b.get("crossUnPnl", 0)), 2)}
    return usdt


def _price_value(base: str, qty: float, prices: dict):
    """Valor aproximado en USDT de `qty` del activo `base` (None si no hay precio)."""
    if base in STABLES:
        return qty
    p = prices.get(base + "USDT") or prices.get(base + "FDUSD") or prices.get(base + "BUSD")
    return qty * p if p else None


def _spot_holdings():
    acct = bc.spot_account()
    prices = bc.all_prices()
    holdings = []
    total = 0.0
    for bal in acct.get("balances", []):
        qty = float(bal.get("free", 0)) + float(bal.get("locked", 0))
        if qty <= 0:
            continue
        asset = bal.get("asset")
        # Primero intentamos valorizar el activo tal cual (evita falsos positivos
        # como LDO, que es un token real). Si no hay precio y tiene prefijo "LD",
        # es una posición de Binance Earn (Flexible Savings): el subyacente es el
        # nombre sin "LD" (LDSOL → SOL, LDUSDT → USDT).
        base, earn = asset, False
        value = _price_value(asset, qty, prices)
        if value is None and asset.startswith("LD") and len(asset) > 2:
            cand = asset[2:]
            v2 = _price_value(cand, qty, prices)
            if v2 is not None:
                base, earn, value = cand, True, v2
        if value is not None and value < 1:
            continue
        holdings.append({"asset": base, "earn": earn, "qty": qty,
                         "value": round(value, 2) if value is not None else None})
        total += value or 0
    holdings.sort(key=lambda x: (x["value"] is None, -(x["value"] or 0)))
    return {"ok": True, "total_value": round(total, 2), "holdings": holdings}


# --- Envío a Railway -----------------------------------------------------
def send(payload: dict, url: str, token: str) -> dict:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST", headers={
        "Content-Type": "application/json",
        "X-Nexus-Token": token,
    })
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.load(resp)


def main():
    load_env_file()
    url = os.environ.get("NEXUS_INGEST_URL", "").strip()
    token = os.environ.get("NEXUS_INGEST_TOKEN", "").strip()
    if not url or not token:
        log("❌ falta NEXUS_INGEST_URL o NEXUS_INGEST_TOKEN (revisa el archivo de credenciales)")
        sys.exit(2)
    lookback = _env_int("BINANCE_LOOKBACK_DAYS", 365)

    log(f"leyendo Binance (lookback {lookback} días)…")
    payload = build_payload(lookback)
    fut = payload["futures"]
    spot = payload["spot"]
    log(f"futuros ok={fut.get('ok')} ({fut.get('error', '') if not fut.get('ok') else str(fut.get('trades_count'))+' trades'})")
    log(f"spot ok={spot.get('ok')} ({spot.get('error', '') if not spot.get('ok') else str(len(spot.get('holdings', [])))+' holdings'})")

    try:
        resp = send(payload, url, token)
        log(f"✓ income enviado a Railway: {resp}")
    except Exception as exc:  # noqa: BLE001
        log(f"❌ error enviando income a Railway: {type(exc).__name__}: {exc}")
        sys.exit(1)

    # También enviamos el FORWARD-TEST de setups (lo escribe la app del Mac mini con
    # precios Binance). Así nexux.cl muestra el paper-trading real y persistente.
    send_setups(url, token)


def app_health() -> dict:
    """Salud de la app del Mac mini: pinguea su estado (poller cada ~2s). Si no
    responde o el estado está viejo, la app está caída → el forward-test no avanza.
    Detecta la muerte de la APP (distinto de la muerte del COLECTOR, que se ve por
    la antigüedad de recepción en Railway)."""
    url = os.environ.get("NEXUS_LOCAL_APP", "http://localhost:8800") + "/m/trading/api/state"
    try:
        with urllib.request.urlopen(url, timeout=5) as resp:
            upd = (json.load(resp) or {}).get("updated") or 0
        age = (time.time() * 1000 - upd) / 1000 if upd else None
        return {"alive": age is not None and age < 30, "age_s": round(age, 1) if age is not None else None}
    except Exception as exc:  # noqa: BLE001
        return {"alive": False, "error": type(exc).__name__}


def send_setups(income_url: str, token: str) -> None:
    """Lee el setups.json local (forward-test, Binance) y lo POSTea a Railway."""
    if not os.path.isfile(SETUPS_PATH):
        log("setups.json no existe todavía (la app aún no registró planes)")
        return
    try:
        with open(SETUPS_PATH, "r", encoding="utf-8") as fh:
            setups = json.load(fh)
    except Exception as exc:  # noqa: BLE001
        log(f"no se pudo leer setups.json: {exc}")
        return
    base = income_url.rstrip("/")
    setups_url = base[:-len("/ingest")] + "/ingest_setups" if base.endswith("/ingest") else base + "/ingest_setups"
    health = app_health()
    log(f"salud app Mac mini: {health}")
    payload = {"setups": setups, "generated_at_ms": int(time.time() * 1000),
               "count": len(setups) if isinstance(setups, list) else 0,
               "macmini": health}
    try:
        resp = send(payload, setups_url, token)
        log(f"✓ setups enviados a Railway ({payload['count']}): {resp}")
    except Exception as exc:  # noqa: BLE001
        log(f"❌ error enviando setups: {type(exc).__name__}: {exc}")


if __name__ == "__main__":
    main()
