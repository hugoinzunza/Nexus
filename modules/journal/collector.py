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
def build_payload(lookback_days: int, income_path: str = INCOME_PATH) -> dict:
    now = int(time.time() * 1000)
    payload = {"configured": True, "generated_at_ms": now,
               "lookback_days": lookback_days,
               "futures": {"ok": False}, "spot": {"ok": False}}
    try:
        income = _load_income(now, lookback_days, income_path)
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


def _load_income(now, lookback_days, income_path=INCOME_PATH):
    os.makedirs(DATA_DIR, exist_ok=True)
    cached = {"rows": [], "last_time": 0}
    if os.path.isfile(income_path):
        try:
            with open(income_path, "r", encoding="utf-8") as fh:
                cached = json.load(fh)
        except Exception:  # noqa: BLE001
            cached = {"rows": [], "last_time": 0}
    lookback_start = now - lookback_days * 86_400_000
    # De dónde tenemos cobertura REAL, que no es lo mismo que dónde empieza la fila más
    # vieja. Antes se infería con `cached["rows"][0]["time"] > lookback_start`, o sea
    # "si mi fila más vieja es más nueva que la ventana, me faltan datos". Pero la
    # subcuenta nació en junio de 2026: nunca va a existir income de hace 365 días, así
    # que la condición no se cumplía JAMÁS y se re-leía el año entero cada 90 segundos.
    # Con `futures_income` en peso 30 y ~53 páginas por corrida, eso son ~1590 de peso
    # por corrida: medido, la IP vivía en 1620 de 2400 y el watchdog quedaba ciego el
    # 8% de los ciclos por -1003. Ausencia de datos no es ausencia de cobertura.
    cubierto = cached.get("covered_from")
    if cubierto is None or int(cubierto) > lookback_start:
        since = lookback_start
        cached = {"rows": [], "last_time": 0}
        cubierto = lookback_start
    else:
        since = max(int(cached.get("last_time", 0)) + 1, lookback_start)
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
    # La cobertura es hasta dónde PREGUNTAMOS, y solo puede ir hacia atrás. Como
    # `lookback_start` avanza con el reloj, una vez que cubierto <= lookback_start la
    # condición se mantiene sola y no se vuelve a pedir el histórico completo.
    cached["covered_from"] = int(min(int(cubierto), int(cached.get("covered_from") or cubierto)))
    with open(income_path, "w", encoding="utf-8") as fh:
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


def _avg_cost(symbol):
    """Costo promedio del holding ACTUAL por media móvil sobre el historial de trades
    (cada compra actualiza el promedio; cada venta baja la cantidad, no el promedio).
    Devuelve (avg_cost, qty_trades) o (None, 0) si no hay trades."""
    try:
        trades = bc.spot_trades(symbol)
    except Exception:  # noqa: BLE001 - el par puede no existir / sin permiso
        return None, 0.0
    if not trades:
        return None, 0.0
    qty_pos, avg = 0.0, 0.0
    for t in sorted(trades, key=lambda x: x.get("time", 0)):
        price = float(t.get("price", 0))
        q = float(t.get("qty", 0))
        if t.get("isBuyer"):
            new = qty_pos + q
            avg = (avg * qty_pos + price * q) / new if new > 0 else 0.0
            qty_pos = new
        else:
            qty_pos = max(0.0, qty_pos - q)
    return (round(avg, 8) if avg > 0 else None), qty_pos


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
        # Precio actual, costo promedio (del historial de trades USDT) y PnL.
        cur = prices.get(base + "USDT")
        avg_cost, pnl, pnl_pct = None, None, None
        if cur and base not in STABLES:
            avg_cost, _ = _avg_cost(base + "USDT")
            if avg_cost:
                pnl = round((cur - avg_cost) * qty, 2)
                pnl_pct = round((cur / avg_cost - 1) * 100, 2)
        holdings.append({"asset": base, "earn": earn, "qty": qty,
                         "value": round(value, 2) if value is not None else None,
                         "price": round(cur, 6) if cur else None,
                         "avg_cost": avg_cost, "pnl": pnl, "pnl_pct": pnl_pct})
        total += value or 0
    holdings.sort(key=lambda x: (x["value"] is None, -(x["value"] or 0)))
    return {"ok": True, "total_value": round(total, 2), "holdings": holdings}


# --- Envío a Railway -----------------------------------------------------
def send(payload: dict, url: str, token: str) -> dict:
    data = json.dumps(payload).encode("utf-8")
    # Reintentos ante blips de red / redeploy de Railway (que tarda ~30-120s). Si
    # aun así falla, el próximo ciclo (90s) reenvía el snapshot actual (idempotente).
    last = None
    for intento in range(3):
        try:
            req = urllib.request.Request(url, data=data, method="POST", headers={
                "Content-Type": "application/json",
                "X-Nexus-Token": token,
            })
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.load(resp)
        except Exception as exc:  # noqa: BLE001 - reintenta y propaga el último
            last = exc
            if intento < 2:
                time.sleep(3 * (intento + 1))
    raise last


# --- Colección multi-usuario (Fase C: bóveda) ----------------------------
def _api_base(ingest_url: str) -> str:
    """De la URL de ingesta (.../m/journal/api/ingest) saca la base .../m/journal/api."""
    base = ingest_url.rstrip("/")
    return base[:-len("/ingest")] if base.endswith("/ingest") else base


def _post_json(url: str, payload: dict, token: str) -> dict:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST", headers={
        "Content-Type": "application/json", "X-Nexus-Token": token})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.load(resp)


def fetch_connections(api_base: str, token: str) -> list:
    try:
        resp = _post_json(api_base + "/connections", {}, token)
        return resp.get("connections", []) if isinstance(resp, dict) else []
    except Exception as exc:  # noqa: BLE001
        log(f"❌ no se pudieron traer las conexiones: {type(exc).__name__}: {exc}")
        return []


def report_status(api_base: str, token: str, user_id: int, status: str, detail=None) -> None:
    try:
        _post_json(api_base + "/connection-status",
                   {"user_id": user_id, "status": status, "detail": detail}, token)
    except Exception as exc:  # noqa: BLE001
        log(f"  user {user_id}: no se pudo reportar estado ({status}): {exc}")


def collect_connections(ingest_url: str, token: str, lookback: int) -> None:
    """Itera las conexiones de exchange de los usuarios: descifra la llave con la KEK
    privada (solo en el VPS), verifica read-only si está pendiente, y colecta por
    usuario empujando a Railway con su user_id. La llave en claro solo vive en memoria."""
    try:
        from core import vault
    except Exception as exc:  # noqa: BLE001
        log(f"bóveda: no se pudo importar core.vault ({exc}); omito multi-usuario")
        return
    priv = vault.private_pem()
    if not priv:
        log("bóveda: sin clave privada (NEXUX_KEK_PRIVATE / ~/.nexus/kek_private.pem); omito multi-usuario")
        return
    api_base = _api_base(ingest_url)
    conns = fetch_connections(api_base, token)
    if not conns:
        return
    log(f"conexiones multi-usuario: {len(conns)}")
    for c in conns:
        uid = c.get("user_id")
        sealed = c.get("sealed")
        status = c.get("status")
        if uid is None or not isinstance(sealed, dict):
            continue
        try:
            api_key, api_secret = vault.unseal_credentials(sealed, priv)
        except Exception:  # noqa: BLE001
            log(f"  user {uid}: no se pudo descifrar la llave")
            report_status(api_base, token, uid, "error", "no se pudo descifrar la llave")
            continue
        # Verificación read-only (solo si está pendiente): rechaza retiros/transferencias.
        if status == "pending":
            ok, detail = bc.verify_read_only(api_key, api_secret)
            report_status(api_base, token, uid, "active" if ok else "rejected", detail)
            log(f"  user {uid}: verificación → {'active' if ok else 'rejected'} ({detail})")
            if not ok:
                continue
        # Colecta con la llave del usuario (env-swap; el proceso es secuencial).
        prev_k = os.environ.get("BINANCE_API_KEY")
        prev_s = os.environ.get("BINANCE_API_SECRET")
        os.environ["BINANCE_API_KEY"] = api_key
        os.environ["BINANCE_API_SECRET"] = api_secret
        try:
            income_path = os.path.join(DATA_DIR, f"journal_income_{uid}.json")
            payload = build_payload(lookback, income_path=income_path)
            payload["user_id"] = uid
            send(payload, ingest_url, token)
            fut_ok = payload["futures"].get("ok")
            log(f"  user {uid}: futuros ok={fut_ok}, spot ok={payload['spot'].get('ok')} → enviado")
            if not fut_ok:
                report_status(api_base, token, uid, "error", payload["futures"].get("error"))
        except Exception as exc:  # noqa: BLE001
            log(f"  user {uid}: error colectando: {type(exc).__name__}: {exc}")
            report_status(api_base, token, uid, "error", str(exc))
        finally:
            # Restaura la llave previa (la de Hugo) y borra la del usuario de memoria.
            if prev_k is not None:
                os.environ["BINANCE_API_KEY"] = prev_k
            else:
                os.environ.pop("BINANCE_API_KEY", None)
            if prev_s is not None:
                os.environ["BINANCE_API_SECRET"] = prev_s
            else:
                os.environ.pop("BINANCE_API_SECRET", None)
            del api_key, api_secret


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

    # Multi-usuario (Fase C): colecta las cuentas de los beta que conectaron su Binance.
    try:
        collect_connections(url, token, lookback)
    except Exception as exc:  # noqa: BLE001
        log(f"❌ error en colección multi-usuario: {type(exc).__name__}: {exc}")


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
