"""Bot3: la estrategia del curso Bitcoin Traders (playbook.v1) como bot PAPER.

Simulación CAUSAL y determinista sobre OHLCV cerrado (mismo patrón que Bot2):
mismas velas → mismo libro virtual. El "diario" de Bot3 es la reproducción
exacta de lo que la regla habría hecho, sin estado mutable que corromper.

Regla congelada (contrato v1, 2026-08-17 — ver docs/BOT3_CURSO_PROTOCOLO.md):
  zona admitida (OB/FVG de la TF vista o del RECTOR) tocada
  → confirmación iBOS de la TF vista dentro de la ventana
  → solo A FAVOR de la dirección rectora vigente
  → SL en la invalidación de la zona + buffer, TP en la liquidez opuesta
    sin barrer más cercana (as-of, sin mirar el futuro), net RR >= 2
  → una sola posición virtual por mercado; vela ambigua = STOP (conservador).

research_only: sin ejecutor, sin credenciales, sin órdenes, sin contacto con
el diario real, el Bot ni ECON-COHORT-001.
"""
from __future__ import annotations

import bisect

from modules.trading import smc
from modules.trading.smc_course import _bos_events, INT_PIV, STRUCT_PIV, TF_MS

ROUND_TRIP_COST_PCT = 0.0012   # mismo supuesto de costos redondos que Bot2
MIN_NET_RR = 2.0               # regla del curso (ejemplo de S06)
CONF_WINDOW = 30               # velas de la TF vista para confirmar tras el toque
SL_BUFFER_PCT = 0.001          # stop apenas pasada la invalidación de la zona
ZONE_TTL_BARS = 2000           # una zona caduca si nadie la toca en este plazo
MAX_ZONES_SIM = 300            # cota de zonas simuladas (las más recientes)
RECTOR_TF = {"15m": "4h", "1h": "4h", "4h": "1d"}


def _zone_events(candles: list[dict], dur_ms: int) -> list[dict]:
    """Zonas admitidas del curso con su vela de nacimiento y su DISPONIBILIDAD
    causal (fix C-1): el FVG de tres velas se completa recién con el CIERRE de
    la tercera vela → `avail_t = t_nacimiento + duración de la TF`. Nada puede
    tocar/consumir la zona antes de ese instante."""
    n = len(candles)
    out = []
    for bullish in (True, False):
        d = "long" if bullish else "short"
        for f in smc.find_fvgs(candles, 2, n - 1, bullish):
            i = f["idx"]
            avail = candles[i]["t"] + dur_ms
            out.append({"kind": "fvg", "dir": d, "lo": f["lo"], "hi": f["hi"],
                        "born": i, "t": candles[i]["t"], "avail_t": avail})
            ob = smc.find_order_block(candles, max(0, i - 6), i - 2, bullish)
            if ob:
                out.append({"kind": "ob", "dir": d, "lo": ob["lo"], "hi": ob["hi"],
                            "born": i, "t": candles[i]["t"], "avail_t": avail})
    seen, ded = set(), []
    for z in sorted(out, key=lambda z: z["avail_t"]):
        k = (z["kind"], z["dir"], round(z["lo"], 6), round(z["hi"], 6))
        if k in seen:
            continue
        seen.add(k)
        ded.append(z)
    return ded


def _rector_dir_series(rector: list[dict], dur_ms: int) -> list[tuple[int, str]]:
    """Dirección rectora como serie de eventos (t_disponible_ms, long/short).

    Fix C-1: la ruptura se conoce en el CIERRE de la vela que la produce, así
    que el evento se publica en `t + duración`, nunca en la apertura."""
    return [(rector[e["j"]]["t"] + dur_ms, "long" if e["dir"] == "up" else "short")
            for e in _bos_events(rector, STRUCT_PIV)]


def _dir_as_of(series: list[tuple[int, str]], t: int) -> str | None:
    cur = None
    for tt, d in series:
        if tt <= t:
            cur = d
        else:
            break
    return cur


def _target_as_of(candles, sh, sl_pts, j, entry, long):
    """Liquidez opuesta AS-OF la vela j: el swing estructural confirmado más
    cercano más allá de la entrada que nadie ha barrido hasta j."""
    pts = sh if long else sl_pts
    best = None
    for p in pts:
        if p["confirm_idx"] > j:
            continue
        price = p["price"]
        if (price <= entry) if long else (price >= entry):
            continue
        swept = any((candles[k]["h"] > price) if long else (candles[k]["l"] < price)
                    for k in range(p["idx"] + 1, j + 1))
        if swept:
            continue
        if best is None or abs(price - entry) < abs(best - entry):
            best = price
    return best


def simulate(sel: list[dict], rector: list[dict] | None, tf: str) -> dict:
    """Libro virtual completo de la regla del curso sobre la ventana dada."""
    n = len(sel)
    empty = {"trades": [], "descartadas": {}, "abierta": None,
             "summary": {"cerradas": 0, "ganadas": 0, "perdidas": 0,
                         "win_rate": None, "sum_r": 0.0, "avg_r": None,
                         "profit_factor": None}}
    if n < 2 * STRUCT_PIV + 5:
        return empty
    times = [c["t"] for c in sel]
    dur_sel = TF_MS.get(tf, 0)
    rector_tf = RECTOR_TF.get(tf)
    dur_rector = TF_MS.get(rector_tf, dur_sel) if rector else dur_sel
    zones = _zone_events(sel, dur_sel)
    for z in zones:
        z["zona_tf"] = tf
    if rector:
        for z in _zone_events(rector, dur_rector):
            z["zona_tf"] = "rector"
            zones.append(z)
    zones.sort(key=lambda z: z["avail_t"])
    zones = zones[-MAX_ZONES_SIM:]
    ib = _bos_events(sel, INT_PIV)
    sh, sl_pts = smc.swing_points(sel, STRUCT_PIV)
    dir_series = _rector_dir_series(rector if rector else sel,
                                    dur_rector if rector else dur_sel)

    trades = []
    desc: dict[str, int] = {}

    def skip(reason):
        desc[reason] = desc.get(reason, 0) + 1

    open_until = -1
    for z in zones:
        # Fix C-1: el toque solo puede observarse en velas de la TF vista que
        # ABREN cuando la zona ya está disponible (cierre de su formación).
        start = bisect.bisect_left(times, z["avail_t"])
        if start >= n:
            continue
        stop_scan = min(n, start + ZONE_TTL_BARS)
        touch = next((k for k in range(start, stop_scan)
                      if sel[k]["l"] <= z["hi"] and sel[k]["h"] >= z["lo"]), None)
        if touch is None:
            continue
        long = z["dir"] == "long"
        far = z["lo"] if long else z["hi"]
        conf = next((e for e in ib
                     if touch < e["j"] <= touch + CONF_WINDOW
                     and e["dir"] == ("up" if long else "down")), None)
        inval = next((k for k in range(touch, min(n, touch + CONF_WINDOW + 1))
                      if ((sel[k]["c"] < far) if long else (sel[k]["c"] > far))),
                     None)
        if inval is not None and (conf is None or inval < conf["j"]):
            skip("zona invalidada antes de confirmar")
            continue
        if conf is None:
            skip("sin confirmación en la ventana")
            continue
        j = conf["j"]
        if j <= open_until:
            skip("posición virtual ya abierta")
            continue
        # Fix C-1: la decisión ocurre al CIERRE de la vela de entrada; solo
        # cuentan eventos rectores disponibles hasta ese instante.
        rd = _dir_as_of(dir_series, sel[j]["t"] + dur_sel)
        if rd is not None and rd != z["dir"]:
            skip("contra la dirección rectora")
            continue
        entry = sel[j]["c"]
        sl = far * (1 - SL_BUFFER_PCT) if long else far * (1 + SL_BUFFER_PCT)
        risk = abs(entry - sl)
        if risk <= 0:
            continue
        tp = _target_as_of(sel, sh, sl_pts, j, entry, long)
        if tp is None:
            skip("sin liquidez objetivo")
            continue
        gross = abs(tp - entry) / risk
        cost_r = entry * ROUND_TRIP_COST_PCT / risk
        net = gross - cost_r
        if net < MIN_NET_RR:
            skip("net RR < 2")
            continue
        estado, result_r, exit_t = "abierta", None, None
        for k in range(j + 1, n):
            hit_sl = (sel[k]["l"] <= sl) if long else (sel[k]["h"] >= sl)
            hit_tp = (sel[k]["h"] >= tp) if long else (sel[k]["l"] <= tp)
            if hit_sl:                      # conservador: vela ambigua = STOP
                estado, result_r, exit_t = "stop", -1.0 - cost_r, sel[k]["t"]
                open_until = k
                break
            if hit_tp:
                estado, result_r, exit_t = "target", net, sel[k]["t"]
                open_until = k
                break
        if estado == "abierta":
            open_until = n                   # bloquea nuevas entradas
        trades.append({
            "tf": tf, "dir": z["dir"], "zona": z["kind"], "zona_tf": z["zona_tf"],
            "t_zona": z["t"], "t_zona_avail": z["avail_t"],
            "t_toque": sel[touch]["t"], "t_entrada": sel[j]["t"],
            "entry": round(entry, 6), "sl": round(sl, 6), "tp": round(tp, 6),
            "gross_rr": round(gross, 2), "cost_r": round(cost_r, 3),
            "net_rr": round(net, 2), "estado": estado,
            "result_r": round(result_r, 3) if result_r is not None else None,
            "exit_t": exit_t,
        })

    closed = [t for t in trades if t["estado"] in ("stop", "target")]
    wins = [t for t in closed if t["result_r"] > 0]
    losses = [t for t in closed if t["result_r"] <= 0]
    sum_r = sum(t["result_r"] for t in closed)
    gwin = sum(t["result_r"] for t in wins)
    gloss = abs(sum(t["result_r"] for t in losses))
    abierta = next((t for t in trades if t["estado"] == "abierta"), None)
    return {
        "trades": trades[-120:],
        "descartadas": desc,
        "abierta": abierta,
        "summary": {
            "cerradas": len(closed), "ganadas": len(wins), "perdidas": len(losses),
            "win_rate": round(len(wins) / len(closed) * 100, 1) if closed else None,
            "sum_r": round(sum_r, 2),
            "avg_r": round(sum_r / len(closed), 3) if closed else None,
            "profit_factor": round(gwin / gloss, 2) if gloss > 0 else None,
        },
    }
