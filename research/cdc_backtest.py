"""Backtest de investigación: ¿qué APORTA el CDC (Cambio De Carácter / CHoCH)?

Contexto: el indicador "Bitcoin Traders Academy" (Ing. Carlos García) usa el CDC
como CONFIRMACIÓN discrecional en el POI correcto del lado correcto, no como regla
ciega. Acá aislamos su aporte corriendo TRES variantes sobre el MISMO universo de
POIs (réplica SMC POI multi-TF ya validada en el repo):

  A   POI solo            → entra al TOQUE del POI (vela siguiente).
  B0  POI + CDC mecánico  → exige que el cierre rompa el swing en la MISMA vela del
                            toque (lo que colapsó la muestra anoche).
  B   POI + CDC contexto  → toca el POI en descuento/premium, ESPERA a que aparezca
                            el CDC (cierre rompe el último swing relevante) dentro de
                            una ventana, y recién ahí entra (vela siguiente).

Cada POI tapeado genera a lo más UN trade por variante (correspondencia 1:1 de
setups). El SL es el mismo (bajo el POI/barrido) en las tres; el TP es R:R fijo
(headline) o "siguiente liquidez opuesta sin barrer" (robustez). Todo en múltiplos R.

Anti-repaint estricto (idéntico al motor del repo):
  - POIs de TFs superiores solo cuando su vela está CERRADA (t_conf = cierre).
  - El CDC se detecta SOLO con cierres hasta la vela actual (cero look-ahead); los
    swings usan confirm_idx (pivote conocido recién lookback velas después).
  - Señal al cierre de la vela; entrada en la APERTURA de la siguiente (engine.simulate).
Costos: 0.05%/lado + 0.02% slippage por fill (se reporta con y sin costos).
Salida: research/cdc_results.json
"""
from __future__ import annotations

import json
import os
import sys

WT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # raíz del worktree
if WT not in sys.path:
    sys.path.insert(0, WT)

from modules.trading import smc, engine            # noqa: E402
from modules.trading.strategies import detect_pois  # noqa: E402
from modules.trading.backtest import metrics        # noqa: E402

DATA_DIR = "/Users/hugh/Nexus/data"   # caché de klines (gitignored, repo principal)
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cdc_results.json")

PAIRS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "ADAUSDT", "DOGEUSDT"]
BASE_TFS = ["15m", "1h"]            # TF de entrada (scalp / swing)
POI_SOURCES = ["1h", "4h", "1d"]   # de dónde salen los POIs (multi-TF, como el indicador)

# Parámetros (fijados a priori, no tuneados sobre OOS).
PIV = 2                  # lookback de pivotes (estructura de corto plazo para CDC)
DISP = 1.0              # displacement mínimo del impulso (en ATR) para validar el FVG
MAX_AGE_DAYS = 30      # un POI deja de ser válido tras 30 días sin tocarse
CDC_WINDOW = 16        # velas que esperamos el CDC tras tocar el POI (variante B)
STOP_BUF = 0.0005      # colchón bajo/sobre el stop
RR_FIXED = 2.0         # R:R objetivo (headline). Robustez: 3.0 y "liquidez".
MIN_RR = 2.0           # R:R mínimo exigido en modo "liquidez"
IS_FRACTION = 0.70     # split temporal 70/30 por par/TF
WF_WINDOWS = 5         # ventanas walk-forward

TF_MS = {"15m": 900_000, "1h": 3_600_000, "4h": 14_400_000, "1d": 86_400_000}


def load(symbol, tf):
    path = os.path.join(DATA_DIR, f"klines_{symbol}_{tf}.json")
    if not os.path.isfile(path):
        return None
    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    data.sort(key=lambda c: c["t"])
    return data


def conf_prices(points, n):
    """Precio del swing más reciente CONFIRMADO (confirm_idx<=j) en cada vela j.
    Anti-look-ahead: un pivote se conoce recién `piv` velas después de formarse."""
    out = [None] * n
    evt = sorted(points, key=lambda p: p["confirm_idx"])
    pi = 0
    cur = None
    for j in range(n):
        while pi < len(evt) and evt[pi]["confirm_idx"] <= j:
            cur = evt[pi]["price"]
            pi += 1
        out[j] = cur
    return out


def liquidity_tp(direction, entry, idx_now, highs, lows, conf_hi_pts, conf_lo_pts):
    """Siguiente liquidez opuesta SIN BARRER: el swing confirmado más cercano por
    encima (long) / debajo (short) de la entrada que el precio no haya traspasado
    desde que se formó. Devuelve el precio o None."""
    if direction == "long":
        cands = sorted((p for p in conf_hi_pts
                        if p["confirm_idx"] <= idx_now and p["price"] > entry),
                       key=lambda p: p["price"])
        for p in cands:
            after = highs[p["idx"] + 1: idx_now + 1]
            if not after or max(after) < p["price"]:   # sin barrer
                return p["price"]
    else:
        cands = sorted((p for p in conf_lo_pts
                        if p["confirm_idx"] <= idx_now and p["price"] < entry),
                       key=lambda p: -p["price"])
        for p in cands:
            after = lows[p["idx"] + 1: idx_now + 1]
            if not after or min(after) > p["price"]:
                return p["price"]
    return None


def build_signals(base, pois, rr_mode):
    """Recorre las velas base y produce las señales de A, B0 y B compartiendo el
    MISMO pool de POIs. rr_mode in {"fixed","liquidity"}."""
    n = len(base)
    opens = [c["o"] for c in base]
    highs = [c["h"] for c in base]
    lows = [c["l"] for c in base]
    closes = [c["c"] for c in base]
    sh, sl = smc.swing_points(base, PIV)
    last_sh = conf_prices(sh, n)   # swing high confirmado más reciente por vela
    last_sl = conf_prices(sl, n)
    max_age = MAX_AGE_DAYS * 86_400_000

    sigA, sigB0, sigB = [], [], []

    def mk(j, poi):
        """Construye la señal (i,dir,stop,rr); None si no califica (RR<min en liquidez)."""
        if j + 1 >= n:
            return None
        d = poi["dir"]
        stop = poi["stop"] * (1 - STOP_BUF) if d == "long" else poi["stop"] * (1 + STOP_BUF)
        if rr_mode == "fixed":
            return (j, d, stop, RR_FIXED)
        entry = opens[j + 1]                      # entrada real (apertura siguiente)
        risk = (entry - stop) if d == "long" else (stop - entry)
        if risk <= 0:
            return None
        tp = liquidity_tp(d, entry, j, highs, lows, sh, sl)
        if tp is None:
            return None
        rr_eff = ((tp - entry) if d == "long" else (entry - tp)) / risk
        if rr_eff < MIN_RR:
            return None
        return (j, d, stop, round(rr_eff, 3))

    pi = 0
    active = []
    for j in range(n - 1):
        tj = base[j]["t"]
        while pi < len(pois) and pois[pi]["t_conf"] <= tj:
            active.append(dict(pois[pi], used_A=False, used_B0=False,
                               used_B=False, armed=False, arm_bar=-1, dead_B=False))
            pi += 1
        if not active:
            continue
        kept = []
        for poi in active:
            if tj - poi["t_conf"] > max_age:
                continue
            # invalidación: el precio rompió el stop sin completar la entrada -> POI muerto
            if poi["dir"] == "long" and lows[j] < poi["stop"]:
                continue
            if poi["dir"] == "short" and highs[j] > poi["stop"]:
                continue
            kept.append(poi)
        active = kept[-80:]
        for poi in active:
            d = poi["dir"]
            tapped = (d == "long" and lows[j] <= poi["hi"] and highs[j] >= poi["lo"]) or \
                     (d == "short" and highs[j] >= poi["lo"] and lows[j] <= poi["hi"])
            # --- A: entra al toque
            if tapped and not poi["used_A"]:
                s = mk(j, poi)
                if s:
                    sigA.append(s)
                poi["used_A"] = True
            # --- B0: CDC mecánico en la MISMA vela del toque (lo de anoche)
            if tapped and not poi["used_B0"]:
                ref = last_sh[j] if d == "long" else last_sl[j]
                if ref is not None and ((d == "long" and closes[j] > ref) or
                                        (d == "short" and closes[j] < ref)):
                    s = mk(j, poi)
                    if s:
                        sigB0.append(s)
                poi["used_B0"] = True
            # --- B: arma al toque, espera el CDC en contexto
            if tapped and not poi["armed"] and not poi["used_B"] and not poi["dead_B"]:
                poi["armed"] = True
                poi["arm_bar"] = j
        # --- B: revisa POIs armados (CDC = cierre rompe el último swing relevante)
        for poi in active:
            if not poi["armed"] or poi["used_B"] or poi["dead_B"]:
                continue
            if j - poi["arm_bar"] > CDC_WINDOW:
                poi["dead_B"] = True            # ventana vencida sin CDC -> sin trade
                continue
            d = poi["dir"]
            ref = last_sh[j] if d == "long" else last_sl[j]
            if ref is None:
                continue
            if (d == "long" and closes[j] > ref) or (d == "short" and closes[j] < ref):
                s = mk(j, poi)
                if s:
                    sigB.append(s)
                poi["used_B"] = True
    return sigA, sigB0, sigB


def run_variant(base, sig, sym, tf, costs):
    comm, slip = (0.0005, 0.0002) if costs else (0.0, 0.0)
    return engine.simulate(base, list(sig), sym, tf, "cdc",
                           commission=comm, slippage=slip)


def main():
    results = {}   # (rr_mode) -> dados
    for rr_mode in ["fixed", "liquidity"]:
        per = {}    # (variant, pair, tf, costs) -> list[trade]
        spans = {}  # (pair, tf) -> (t0,t1)
        for sym in PAIRS:
            sources = {}
            for tf in POI_SOURCES:
                s = load(sym, tf)
                if s:
                    sources[tf] = s
            if not sources:
                continue
            # POIs del universo multi-TF (mismos para todas las variantes).
            pois_all = []
            for s in sources.values():
                pois_all.extend(detect_pois(s, PIV, DISP))
            pois_all.sort(key=lambda x: x["t_conf"])
            for tf in BASE_TFS:
                base = sources.get(tf) or load(sym, tf)
                if not base or len(base) < 300:
                    continue
                spans[(sym, tf)] = (base[0]["t"], base[-1]["t"])
                sigA, sigB0, sigB = build_signals(base, pois_all, rr_mode)
                for vname, sig in [("A", sigA), ("B0", sigB0), ("B", sigB)]:
                    for costs in (True, False):
                        tr = run_variant(base, sig, sym, tf, costs)
                        per[(vname, sym, tf, costs)] = tr
                print(f"[{rr_mode}] {sym} {tf}: A={len(sigA)} B0={len(sigB0)} "
                      f"B={len(sigB)} señales")
        results[rr_mode] = {"per": per, "spans": spans}

    # --- Serializa un resumen navegable -----------------------------------
    out = {"params": {"PIV": PIV, "DISP": DISP, "MAX_AGE_DAYS": MAX_AGE_DAYS,
                      "CDC_WINDOW": CDC_WINDOW, "RR_FIXED": RR_FIXED, "MIN_RR": MIN_RR,
                      "IS_FRACTION": IS_FRACTION, "WF_WINDOWS": WF_WINDOWS,
                      "PAIRS": PAIRS, "BASE_TFS": BASE_TFS, "POI_SOURCES": POI_SOURCES},
           "modes": {}}

    for rr_mode, data in results.items():
        per, spans = data["per"], data["spans"]
        mode_out = {}
        # Helper para juntar y splittear correctamente por par.
        def collect(variant, tf, costs, period, pairs=PAIRS):
            pool = []
            for sym in pairs:
                tr = per.get((variant, sym, tf, costs), [])
                if period == "all":
                    pool.extend(tr)
                    continue
                sp = spans.get((sym, tf))
                if not sp:
                    continue
                t0, t1 = sp
                cut = t0 + IS_FRACTION * (t1 - t0)
                if period == "is":
                    pool.extend(t for t in tr if t["entry_time"] <= cut)
                else:
                    pool.extend(t for t in tr if t["entry_time"] > cut)
            return pool

        # Tabla principal: por TF, por variante, IS/OOS, con/sin costos.
        tables = {}
        for tf in BASE_TFS:
            tdict = {}
            for variant in ["A", "B0", "B"]:
                vd = {}
                for costs in (True, False):
                    ck = "con_costos" if costs else "sin_costos"
                    vd[ck] = {
                        "IS": metrics(collect(variant, tf, costs, "is")),
                        "OOS": metrics(collect(variant, tf, costs, "oos")),
                        "ALL": metrics(collect(variant, tf, costs, "all")),
                    }
                tdict[variant] = vd
            tables[tf] = tdict

        # Desglose por par (solo con costos, OOS y ALL, headline rr).
        per_pair = {}
        for tf in BASE_TFS:
            pp = {}
            for sym in PAIRS:
                pp[sym] = {}
                for variant in ["A", "B0", "B"]:
                    tr_all = per.get((variant, sym, tf, True), [])
                    sp = spans.get((sym, tf))
                    if sp:
                        t0, t1 = sp
                        cut = t0 + IS_FRACTION * (t1 - t0)
                        oos = [t for t in tr_all if t["entry_time"] > cut]
                    else:
                        oos = []
                    pp[sym][variant] = {"ALL": metrics(tr_all), "OOS": metrics(oos)}
            per_pair[tf] = pp

        # Walk-forward: expectativa por ventana temporal (con costos, agregado por TF).
        wf = {}
        for tf in BASE_TFS:
            wfd = {}
            # rango temporal global del TF
            t0 = min((spans[(s, tf)][0] for s in PAIRS if (s, tf) in spans), default=0)
            t1 = max((spans[(s, tf)][1] for s in PAIRS if (s, tf) in spans), default=0)
            if t1 <= t0:
                continue
            edges = [t0 + (t1 - t0) * k / WF_WINDOWS for k in range(WF_WINDOWS + 1)]
            for variant in ["A", "B0", "B"]:
                allt = []
                for sym in PAIRS:
                    allt.extend(per.get((variant, sym, tf, True), []))
                wins = []
                for k in range(WF_WINDOWS):
                    lo, hi = edges[k], edges[k + 1]
                    seg = [t for t in allt if lo <= t["entry_time"] < hi]
                    m = metrics(seg)
                    wins.append({"n": m["trades"], "exp_R": m["expectancy_R"],
                                 "PF": m["profit_factor"], "wr": m["win_rate"]})
                wfd[variant] = wins
            wf[tf] = wfd

        mode_out["tables"] = tables
        mode_out["per_pair"] = per_pair
        mode_out["walk_forward"] = wf
        out["modes"][rr_mode] = mode_out

    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=1)
    print(f"\n→ {OUT}")


if __name__ == "__main__":
    main()
