"""Reconstrucción de trades cerrados y estadísticas del diario.

A partir del `income` de futuros de Binance (PnL realizado + comisiones +
funding) reconstruye "trades cerrados" agrupando por símbolo y cercanía temporal,
y calcula las métricas del diario: PnL neto, win rate, profit factor, mejor/peor,
racha, curva de equity y desgloses por par, sesión, día de semana y hora.

Todo en la moneda de liquidación (USDT). Es una reconstrucción razonable a partir
del income; no pretende ser idéntica a la contabilidad interna de Binance.
"""
from __future__ import annotations

import time
from typing import List

CLUSTER_GAP_MS = 2 * 3_600_000  # 2h: PnL realizado del mismo símbolo dentro de
                                # esta ventana se considera un mismo trade.

_SESSIONS = [("Asia", 0, 7), ("Londres", 7, 13), ("NY", 13, 21), ("Fuera", 21, 24)]
_WEEKDAYS = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]


def _session(ts_ms: int) -> str:
    h = time.gmtime(ts_ms / 1000).tm_hour
    for name, lo, hi in _SESSIONS:
        if lo <= h < hi:
            return name
    return "Fuera"


def _f(x) -> float:
    try:
        return float(x)
    except (TypeError, ValueError):
        return 0.0


def reconstruct_trades(income: List[dict]) -> List[dict]:
    """Agrupa el income en trades cerrados por (símbolo, cluster temporal).

    Cada trade: {symbol, open_time, close_time, realized, commission, funding,
    net, fills}. El neto = PnL realizado − comisiones − funding (estos vienen
    como income negativo, así que sumamos directamente todo)."""
    by_symbol = {}
    for r in income:
        sym = r.get("symbol") or ""
        if not sym:
            continue
        by_symbol.setdefault(sym, []).append(r)

    trades = []
    for sym, rows in by_symbol.items():
        rows.sort(key=lambda x: int(x["time"]))
        cluster = None
        last_realized_time = None
        for r in rows:
            t = int(r["time"])
            itype = r.get("incomeType", "")
            val = _f(r.get("income"))
            if itype == "REALIZED_PNL":
                if cluster is None or (last_realized_time is not None and
                                       t - last_realized_time > CLUSTER_GAP_MS):
                    if cluster:
                        trades.append(cluster)
                    cluster = {"symbol": sym, "open_time": t, "close_time": t,
                               "realized": 0.0, "commission": 0.0, "funding": 0.0, "fills": 0}
                cluster["realized"] += val
                cluster["close_time"] = t
                cluster["fills"] += 1
                last_realized_time = t
            elif cluster is not None and t <= cluster["close_time"] + CLUSTER_GAP_MS:
                # Comisión / funding cercano al cluster activo → se le imputa.
                if itype == "COMMISSION":
                    cluster["commission"] += val
                elif itype == "FUNDING_FEE":
                    cluster["funding"] += val
        if cluster:
            trades.append(cluster)

    for tr in trades:
        tr["net"] = round(tr["realized"] + tr["commission"] + tr["funding"], 6)
        tr["realized"] = round(tr["realized"], 6)
        tr["commission"] = round(tr["commission"], 6)
        tr["funding"] = round(tr["funding"], 6)
    trades.sort(key=lambda x: x["close_time"])
    return trades


def metrics(trades: List[dict]) -> dict:
    n = len(trades)
    if n == 0:
        return {"trades": 0, "net_pnl": 0.0, "win_rate": 0.0, "wins": 0, "losses": 0,
                "avg_win": 0.0, "avg_loss": 0.0, "profit_factor": 0.0,
                "best": 0.0, "worst": 0.0, "max_win_streak": 0, "max_loss_streak": 0,
                "gross_commission": 0.0, "gross_funding": 0.0}
    nets = [t["net"] for t in trades]
    wins = [x for x in nets if x > 0]
    losses = [x for x in nets if x <= 0]
    gross_win = sum(wins)
    gross_loss = abs(sum(losses))
    ws = ls = mws = mls = 0
    for x in nets:
        if x > 0:
            ws += 1; mws = max(mws, ws); ls = 0
        else:
            ls += 1; mls = max(mls, ls); ws = 0
    return {
        "trades": n,
        "net_pnl": round(sum(nets), 2),
        "wins": len(wins), "losses": len(losses),
        "win_rate": round(len(wins) / n * 100, 1),
        "avg_win": round(gross_win / len(wins), 2) if wins else 0.0,
        "avg_loss": round(sum(losses) / len(losses), 2) if losses else 0.0,
        "profit_factor": round(gross_win / gross_loss, 2) if gross_loss > 0 else float("inf"),
        "best": round(max(nets), 2), "worst": round(min(nets), 2),
        "max_win_streak": mws, "max_loss_streak": mls,
        "gross_commission": round(sum(t["commission"] for t in trades), 2),
        "gross_funding": round(sum(t["funding"] for t in trades), 2),
    }


def equity_curve(trades: List[dict]) -> List[dict]:
    eq = 0.0
    out = []
    for t in trades:
        eq += t["net"]
        out.append({"t": t["close_time"], "pnl": round(eq, 2)})
    return out


def _group(trades, keyfn):
    groups = {}
    for t in trades:
        groups.setdefault(keyfn(t), []).append(t)
    out = {}
    for g, ts in groups.items():
        nets = [x["net"] for x in ts]
        wins = [x for x in nets if x > 0]
        out[g] = {"trades": len(ts), "net_pnl": round(sum(nets), 2),
                  "win_rate": round(len(wins) / len(ts) * 100, 1)}
    return out


def breakdowns(trades: List[dict]) -> dict:
    by_hour = _group(trades, lambda t: time.gmtime(t["close_time"] / 1000).tm_hour)
    return {
        "by_pair": _group(trades, lambda t: t["symbol"]),
        "by_session": _group(trades, lambda t: _session(t["close_time"])),
        "by_weekday": _group(trades, lambda t: _WEEKDAYS[time.gmtime(t["close_time"] / 1000).tm_wday]),
        "by_hour": {str(h): by_hour.get(h, {"trades": 0, "net_pnl": 0.0, "win_rate": 0.0})
                    for h in range(24)},
    }
