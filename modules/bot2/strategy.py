"""Motor research de la estrategia básica tendencial CreceTrader.

No contiene conectores de exchange, credenciales ni órdenes. Produce candidatos y
un libro virtual reproducible a partir de OHLCV cerrado.
"""
from __future__ import annotations

from modules.inteligencia import fases as F
from modules.inteligencia import precio as P

PIV = 5
ATR_PERIOD = 14
ATR_BUFFER = 0.10
MIN_NET_RR = 2.0
MAX_WAIT_BARS = 120
ROUND_TRIP_COST_PCT = 0.0012
VARIANTS = ("teacher_2close", "first_close", "structure_break")
PANORAMA = {
    "1h": ("4h", "1d"),
    "4h": ("1d", "1w"),
    "1d": ("1w",),
}


def atr_values(velas: list[dict], period: int = ATR_PERIOD) -> list[float | None]:
    salida = [None] * len(velas)
    trs = []
    for i, vela in enumerate(velas):
        prev = float(velas[i - 1]["c"]) if i else float(vela["o"])
        tr = max(float(vela["h"]) - float(vela["l"]),
                 abs(float(vela["h"]) - prev),
                 abs(float(vela["l"]) - prev))
        trs.append(tr)
        if i >= period - 1:
            salida[i] = sum(trs[i - period + 1:i + 1]) / period
    return salida


def _bucket_t(t: int, tf: str) -> int:
    paso = P.TF_MS[tf]
    if tf != "1w":
        return (t // paso) * paso
    # 1970-01-01 fue jueves; desplazar tres días hace que el bucket comience lunes.
    offset = 3 * P.TF_MS["1d"]
    return ((t + offset) // paso) * paso - offset


def agregar(velas: list[dict], tf: str) -> list[dict]:
    grupos = []
    actual = None
    for vela in velas:
        bucket = _bucket_t(int(vela["t"]), tf)
        if actual is None or actual["t"] != bucket:
            actual = {"t": bucket, "o": float(vela["o"]), "h": float(vela["h"]),
                      "l": float(vela["l"]), "c": float(vela["c"]),
                      "v": float(vela.get("v") or 0)}
            grupos.append(actual)
        else:
            actual["h"] = max(actual["h"], float(vela["h"]))
            actual["l"] = min(actual["l"], float(vela["l"]))
            actual["c"] = float(vela["c"])
            actual["v"] += float(vela.get("v") or 0)
    return grupos


def _trend_as_of(velas: list[dict], tf: str, decision_t: int,
                 piv: int = PIV) -> str:
    disponibles = [v for v in velas if int(v["t"]) + P.TF_MS[tf] <= decision_t]
    return P.estructura(disponibles, piv)["tendencia"]


def _context_series(velas: list[dict], tf: str) -> dict[str, list[dict]]:
    return {superior: agregar(velas, superior) for superior in PANORAMA[tf]}


def _context_ok(contexto: dict[str, list[dict]], side: str,
                decision_t: int) -> tuple[bool, dict, str]:
    esperada = "alcista" if side == "long" else "bajista"
    tendencias = {
        tf: _trend_as_of(serie, tf, decision_t)
        for tf, serie in contexto.items()
    }
    conocidas = [v for v in tendencias.values() if v in ("alcista", "bajista")]
    contraria = "bajista" if esperada == "alcista" else "alcista"
    # El curso pide panorama, pero no define cómo resolver un TF indefinido o mixto.
    # Para no convertir esa ambigüedad en cero muestras, el laboratorio solo veta
    # cuando todas las lecturas conocidas son contrarias. La etiqueta queda guardada
    # para comparar luego contra una política estricta sin reescribir el pasado.
    if conocidas and all(v == contraria for v in conocidas):
        return False, tendencias, "opuesto"
    if conocidas and all(v == esperada for v in conocidas):
        return True, tendencias, "alineado"
    return True, tendencias, "mixto_o_indefinido"


def _line_value(a: dict, b: dict, idx: int) -> float:
    if b["idx"] == a["idx"]:
        return float(b["price"])
    slope = (float(b["price"]) - float(a["price"])) / (b["idx"] - a["idx"])
    return float(a["price"]) + slope * (idx - a["idx"])


def _phase_event(velas: list[dict], ciclo: dict, variant: str,
                 points: dict, atrs: list[float | None]) -> dict:
    side = ciclo["side"]
    long = side == "long"
    a, b, c = ciclo["origin"], ciclo["impulse_end"], ciclo["correction_end"]
    recorrido = float(b["price"]) - float(a["price"])
    fib = float(a["price"]) + 0.618 * recorrido
    highs, lows = points["highs"], points["lows"]
    max_i = min(len(velas) - 2, ciclo["available_idx"] + MAX_WAIT_BARS)
    rechazos = {"sin_hl": 0, "sin_referencia": 0, "sin_evento": 0}

    for i in range(ciclo["available_idx"] + 1, max_i + 1):
        vela = velas[i]
        if (long and float(vela["l"]) <= float(a["price"])) or \
           ((not long) and float(vela["h"]) >= float(a["price"])):
            return {"event": None, "reason": "fase invalidada", "detail": rechazos}

        piv_lado = lows if long else highs
        hl = [p for p in piv_lado
              if p["idx"] > c["idx"] and p["confirm_idx"] <= i]
        hl = [p for p in hl if (p["price"] > c["price"] if long
                                else p["price"] < c["price"])]
        if not hl:
            rechazos["sin_hl"] += 1
            continue
        ultimo_hl = hl[-1]

        piv_ref = highs if long else lows
        refs = [p for p in piv_ref
                if c["idx"] < p["idx"] < ultimo_hl["idx"]
                and p["confirm_idx"] <= i]
        if not refs:
            rechazos["sin_referencia"] += 1
            continue
        ref = refs[-1]
        if not (ref["price"] < b["price"] if long else ref["price"] > b["price"]):
            continue
        linea = _line_value(b, ref, i)
        umbral_teacher = (max(fib, float(ref["price"]), linea) if long
                           else min(fib, float(ref["price"]), linea))
        umbral_structure = float(ref["price"])
        close = float(vela["c"])
        bullish = close > float(vela["o"])
        pasa_structure = close > umbral_structure if long else close < umbral_structure
        if variant == "structure_break":
            pasa = pasa_structure
        else:
            pasa = (close > umbral_teacher if long else close < umbral_teacher)
            pasa = pasa and (bullish if long else not bullish)
            if pasa and variant == "teacher_2close":
                if i <= 0:
                    pasa = False
                else:
                    previa = velas[i - 1]
                    linea_previa = _line_value(b, ref, i - 1)
                    umbral_previo = (max(fib, float(ref["price"]), linea_previa) if long
                                     else min(fib, float(ref["price"]), linea_previa))
                    close_previo = float(previa["c"])
                    color_previo = close_previo > float(previa["o"])
                    pasa = ((close_previo > umbral_previo and color_previo) if long
                            else (close_previo < umbral_previo and not color_previo))
        if not pasa:
            rechazos["sin_evento"] += 1
            continue

        entry_idx = i + 1
        atr = atrs[i]
        if atr is None or atr <= 0:
            return {"event": None, "reason": "ATR no disponible", "detail": rechazos}
        entry_raw = float(velas[entry_idx]["o"])
        entry = entry_raw * (1.0003 if long else 0.9997)
        structural = min(float(c["price"]), float(ultimo_hl["price"])) if long \
            else max(float(c["price"]), float(ultimo_hl["price"]))
        stop = structural - ATR_BUFFER * atr if long else structural + ATR_BUFFER * atr
        risk = entry - stop if long else stop - entry
        if risk <= 0:
            return {"event": None, "reason": "stop inválido", "detail": rechazos}

        candidatos = []
        for ratio in (1.25, 1.50, 1.618, 2.00):
            precio = float(a["price"]) + ratio * recorrido
            if (precio > entry if long else precio < entry):
                candidatos.append((precio, f"proyección {ratio:g}"))
        if not candidatos:
            return {"event": None, "reason": "sin objetivo causal", "detail": rechazos}
        target, target_type = min(candidatos, key=lambda x: abs(x[0] - entry))
        obstaculos = [
            float(p["price"]) for p in (highs if long else lows)
            if p["confirm_idx"] <= i
            and ((entry < p["price"] < target) if long
                 else (target < p["price"] < entry))
        ]
        gross_rr = abs(target - entry) / risk
        cost_r = entry * ROUND_TRIP_COST_PCT / risk
        net_rr = gross_rr - cost_r
        event = {
            "cycle_id": ciclo["id"], "side": side, "variant": variant,
            "signal_idx": i, "signal_t": int(vela["t"]),
            "entry_idx": entry_idx, "entry_t": int(velas[entry_idx]["t"]),
            "entry": entry, "stop": stop, "target": target,
            "target_type": target_type, "gross_rr": gross_rr,
            "cost_r": cost_r, "net_rr": net_rr, "fib_61_8": fib,
            "obstacles_before_target": len(obstaculos),
            "first_obstacle": (min(obstaculos) if long and obstaculos
                               else max(obstaculos) if obstaculos else None),
            "reference": float(ref["price"]), "trendline": linea,
            "higher_low": float(ultimo_hl["price"]),
            "phase_i": ciclo["phase_i"], "phase_ii": ciclo["phase_ii"],
            "phase_iii": {
                "label": "III", "start_idx": c["idx"], "end_idx": i,
                "start_t": c["pivot_t"], "end_t": int(vela["t"]),
                "start_price": float(c["price"]), "end_price": close,
                "available_at": int(vela["t"]) + P.TF_MS[ciclo["tf"]],
            },
        }
        return {"event": event, "reason": None, "detail": rechazos}
    return {"event": None, "reason": "evento no apareció a tiempo", "detail": rechazos}


def _simulate(velas: list[dict], event: dict) -> dict:
    long = event["side"] == "long"
    risk = abs(event["entry"] - event["stop"])
    for i in range(event["entry_idx"], len(velas)):
        vela = velas[i]
        stop_hit = float(vela["l"]) <= event["stop"] if long \
            else float(vela["h"]) >= event["stop"]
        target_hit = float(vela["h"]) >= event["target"] if long \
            else float(vela["l"]) <= event["target"]
        if stop_hit:
            return {**event, "status": "loss", "exit_idx": i,
                    "exit_t": int(vela["t"]), "result_r": -1.0 - event["cost_r"]}
        if target_hit:
            return {**event, "status": "win", "exit_idx": i,
                    "exit_t": int(vela["t"]), "result_r": event["net_rr"]}
    last = float(velas[-1]["c"])
    unrealized = ((last - event["entry"]) if long else (event["entry"] - last)) / risk
    return {**event, "status": "open", "exit_idx": None, "exit_t": None,
            "result_r": unrealized - event["cost_r"]}


def analyze(velas: list[dict], tf: str, variant: str) -> dict:
    if variant not in VARIANTS:
        raise ValueError("variante no habilitada")
    if tf not in PANORAMA:
        raise ValueError("temporalidad no habilitada")
    points = F.pivotes_confirmados(velas, tf, PIV)
    ciclos = F.ciclos_confirmados(velas, tf, PIV)
    atrs = atr_values(velas)
    contexto = _context_series(velas, tf)
    candidatos = []
    eventos = []
    rejected = {}
    for ciclo in ciclos:
        resultado = _phase_event(velas, ciclo, variant, points, atrs)
        if not resultado["event"]:
            reason = resultado["reason"]
            rejected[reason] = rejected.get(reason, 0) + 1
            candidatos.append({"cycle_id": ciclo["id"], "side": ciclo["side"],
                               "status": "rejected", "reason": reason,
                               "available_at": ciclo["available_at"]})
            continue
        event = resultado["event"]
        decision_t = int(velas[event["signal_idx"]]["t"]) + P.TF_MS[tf]
        ok_context, tendencias, context_label = _context_ok(
            contexto, event["side"], decision_t)
        if not ok_context:
            reason = "panorama superior no alineado"
            rejected[reason] = rejected.get(reason, 0) + 1
            candidatos.append({"cycle_id": ciclo["id"], "side": ciclo["side"],
                               "status": "rejected", "reason": reason,
                               "available_at": ciclo["available_at"],
                               "context": tendencias,
                               "context_label": context_label})
            continue
        if event["net_rr"] < MIN_NET_RR:
            reason = "RR neto menor a 2"
            rejected[reason] = rejected.get(reason, 0) + 1
            candidatos.append({"cycle_id": ciclo["id"], "side": ciclo["side"],
                               "status": "rejected", "reason": reason,
                               "available_at": ciclo["available_at"],
                               "net_rr": round(event["net_rr"], 3)})
            continue
        event["context"] = tendencias
        event["context_label"] = context_label
        eventos.append(event)
        candidatos.append({"cycle_id": ciclo["id"], "side": ciclo["side"],
                           "status": "accepted", "reason": None,
                           "available_at": ciclo["available_at"],
                           "signal_t": event["signal_t"]})

    # Un libro por variante no abre otra posición en el mismo par/TF hasta cerrar.
    trades = []
    blocked_until = -1
    for event in sorted(eventos, key=lambda e: e["entry_idx"]):
        if event["entry_idx"] <= blocked_until:
            rejected["posición virtual ya abierta"] = \
                rejected.get("posición virtual ya abierta", 0) + 1
            continue
        trade = _simulate(velas, event)
        trades.append(trade)
        blocked_until = trade["exit_idx"] if trade["exit_idx"] is not None \
            else len(velas)
    closed = [t for t in trades if t["status"] != "open"]
    results = [float(t["result_r"]) for t in closed]
    equity = 0.0
    peak = 0.0
    max_dd = 0.0
    for result in results:
        equity += result
        peak = max(peak, equity)
        max_dd = max(max_dd, peak - equity)
    return {
        "research_only": True, "execution_enabled": False,
        "strategy_id": "crecetrader_basic_trend_v1",
        "tf": tf, "variant": variant,
        "rules": {
            "pivot": "5+1+5", "correction_zone": [0.382, 0.618],
            "entry": "apertura siguiente + slippage adverso",
            "stop": "extremo estructural + 0,10 ATR",
            "target": "primera proyección de fase alcanzable",
            "obstacles": "pivotes causales intermedios registrados, no omitidos",
            "min_net_rr": MIN_NET_RR, "management": "salida completa",
        },
        "summary": {
            "cycles": len(ciclos), "accepted_events": len(eventos),
            "trades": len(trades), "closed": len(closed),
            "wins": sum(t["status"] == "win" for t in closed),
            "win_rate": (sum(t["status"] == "win" for t in closed) / len(closed)
                         if closed else None),
            "avg_r": sum(results) / len(results) if results else None,
            "total_r": sum(results), "max_drawdown_r": max_dd,
            "open": sum(t["status"] == "open" for t in trades),
        },
        "rejected": rejected,
        "candidates": candidatos[-40:],
        "trades": trades[-80:],
        "phases": F.fases_para_grafico(velas, tf, PIV, limit=12),
    }
