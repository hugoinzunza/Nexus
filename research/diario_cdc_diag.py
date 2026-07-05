"""Columna paralela DIAGNÓSTICA del Diario: hipótesis "CDC en 8 velas post-toque"
+ simulación estilo `cap03_8` — research puro, SOLO observación.

Qué hace:
  1. Lee los setups del Diario (por defecto `data/setups.json`; acepta cualquier
     copia con `--file`, p.ej. un scp del VPS). **Solo lectura: jamás muta ni
     reescribe el store.**
  2. Para cada setup ACTIVADO (el precio tocó la zona), baja velas PÚBLICAS de
     Binance (fapi/klines, sin credenciales) del tf del plan y calcula:
       - `cdc_confirmed_within_8`: ¿hubo cierre que rompe el último swing
         confirmado (piv=2) en la dirección del plan, DESPUÉS del toque y dentro
         de 8 velas? (misma definición causal de los estudios OOS/abort)
       - `abort_cap03_8_sim_result`: netR simulado con la regla cap03_8 (si no
         hay CDC en 8 velas: stop apretado a -0.3R si va a favor, cierre a
         mercado si va en contra; SL/TP original mandan si tocan antes).
       - `abort_cap03_8_reason` + timestamps usados.
  3. Escribe TODO en un archivo SEPARADO: `data/diagnostics/cdc_abort_diag.json`
     (gitignored, marcado `research_only`). Nada entra al P&L oficial ni a
     `setups.json`, y NADA de esto cierra/aborta trades reales o dry.

Anti-look-ahead: velas cerradas, swings con confirm_idx, el CDC solo puede
ocurrir en velas POSTERIORES a la del toque, el aborto decide en el close de la
vela 8. Este archivo NO importa modules.bot ni escribe en el store del Diario.

Corre:  .venv/bin/python3 research/diario_cdc_diag.py [--file copia_setups.json]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.request

WT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if WT not in sys.path:
    sys.path.insert(0, WT)

from modules.trading.setups_store import _cost_fraction  # noqa: E402  (solo el modelo de costos)
from research import bta_visual_oos as oos  # noqa: E402  (last_confirmed_arrays)

SETUPS_DEFAULT = os.path.join(WT, "data", "setups.json")
OUT_DIR = os.path.join(WT, "data", "diagnostics")
OUT_PATH = os.path.join(OUT_DIR, "cdc_abort_diag.json")

KLINES_URL = "https://fapi.binance.com/fapi/v1/klines"
TF_MS = {"15m": 900_000, "1h": 3_600_000, "4h": 14_400_000, "1D": 86_400_000}
TF_BINANCE = {"15m": "15m", "1h": "1h", "4h": "4h", "1D": "1d"}
WINDOW = 8            # velas post-toque para el CDC (hipótesis del estudio abort)
CAP_R = -0.3
HIST = 240            # velas de historia previas al toque (para swings confirmados)
HORIZON = 500         # velas máx. para resolver la simulación


def fetch_klines(symbol: str, tf: str, start_ms: int, limit: int = 1000) -> list[dict]:
    """Klines PÚBLICOS de Binance Futures (GET sin llaves, solo lectura)."""
    url = (f"{KLINES_URL}?symbol={symbol}&interval={TF_BINANCE[tf]}"
           f"&startTime={start_ms}&limit={limit}")
    req = urllib.request.Request(url, headers={"User-Agent": "nexux-research"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        raw = json.load(resp)
    return [{"t": int(r[0]), "o": float(r[1]), "h": float(r[2]),
             "l": float(r[3]), "c": float(r[4]), "v": float(r[5])} for r in raw]


def _netR(r, entry, sl):
    slf = abs(entry - sl) / entry
    return r if slf <= 0 else r - _cost_fraction(r > 0) / slf


def sim_cap03_8(candles: list[dict], tap_ms: int, long: bool,
                entry: float, sl: float, tp: float) -> dict:
    """Simulación cap03_8 sobre velas CERRADAS posteriores al toque.

    Devuelve dict con cdc_confirmed_within_8, resultado netR, razón y
    timestamps usados. Puro: no muta `candles` ni ningún estado externo.
    """
    risk = (entry - sl) if long else (sl - entry)
    if risk <= 0 or not candles:
        return {"ok": False, "reason": "sin_datos"}
    # vela del toque = la que CONTIENE tap_ms; todo lo decidible parte DESPUÉS
    i_tap = None
    for i, c in enumerate(candles):
        if c["t"] <= tap_ms < c["t"] + (candles[1]["t"] - candles[0]["t"]
                                        if len(candles) > 1 else 1):
            i_tap = i
            break
    if i_tap is None or i_tap + 1 >= len(candles):
        return {"ok": False, "reason": "sin_datos"}

    lh2, ll2 = oos.last_confirmed_arrays(candles, 2)
    i_cdc = None
    for j in range(i_tap + 1, min(i_tap + 1 + WINDOW, len(candles))):
        c = candles[j]
        if (c["l"] <= sl) if long else (c["h"] >= sl):
            break                              # murió por SL antes del CDC
        ref = lh2[j] if long else ll2[j]
        if ref is not None and ((long and c["c"] > ref) or
                                (not long and c["c"] < ref)):
            i_cdc = j
            break

    j_window = i_tap + WINDOW
    reason = None
    r = None
    cap_px = entry + CAP_R * risk if long else entry - CAP_R * risk
    cur_sl = sl
    # La vela del TOQUE también puede tocar SL/TP (después de la activación).
    # Conservador: si su extremo alcanza el SL, cuenta SL (no sabemos el orden
    # intrabar). Sin esto, un SL dentro de la vela de activación se saltaba y
    # el sim cabalgaba hasta TPs irreales (artefacto detectado con ADA 54R).
    j_res = None
    for j in range(i_tap, min(i_tap + 1 + HORIZON, len(candles))):
        c = candles[j]
        if (c["l"] <= cur_sl) if long else (c["h"] >= cur_sl):
            r = ((cur_sl - entry) / risk) if long else ((entry - cur_sl) / risk)
            reason = "sl_original" if cur_sl == sl else "abort_cap_stop"
            j_res = j
            break
        # En la vela del toque NO se acredita TP: pudo ocurrir ANTES de la
        # activación (solo el SL se evalúa ahí, por conservadurismo).
        if j > i_tap and ((c["h"] >= tp) if long else (c["l"] <= tp)):
            r = abs(tp - entry) / risk
            reason = "tp_original" if cur_sl == sl else "tp_tras_cap"
            j_res = j
            break
        if j >= j_window and cur_sl == sl and i_cdc is None:
            # misma definición cap03_8 del estudio: peor que el cap -> fuera a
            # mercado; si no, stop apretado a -0.3R con el TP intacto
            px = c["c"]
            r_now = ((px - entry) / risk) if long else ((entry - px) / risk)
            if r_now <= CAP_R:
                r = r_now
                reason = "abort_mkt"
                break
            cur_sl = cap_px
    if r is None:
        return {"ok": False, "reason": "sin_resolucion",
                "cdc_confirmed_within_8": i_cdc is not None}
    # Un CDC POSTERIOR a la resolución no cuenta (el trade ya estaba muerto).
    if i_cdc is not None and j_res is not None and i_cdc > j_res:
        i_cdc = None
    if i_cdc is not None and reason in ("sl_original", "tp_original"):
        reason = "cdc_a_tiempo_" + ("tp" if reason == "tp_original" else "sl")
    return {
        "ok": True,
        "cdc_confirmed_within_8": i_cdc is not None,
        "cdc_ts": candles[i_cdc]["t"] // 1000 if i_cdc is not None else None,
        "tap_bar_ts": candles[i_tap]["t"] // 1000,
        "window_end_ts": candles[min(j_window, len(candles) - 1)]["t"] // 1000,
        "sim_netR": round(_netR(r, entry, sl), 3),
        "reason": reason,
    }


def diagnose(setups: list[dict], fetch=fetch_klines, max_setups: int | None = None):
    """Corre el diagnóstico sobre una lista de setups (NO la muta). Devuelve
    (registros, resumen). `fetch` inyectable para tests sin red."""
    recs = []
    activados = [s for s in setups
                 if s.get("ts_activated") and s.get("entry") and s.get("sl")
                 and s.get("tp") and s.get("dir") in ("long", "short")]
    if max_setups:
        activados = activados[-max_setups:]
    for s in activados:
        tf = s.get("cdc_tf") or s.get("poi_tf") or "1h"
        if tf not in TF_MS:
            tf = "1h"
        symbol = (s.get("pair") or "").replace("_", "")
        tap_ms = int(s["ts_activated"]) * 1000
        start = tap_ms - HIST * TF_MS[tf]
        try:
            candles = fetch(symbol, tf, start)
        except Exception as exc:  # red caída: se reporta, no se inventa
            candles = []
            err = str(exc)[:80]
        sim = sim_cap03_8(candles, tap_ms, s["dir"] == "long",
                          float(s["entry"]), float(s["sl"]), float(s["tp"]))
        recs.append({
            "research_only": True,
            "setup_id": f"{s.get('key')}:{s.get('ts_created')}",
            "pair": s.get("pair"), "dir": s.get("dir"), "tf": tf,
            "rr": s.get("rr"), "status": s.get("status"),
            "result_r_real": s.get("result_r"),
            "ts_activated": s.get("ts_activated"),
            "cdc_post_touch_window_8": WINDOW,
            "cdc_confirmed_within_8": sim.get("cdc_confirmed_within_8"),
            "abort_cap03_8_sim_result": sim.get("sim_netR"),
            "abort_cap03_8_reason": sim.get("reason"),
            "sim_ok": sim.get("ok", False),
            "timestamps": {"tap_bar": sim.get("tap_bar_ts"),
                           "window_end": sim.get("window_end_ts"),
                           "cdc": sim.get("cdc_ts")},
        })
        time.sleep(0.15)  # cortesía con el rate limit público

    ok = [r for r in recs if r["sim_ok"]]
    con = [r for r in ok if r["cdc_confirmed_within_8"]]
    sin = [r for r in ok if not r["cdc_confirmed_within_8"]]

    def avg(rows, k):
        vals = [r[k] for r in rows if isinstance(r.get(k), (int, float))]
        return round(sum(vals) / len(vals), 3) if vals else None

    resumen = {
        "research_only": True,
        "nota": ("DIAGNOSTICO paralelo, solo observacion. No es gate, no altera "
                 "setups ni P&L oficial, no cierra trades reales/dry."),
        "n_activados": len(activados), "n_simulados": len(ok),
        "n_cdc_dentro_de_8": len(con), "n_sin_cdc": len(sin),
        "avg_sim_netR_con_cdc": avg(con, "abort_cap03_8_sim_result"),
        "avg_sim_netR_sin_cdc": avg(sin, "abort_cap03_8_sim_result"),
        "avg_real_con_cdc": avg([r for r in con if r["result_r_real"] is not None],
                                "result_r_real"),
        "avg_real_sin_cdc": avg([r for r in sin if r["result_r_real"] is not None],
                                "result_r_real"),
    }
    return recs, resumen


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", default=SETUPS_DEFAULT,
                    help="ruta a setups.json (o una copia scp del VPS)")
    ap.add_argument("--max", type=int, default=None, help="limitar setups (debug)")
    args = ap.parse_args()
    setups = json.load(open(args.file))
    recs, resumen = diagnose(setups, max_setups=args.max)
    os.makedirs(OUT_DIR, exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8") as fh:
        json.dump({"meta": resumen, "registros": recs}, fh, ensure_ascii=False, indent=1)
    print(f"diagnóstico: {OUT_PATH}")
    print(json.dumps(resumen, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
