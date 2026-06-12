"""Evaluador de filtros complementarios sobre las entradas SMC POI multi-TF.

Carga research/trades_features.json (generado por collect_trades.py) y mide, para
cada filtro candidato, su DELTA honesto sobre la estrategia base:
  - in-sample (70% antiguo) vs out-of-sample (30% reciente), por separado,
  - CON y SIN costos (comisión 0.05%/lado + slippage 0.02%, en R vía risk_frac),
  - #trades, winrate, expectativa R, profit factor, walk-forward (3 ventanas),
  - cuánto se descarta y qué le pasa a lo descartado.

Umbral de robustez (innegociable): OOS expectativa_neta>0, PF_neto≥1.1, ≥30 trades
OOS, walk-forward neto>0, y MEJORA de expectativa OOS sobre la base. Nada se elige
por el in-sample.

Uso:  python3 research/evaluate.py
"""
from __future__ import annotations

import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
TRADES = os.path.join(HERE, "trades_features.json")

COMM = 0.0005
SLIP = 0.0002
COST_FRAC = 2 * (COMM + SLIP)   # round-trip: comisión y slippage entrada+salida
IS_FRAC = 0.70
MIN_OOS_TRADES = 30
MIN_PF = 1.1


def cost_R(tr):
    rf = tr.get("risk_frac") or 0.0
    if rf <= 0:
        return 0.0
    return COST_FRAC / rf


def net_R(tr):
    return tr["r_gross"] - cost_R(tr)


def metrics(trades, costs=True):
    closed = [t for t in trades if t["status"] in ("ganada", "perdida")]
    n = len(closed)
    if n == 0:
        return {"n": 0, "win": 0.0, "exp": 0.0, "pf": 0.0, "totalR": 0.0,
                "avg_cost_R": 0.0, "wins": 0}
    rs = [(net_R(t) if costs else t["r_gross"]) for t in closed]
    wins = [r for r in rs if r > 0]
    losses = [r for r in rs if r <= 0]
    gw = sum(wins)
    gl = abs(sum(losses))
    return {
        "n": n, "wins": len(wins),
        "win": round(len(wins) / n * 100, 1),
        "exp": round(sum(rs) / n, 3),
        "pf": round(gw / gl, 2) if gl > 0 else float("inf"),
        "totalR": round(sum(rs), 1),
        "avg_cost_R": round(sum(cost_R(t) for t in closed) / n, 3),
    }


def split(trades):
    ts = sorted(t["t"] for t in trades)
    if not ts:
        return 0
    return ts[0] + IS_FRAC * (ts[-1] - ts[0])


def windows(trades, n=3):
    ts = sorted(t["t"] for t in trades)
    if not ts:
        return []
    lo, hi = ts[0], ts[-1]
    qs = [lo + (hi - lo) * f for f in (0, 0.25, 0.5, 0.75, 1.0001)]
    return [(qs[i], qs[i + 1]) for i in range(4)]


def win(trades, lo, hi):
    return [t for t in trades if lo <= t["t"] < hi]


def evaluate(trades, pred, costs=True):
    """Devuelve dict con IS/OOS/full/WF para el subconjunto que pasa `pred`."""
    kept = [t for t in trades if pred(t)]
    sp = split(trades)   # split global (mismo corte temporal para todos)
    is_m = metrics(win(kept, 0, sp), costs)
    oos_m = metrics(win(kept, sp, 1e18), costs)
    full_m = metrics(kept, costs)
    wf = []
    for lo, hi in windows(trades):
        wf.extend(win(kept, lo, hi))
    wf_m = metrics(wf, costs)
    return {"is": is_m, "oos": oos_m, "full": full_m, "wf": wf_m,
            "kept": len([t for t in kept if t["status"] in ("ganada", "perdida")])}


# --- Filtros candidatos -------------------------------------------------
def F(name, family, pred):
    return {"name": name, "family": family, "pred": pred}


def feat(t, k):
    return t["feat"].get(k)


def long(t):
    return t["dir"] == "long"


CANDIDATES = [
    # Tendencia por cruces de EMA (a favor de la dirección del trade).
    F("EMA 9/21 a favor", "EMA", lambda t: feat(t, "ema_9_21") == 1),
    F("EMA 20/50 a favor", "EMA", lambda t: feat(t, "ema_20_50") == 1),
    F("EMA 50/200 a favor", "EMA", lambda t: feat(t, "ema_50_200") == 1),
    F("EMA 53/200 a favor (Hugo)", "EMA", lambda t: feat(t, "ema_53_200") == 1),
    F("EMA 9/21 EN CONTRA", "EMA", lambda t: feat(t, "ema_9_21") == -1),
    F("EMA 50/200 EN CONTRA", "EMA", lambda t: feat(t, "ema_50_200") == -1),
    F("Precio sobre EMA200 a favor", "EMA", lambda t: feat(t, "price_vs_ema200") == 1),
    F("Precio sobre EMA50 a favor", "EMA", lambda t: feat(t, "price_vs_ema50") == 1),
    F("Pendiente EMA200 a favor", "EMA", lambda t: feat(t, "ema200_slope_dir") == 1),
    # RSI
    F("RSI no extremo (long<70/short>30)", "RSI",
      lambda t: (feat(t, "rsi") is not None) and (feat(t, "rsi") < 70 if long(t) else feat(t, "rsi") > 30)),
    F("RSI a favor del valor (long<45/short>55)", "RSI",
      lambda t: (feat(t, "rsi") is not None) and (feat(t, "rsi") < 45 if long(t) else feat(t, "rsi") > 55)),
    F("RSI momentum (long>50/short<50)", "RSI",
      lambda t: (feat(t, "rsi") is not None) and (feat(t, "rsi") > 50 if long(t) else feat(t, "rsi") < 50)),
    # ADX
    F("ADX>20 (con tendencia)", "ADX", lambda t: (feat(t, "adx") or 0) > 20),
    F("ADX>25 (tendencia fuerte)", "ADX", lambda t: (feat(t, "adx") or 0) > 25),
    F("ADX<20 (en rango)", "ADX", lambda t: feat(t, "adx") is not None and feat(t, "adx") < 20),
    # Volumen
    F("Volumen > media", "Volumen", lambda t: (feat(t, "vol_ratio") or 0) > 1.0),
    F("Volumen > 1.5x media", "Volumen", lambda t: (feat(t, "vol_ratio") or 0) > 1.5),
    # Sesión
    F("Solo NY", "Sesión", lambda t: t["session"] == "NY"),
    F("Excluir Londres", "Sesión", lambda t: t["session"] != "Londres"),
    F("NY o Asia (excl. Londres y Fuera)", "Sesión", lambda t: t["session"] in ("NY", "Asia")),
    # Macro: VIX
    F("VIX < 20 (calma)", "Macro-VIX", lambda t: feat(t, "vix") is not None and feat(t, "vix") < 20),
    F("VIX < 25", "Macro-VIX", lambda t: feat(t, "vix") is not None and feat(t, "vix") < 25),
    F("VIX > 25 (estrés)", "Macro-VIX", lambda t: feat(t, "vix") is not None and feat(t, "vix") > 25),
    # Macro: correlación BTC-SPX
    F("Corr BTC-SPX < 0.3 (desacople)", "Macro-Corr",
      lambda t: feat(t, "btc_spx_corr30") is not None and feat(t, "btc_spx_corr30") < 0.3),
    F("Corr BTC-SPX > 0.5 (acople risk-on)", "Macro-Corr",
      lambda t: feat(t, "btc_spx_corr30") is not None and feat(t, "btc_spx_corr30") > 0.5),
    # Macro: régimen BTC
    F("BTC sobre su MA200d (risk-on)", "Macro-BTC", lambda t: feat(t, "btc_above_ma200") == 1),
    F("BTC bajo su MA200d (risk-off)", "Macro-BTC", lambda t: feat(t, "btc_above_ma200") == 0),
]


def _pf(v):
    return "∞" if v == float("inf") else v


def row(m):
    return f"n={m['n']:<4} win={m['win']:>4}%  exp={m['exp']:>6}R  PF={_pf(m['pf']):>5}"


def main():
    with open(TRADES, "r", encoding="utf-8") as fh:
        trades = json.load(fh)
    closed = [t for t in trades if t["status"] in ("ganada", "perdida")]
    anul = sum(1 for t in trades if t["status"] == "anulada")
    print(f"Registros: {len(trades)} · cerrados: {len(closed)} · anuladas: {anul} · "
          f"abiertos: {len(trades)-len(closed)-anul}")

    # Distribución de costo en R (clave: setups con stop muy ajustado se vuelven incosteables).
    crs = sorted(cost_R(t) for t in closed)
    if crs:
        print(f"Costo por trade (R): mediana {round(crs[len(crs)//2],3)} · "
              f"p25 {round(crs[len(crs)//4],3)} · p75 {round(crs[3*len(crs)//4],3)} · "
              f"max {round(crs[-1],3)}")

    base_all = lambda t: True   # noqa: E731
    print("\n" + "=" * 78)
    print("BASE (todas las entradas POI multi-TF, 7 pares, 1h+4h)")
    print("=" * 78)
    for label, costs in [("SIN costos", False), ("CON costos", True)]:
        b = evaluate(closed, base_all, costs)
        print(f"  {label}:")
        print(f"    IS : {row(b['is'])}")
        print(f"    OOS: {row(b['oos'])}")
        print(f"    WF : {row(b['wf'])}   full: {row(b['full'])}")

    # Base OOS con costos = referencia para el delta.
    base_oos = evaluate(closed, base_all, True)["oos"]
    base_exp = base_oos["exp"]

    print("\n" + "=" * 78)
    print(f"FILTROS · DELTA de expectativa OOS (neto) sobre base ({base_exp}R)")
    print("=" * 78)
    print(f"  {'filtro':<38}{'OOSn':>5}{'win':>6}{'expN':>7}{'PFN':>6}{'Δexp':>7}{'WFexp':>7}  rob")
    results = []
    for c in CANDIDATES:
        e_net = evaluate(closed, c["pred"], True)
        e_gross = evaluate(closed, c["pred"], False)
        oos = e_net["oos"]
        wf = e_net["wf"]
        delta = round(oos["exp"] - base_exp, 3)
        robust = (oos["n"] >= MIN_OOS_TRADES and oos["exp"] > 0
                  and (oos["pf"] if oos["pf"] != float("inf") else 99) >= MIN_PF
                  and wf["exp"] > 0 and delta > 0)
        results.append({"c": c, "net": e_net, "gross": e_gross, "delta": delta, "robust": robust})
        flag = "✅" if robust else ("·" if oos["n"] >= MIN_OOS_TRADES else "⚠pocos")
        print(f"  {c['name'][:37]:<38}{oos['n']:>5}{oos['win']:>6}{oos['exp']:>7}"
              f"{_pf(oos['pf']):>6}{delta:>7}{wf['exp']:>7}  {flag}")

    # Guardar JSON para el informe.
    out = {
        "costs": {"commission_per_side": COMM, "slippage": SLIP, "cost_frac_roundtrip": COST_FRAC},
        "n_closed": len(closed), "n_anuladas": anul,
        "base": {"oos": base_oos, "is": evaluate(closed, base_all, True)["is"],
                 "oos_gross": evaluate(closed, base_all, False)["oos"]},
        "filters": [{
            "name": r["c"]["name"], "family": r["c"]["family"],
            "oos_net": r["net"]["oos"], "is_net": r["net"]["is"],
            "oos_gross": r["gross"]["oos"], "wf_net": r["net"]["wf"],
            "full_net": r["net"]["full"], "delta_oos_exp": r["delta"], "robust": r["robust"],
        } for r in results],
    }
    with open(os.path.join(HERE, "filter_results.json"), "w", encoding="utf-8") as fh:
        json.dump(_safe(out), fh, ensure_ascii=False, indent=1)
    print("\n→ research/filter_results.json")
    return results


def _safe(o):
    import math
    if isinstance(o, float):
        return None if (math.isinf(o) or math.isnan(o)) else o
    if isinstance(o, dict):
        return {k: _safe(v) for k, v in o.items()}
    if isinstance(o, list):
        return [_safe(v) for v in o]
    return o


if __name__ == "__main__":
    main()
