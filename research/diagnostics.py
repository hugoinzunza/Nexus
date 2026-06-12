"""Diagnóstico de robustez del filtro recomendado (VIX<25 + ADX>25):
  - walk-forward ventana por ventana (¿positivo en cada tramo o solo en uno?),
  - jackknife por par (¿depende de un único símbolo?),
  - efecto en winrate y en la cola (dependencia de pocas ganadoras grandes).
"""
from __future__ import annotations

import json
import os

from evaluate import TRADES, metrics, net_R, feat, split, win

HERE = os.path.dirname(os.path.abspath(__file__))


def rec(t):
    return (feat(t, "vix") is not None and feat(t, "vix") < 25) and ((feat(t, "adx") or 0) > 25)


def base(t):
    return True


def _pf(v):
    return "∞" if v == float("inf") else v


def main():
    with open(TRADES, "r", encoding="utf-8") as fh:
        trades = json.load(fh)
    closed = [t for t in trades if t["status"] in ("ganada", "perdida")]

    print("WALK-FORWARD por ventana (con costos) · BASE vs FILTRO recomendado")
    ts = sorted(t["t"] for t in closed)
    lo, hi = ts[0], ts[-1]
    import time
    for k in range(4):
        a = lo + (hi - lo) * (k / 4)
        b = lo + (hi - lo) * ((k + 1) / 4) + (1 if k == 3 else 0)
        wb = [t for t in closed if a <= t["t"] < b]
        wf = [t for t in wb if rec(t)]
        mb, mf = metrics(wb, True), metrics(wf, True)
        da = time.strftime("%Y-%m", time.gmtime(a / 1000))
        db = time.strftime("%Y-%m", time.gmtime(b / 1000))
        print(f"  V{k+1} {da}→{db}  BASE exp={mb['exp']:>6} n={mb['n']:>3} | "
              f"FILTRO exp={mf['exp']:>6} PF={_pf(mf['pf']):>5} win={mf['win']:>4}% n={mf['n']:>3}")

    print("\nJACKKNIFE por par (OOS, con costos): saco un par y reevalúo el filtro")
    sp = split(closed)
    oos = [t for t in closed if t["t"] >= sp]
    pairs = sorted(set(t["pair"] for t in oos))
    full = metrics([t for t in oos if rec(t)], True)
    print(f"  OOS completo: exp={full['exp']} PF={_pf(full['pf'])} n={full['n']}")
    for p in pairs:
        sub = [t for t in oos if rec(t) and t["pair"] != p]
        m = metrics(sub, True)
        print(f"   sin {p:<9} exp={m['exp']:>6} PF={_pf(m['pf']):>5} n={m['n']:>3}")

    print("\nDEPENDENCIA DE LA COLA (OOS filtrado): ¿y si quito la mejor ganadora?")
    kept = [t for t in oos if rec(t)]
    rs = sorted(((net_R(t), t) for t in kept), key=lambda x: -x[0])
    m_all = metrics(kept, True)
    for drop in (0, 1, 2, 3):
        sub = [t for (_, t) in rs[drop:]]
        m = metrics(sub, True)
        print(f"  quitando top-{drop} ganadoras: exp={m['exp']:>6} PF={_pf(m['pf']):>5} n={m['n']}")
    print(f"  (winrate filtrado OOS: {m_all['win']}% vs base ~12%; "
          f"mediana R de las top: {round(rs[0][0],1) if rs else 0}R la mayor)")


if __name__ == "__main__":
    main()
