"""Estudio histórico BTC M15 estilo BTA/SMC contra reglas Nexux.

Objetivo: recorrer la mayor historia local disponible de BTCUSDT en 15m y medir,
sin mirar el futuro, los conceptos que Hugo pidió observar del profe:

  - estructura: weak/strong highs/lows y sweeps,
  - FVGs y su fill,
  - OB/POI: formación, mitigación, invalidación,
  - CDC después del toque,
  - TP hacia la siguiente liquidez opuesta sin barrer.

Salida:
  research/bta_m15_structure_results.json
  research/bta_m15_structure_2026-06-30.md
"""
from __future__ import annotations

import json
import os
import sys
import time
from collections import defaultdict
from statistics import median

WT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if WT not in sys.path:
    sys.path.insert(0, WT)

from modules.trading import engine, smc  # noqa: E402
from modules.trading.backtest import metrics, session_of  # noqa: E402
from modules.trading.strategies import detect_pois  # noqa: E402

DATA_DIR = os.path.join(WT, "data")
OUT_JSON = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "bta_m15_structure_results.json")
OUT_MD = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                      "bta_m15_structure_2026-06-30.md")

SYMBOL = "BTCUSDT"
BASE_TF = "15m"
POI_SOURCES = ["15m", "1h", "4h", "1d"]

PIV_MICRO = 2
PIV_STRUCT = 10
DISP = 1.0
MAX_AGE_DAYS = 30
CDC_WINDOW = 16
STOP_BUF = 0.0005
RR_FIXED = 2.0
MIN_RR_LIQ = 2.0
MAX_HOLD = 96


def load(tf):
    path = os.path.join(DATA_DIR, f"klines_{SYMBOL}_{tf}.json")
    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    data.sort(key=lambda c: c["t"])
    return data


def year(ts_ms):
    return str(time.gmtime(ts_ms / 1000).tm_year)


def iso(ts_ms):
    return time.strftime("%Y-%m-%d %H:%M", time.gmtime(ts_ms / 1000))


def pct(num, den):
    return round(100.0 * num / den, 1) if den else 0.0


def add_counter(bucket, key, n=1):
    bucket[key] = bucket.get(key, 0) + n


def summarize_trades(trades):
    m = metrics(trades)
    keep = ["trades", "win_rate", "expectancy_R", "profit_factor", "total_R",
            "max_drawdown_R", "timeouts"]
    return {k: m[k] for k in keep}


def conf_prices(points, n):
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


def first_sweep(candles, point, side):
    price = point["price"]
    start = point["confirm_idx"] + 1
    if side == "high":
        for k in range(start, len(candles)):
            if candles[k]["h"] > price:
                return k
    else:
        for k in range(start, len(candles)):
            if candles[k]["l"] < price:
                return k
    return None


def structure_stats(candles, piv):
    sh, sl = smc.swing_points(candles, piv)
    by_year = defaultdict(lambda: {
        "swing_highs": 0, "swing_lows": 0,
        "weak_highs_end": 0, "weak_lows_end": 0,
        "swept_highs": 0, "swept_lows": 0,
        "median_sweep_hours_high": None, "median_sweep_hours_low": None,
    })
    high_hours = defaultdict(list)
    low_hours = defaultdict(list)
    examples = []

    for p in sh:
        y = year(candles[p["idx"]]["t"])
        add_counter(by_year[y], "swing_highs")
        k = first_sweep(candles, p, "high")
        if k is None:
            add_counter(by_year[y], "weak_highs_end")
        else:
            add_counter(by_year[y], "swept_highs")
            high_hours[y].append((candles[k]["t"] - candles[p["idx"]]["t"]) / 3_600_000)
            if len(examples) < 10:
                examples.append({"type": "swept_high", "pivot": iso(candles[p["idx"]]["t"]),
                                 "sweep": iso(candles[k]["t"]), "price": round(p["price"], 2)})
    for p in sl:
        y = year(candles[p["idx"]]["t"])
        add_counter(by_year[y], "swing_lows")
        k = first_sweep(candles, p, "low")
        if k is None:
            add_counter(by_year[y], "weak_lows_end")
        else:
            add_counter(by_year[y], "swept_lows")
            low_hours[y].append((candles[k]["t"] - candles[p["idx"]]["t"]) / 3_600_000)

    for y, vals in by_year.items():
        if high_hours[y]:
            vals["median_sweep_hours_high"] = round(median(high_hours[y]), 2)
        if low_hours[y]:
            vals["median_sweep_hours_low"] = round(median(low_hours[y]), 2)
    return {"piv": piv, "by_year": dict(sorted(by_year.items())), "examples": examples}


def fvg_stats(candles):
    out = defaultdict(lambda: {
        "bull_fvg": 0, "bear_fvg": 0, "filled": 0,
        "filled_bull": 0, "filled_bear": 0,
        "median_fill_bars": None, "fill_rate_pct": 0.0,
    })
    fill_bars = defaultdict(list)

    for i in range(2, len(candles)):
        a, c = candles[i - 2], candles[i]
        zones = []
        if a["h"] < c["l"]:
            zones.append(("bull", a["h"], c["l"]))
        if a["l"] > c["h"]:
            zones.append(("bear", c["h"], a["l"]))
        for kind, lo, hi in zones:
            y = year(candles[i]["t"])
            add_counter(out[y], f"{kind}_fvg")
            filled_at = None
            for k in range(i + 1, len(candles)):
                if candles[k]["l"] <= hi and candles[k]["h"] >= lo:
                    filled_at = k
                    break
            if filled_at is not None:
                add_counter(out[y], "filled")
                add_counter(out[y], f"filled_{kind}")
                fill_bars[y].append(filled_at - i)

    for y, vals in out.items():
        total = vals["bull_fvg"] + vals["bear_fvg"]
        vals["fill_rate_pct"] = pct(vals["filled"], total)
        if fill_bars[y]:
            vals["median_fill_bars"] = round(median(fill_bars[y]), 1)
    return dict(sorted(out.items()))


def liquidity_tp(direction, entry, idx_now, highs, lows, sh, sl):
    if direction == "long":
        cands = sorted((p for p in sh
                        if p["confirm_idx"] <= idx_now and p["price"] > entry),
                       key=lambda p: p["price"])
        for p in cands:
            after = highs[p["idx"] + 1: idx_now + 1]
            if not after or max(after) < p["price"]:
                return p["price"], "Weak High"
    else:
        cands = sorted((p for p in sl
                        if p["confirm_idx"] <= idx_now and p["price"] < entry),
                       key=lambda p: -p["price"])
        for p in cands:
            after = lows[p["idx"] + 1: idx_now + 1]
            if not after or min(after) > p["price"]:
                return p["price"], "Weak Low"
    return None, None


def build_touch_records(base, pois):
    n = len(base)
    opens = [c["o"] for c in base]
    highs = [c["h"] for c in base]
    lows = [c["l"] for c in base]
    closes = [c["c"] for c in base]
    sh, sl = smc.swing_points(base, PIV_MICRO)
    last_sh = conf_prices(sh, n)
    last_sl = conf_prices(sl, n)
    max_age = MAX_AGE_DAYS * 86_400_000

    records = []
    signals_fixed = []
    signals_liq = []
    signal_meta_fixed = []
    signal_meta_liq = []
    pi = 0
    active = []

    for j in range(n - 1):
        tj = base[j]["t"]
        while pi < len(pois) and pois[pi]["t_conf"] <= tj:
            active.append(dict(pois[pi], used=False, armed=False, arm_bar=-1,
                               cdc_ok=False, dead=False))
            pi += 1
        if not active:
            continue

        kept = []
        for poi in active:
            if poi["used"] or poi["dead"] or tj - poi["t_conf"] > max_age:
                continue
            invalid = (poi["dir"] == "long" and lows[j] < poi["stop"]) or \
                      (poi["dir"] == "short" and highs[j] > poi["stop"])
            if invalid:
                poi["dead"] = True
                records.append({"event": "invalid_before_touch", "year": year(tj),
                                "source_tf": poi["source_tf"], "dir": poi["dir"]})
                continue
            kept.append(poi)
        active = kept[-120:]

        for poi in active:
            d = poi["dir"]
            tapped = (d == "long" and lows[j] <= poi["hi"] and highs[j] >= poi["lo"]) or \
                     (d == "short" and highs[j] >= poi["lo"] and lows[j] <= poi["hi"])
            if not tapped:
                continue

            stop = poi["stop"] * (1 - STOP_BUF) if d == "long" else poi["stop"] * (1 + STOP_BUF)
            entry = opens[j + 1]
            risk = (entry - stop) if d == "long" else (stop - entry)
            tp, tp_label = liquidity_tp(d, entry, j, highs, lows, sh, sl)
            rr_liq = None
            if tp is not None and risk > 0:
                rr_liq = ((tp - entry) if d == "long" else (entry - tp)) / risk

            rec = {
                "event": "touch", "idx": j, "year": year(tj), "time": iso(tj),
                "source_tf": poi["source_tf"], "dir": d, "session": session_of(tj),
                "entry_next_open": round(entry, 2), "stop": round(stop, 2),
                "poi_lo": round(poi["lo"], 2), "poi_hi": round(poi["hi"], 2),
                "risk_pct": round(risk / entry * 100, 3) if entry and risk > 0 else None,
                "tp_liq": round(tp, 2) if tp else None, "tp_label": tp_label,
                "rr_liq": round(rr_liq, 3) if rr_liq else None,
                "cdc_same_bar": False, "cdc_within_window": False,
                "cdc_delay_bars": None,
            }

            ref = last_sh[j] if d == "long" else last_sl[j]
            if ref is not None and ((d == "long" and closes[j] > ref) or
                                    (d == "short" and closes[j] < ref)):
                rec["cdc_same_bar"] = True
                rec["cdc_within_window"] = True
                rec["cdc_delay_bars"] = 0
            else:
                end = min(n - 1, j + CDC_WINDOW)
                for k in range(j + 1, end + 1):
                    ref_k = last_sh[k] if d == "long" else last_sl[k]
                    if ref_k is None:
                        continue
                    if (d == "long" and closes[k] > ref_k) or (d == "short" and closes[k] < ref_k):
                        rec["cdc_within_window"] = True
                        rec["cdc_delay_bars"] = k - j
                        break

            poi["used"] = True
            rid = len(records)
            records.append(rec)
            signals_fixed.append((j, d, stop, RR_FIXED))
            signal_meta_fixed.append(rid)
            if rr_liq is not None and rr_liq >= MIN_RR_LIQ:
                signals_liq.append((j, d, stop, round(rr_liq, 3)))
                signal_meta_liq.append(rid)

    return records, (signals_fixed, signal_meta_fixed), (signals_liq, signal_meta_liq)


def attach_trades(base, records, signals, signal_meta, mode):
    trades = engine.simulate(base, list(signals), SYMBOL, BASE_TF, f"bta_m15_{mode}",
                             max_hold=MAX_HOLD)
    # engine.simulate skips overlapping trades; match by signal tuple order.
    sig_by_key = defaultdict(list)
    for sig, rid in zip(signals, signal_meta):
        sig_by_key[(sig[0], sig[1], round(sig[2], 6), round(sig[3], 6))].append(rid)
    for t in trades:
        # Entry is next candle open, so find the prior signal by entry_time.
        entry_idx = next((i for i, c in enumerate(base) if c["t"] == t["entry_time"]), None)
        if entry_idx is None:
            continue
        j = entry_idx - 1
        candidates = [rid for (sj, sd, _ss, _rr), ids in sig_by_key.items()
                      if sj == j and sd == t["direction"] for rid in ids]
        if not candidates:
            continue
        rid = candidates[0]
        records[rid][f"trade_{mode}"] = {
            "outcome": t["outcome"], "R": t["R"],
            "entry_time": iso(t["entry_time"]), "exit_time": iso(t["exit_time"]),
        }
    return trades


def aggregate_records(records):
    by_year = defaultdict(lambda: {
        "touches": 0, "invalid_before_touch": 0,
        "cdc_same_bar": 0, "cdc_within_window": 0,
        "liq_rr_ge_2": 0, "long": 0, "short": 0,
    })
    by_source = defaultdict(lambda: {
        "touches": 0, "invalid_before_touch": 0, "cdc_within_window": 0,
        "liq_rr_ge_2": 0,
    })
    by_session = defaultdict(lambda: {"touches": 0, "cdc_within_window": 0})

    for r in records:
        y = r["year"]
        src = r.get("source_tf", "n/a")
        if r["event"] == "invalid_before_touch":
            add_counter(by_year[y], "invalid_before_touch")
            add_counter(by_source[src], "invalid_before_touch")
            continue
        add_counter(by_year[y], "touches")
        add_counter(by_source[src], "touches")
        add_counter(by_session[r["session"]], "touches")
        add_counter(by_year[y], r["dir"])
        if r["cdc_same_bar"]:
            add_counter(by_year[y], "cdc_same_bar")
        if r["cdc_within_window"]:
            add_counter(by_year[y], "cdc_within_window")
            add_counter(by_source[src], "cdc_within_window")
            add_counter(by_session[r["session"]], "cdc_within_window")
        if r["rr_liq"] is not None and r["rr_liq"] >= MIN_RR_LIQ:
            add_counter(by_year[y], "liq_rr_ge_2")
            add_counter(by_source[src], "liq_rr_ge_2")

    return {
        "by_year": dict(sorted(by_year.items())),
        "by_source": dict(sorted(by_source.items())),
        "by_session": dict(sorted(by_session.items())),
    }


def trades_by(trades, key_fn):
    out = {}
    buckets = defaultdict(list)
    for t in trades:
        buckets[key_fn(t)].append(t)
    for key, vals in sorted(buckets.items()):
        out[str(key)] = summarize_trades(vals)
    return out


def best_examples(records):
    winners = []
    failures = []
    for r in records:
        if r["event"] != "touch":
            continue
        liq = r.get("trade_liq")
        fixed = r.get("trade_fixed")
        item = {
            "time": r["time"], "source_tf": r["source_tf"], "dir": r["dir"],
            "session": r["session"], "rr_liq": r["rr_liq"],
            "cdc_delay_bars": r["cdc_delay_bars"],
            "fixed_R": fixed["R"] if fixed else None,
            "liq_R": liq["R"] if liq else None,
            "outcome_liq": liq["outcome"] if liq else None,
        }
        if liq and liq["R"] > 0:
            winners.append(item)
        if fixed and fixed["R"] <= 0:
            failures.append(item)
    winners.sort(key=lambda x: x["liq_R"] or 0, reverse=True)
    failures.sort(key=lambda x: x["fixed_R"] if x["fixed_R"] is not None else 999)
    return {"best_liquidity_winners": winners[:8], "fixed_rr_failures": failures[:8]}


def md_table(rows, headers):
    lines = ["| " + " | ".join(headers) + " |",
             "| " + " | ".join(["---"] * len(headers)) + " |"]
    for row in rows:
        lines.append("| " + " | ".join(str(row.get(h, "")) for h in headers) + " |")
    return "\n".join(lines)


def write_report(out):
    span = out["span"]
    rows = []
    for y, s in out["poi_events"]["by_year"].items():
        fm = out["trades"]["fixed_by_year"].get(y, {})
        lm = out["trades"]["liquidity_by_year"].get(y, {})
        rows.append({
            "año": y,
            "toques": s.get("touches", 0),
            "CDC<=16": f"{pct(s.get('cdc_within_window', 0), s.get('touches', 0))}%",
            "RRliq>=2": f"{pct(s.get('liq_rr_ge_2', 0), s.get('touches', 0))}%",
            "fixed expR": fm.get("expectancy_R", 0),
            "fixed PF": fm.get("profit_factor", 0),
            "liq expR": lm.get("expectancy_R", 0),
            "liq PF": lm.get("profit_factor", 0),
        })

    fvg_rows = []
    for y, s in out["fvg"].items():
        total = s["bull_fvg"] + s["bear_fvg"]
        fvg_rows.append({"año": y, "FVGs": total, "bull": s["bull_fvg"],
                         "bear": s["bear_fvg"], "fill": f'{s["fill_rate_pct"]}%',
                         "med fill velas": s["median_fill_bars"]})

    struct_rows = []
    for y, s in out["structure"]["piv10"]["by_year"].items():
        struct_rows.append({
            "año": y,
            "SH": s["swing_highs"], "SL": s["swing_lows"],
            "weak H fin": s["weak_highs_end"], "weak L fin": s["weak_lows_end"],
            "sweep H": s["swept_highs"], "sweep L": s["swept_lows"],
            "med h sweep H": s["median_sweep_hours_high"],
            "med h sweep L": s["median_sweep_hours_low"],
        })

    source_rows = []
    for src, s in out["poi_events"]["by_source"].items():
        source_rows.append({
            "fuente": src, "toques": s.get("touches", 0),
            "invalid pre": s.get("invalid_before_touch", 0),
            "CDC<=16": f"{pct(s.get('cdc_within_window', 0), s.get('touches', 0))}%",
            "RRliq>=2": f"{pct(s.get('liq_rr_ge_2', 0), s.get('touches', 0))}%",
        })

    fx = out["trades"]["fixed_all"]
    lx = out["trades"]["liquidity_all"]
    text = f"""# Estudio BTC M15 estilo BTA/SMC vs Nexux

Fecha del estudio: 2026-06-30. Datos locales: {span["from"]} UTC a {span["to"]} UTC, {span["candles"]:,} velas de 15m.

## Lectura ejecutiva

- En M15 hay muchísima estructura operable visualmente, pero el edge mecánico no viene de “tocar cualquier OB”: aparece cuando el POI tiene salida hacia liquidez opuesta con R:R suficiente y el CDC no llega tarde.
- La variante simple de toque a POI con TP fijo 2R dio {fx["trades"]} trades, expectativa {fx["expectancy_R"]}R, PF {fx["profit_factor"]} y total {fx["total_R"]}R.
- La variante que apunta a la siguiente liquidez weak sin barrer y exige R:R >= {MIN_RR_LIQ} dio {lx["trades"]} trades, expectativa {lx["expectancy_R"]}R, PF {lx["profit_factor"]} y total {lx["total_R"]}R.
- M15 sirve mejor como microscopio de ejecución: barrido, mitigación y CDC. Para dirección y selección de POI, los resultados siguen favoreciendo que la idea venga de 1h/4h/1d y no de ruido M15 aislado.

## POI / OB por año

{md_table(rows, ["año", "toques", "CDC<=16", "RRliq>=2", "fixed expR", "fixed PF", "liq expR", "liq PF"])}

## Fuente del POI

{md_table(source_rows, ["fuente", "toques", "invalid pre", "CDC<=16", "RRliq>=2"])}

## Estructura PIV10 M15

Weak = nivel todavía no barrido al cierre de la historia. Strong = nivel que ya fue barrido después de confirmarse.

{md_table(struct_rows, ["año", "SH", "SL", "weak H fin", "weak L fin", "sweep H", "sweep L", "med h sweep H", "med h sweep L"])}

## FVG M15

{md_table(fvg_rows, ["año", "FVGs", "bull", "bear", "fill", "med fill velas"])}

## Casos destacados

Mejores trades con TP a liquidez:

```json
{json.dumps(out["examples"]["best_liquidity_winners"], ensure_ascii=False, indent=2)}
```

Fallos representativos de TP fijo:

```json
{json.dumps(out["examples"]["fixed_rr_failures"], ensure_ascii=False, indent=2)}
```

## Conclusión para Nexux

La lectura del profe tiene sentido como secuencia: liquidez tomada -> desplazamiento/FVG -> OB/POI -> mitigación -> CDC -> objetivo en weak liquidity. La parte crítica para automatizar no es detectar más dibujos, sino filtrar cuáles toques tienen liquidez cercana al otro lado, riesgo estructural acotado y confirmación CDC dentro de una ventana corta. En esta muestra, M15 por sí solo genera demasiada frecuencia; conviene tratarlo como gatillo de entrada y dejar el sesgo/POI principal en timeframes superiores.
"""
    with open(OUT_MD, "w", encoding="utf-8") as fh:
        fh.write(text)


def main():
    base = load(BASE_TF)
    sources = {tf: load(tf) for tf in POI_SOURCES}
    pois = []
    poi_formation = defaultdict(lambda: {"long": 0, "short": 0})
    for tf, candles in sources.items():
        for p in detect_pois(candles, PIV_MICRO, DISP):
            pp = dict(p)
            pp["source_tf"] = tf
            pois.append(pp)
            add_counter(poi_formation[year(pp["t_conf"])], pp["dir"])
    pois.sort(key=lambda p: p["t_conf"])

    records, fixed_pack, liq_pack = build_touch_records(base, pois)
    fixed_trades = attach_trades(base, records, fixed_pack[0], fixed_pack[1], "fixed")
    liq_trades = attach_trades(base, records, liq_pack[0], liq_pack[1], "liq")

    out = {
        "params": {
            "symbol": SYMBOL, "base_tf": BASE_TF, "poi_sources": POI_SOURCES,
            "piv_micro": PIV_MICRO, "piv_struct": PIV_STRUCT, "disp_atr": DISP,
            "cdc_window": CDC_WINDOW, "max_age_days": MAX_AGE_DAYS,
            "rr_fixed": RR_FIXED, "min_rr_liquidity": MIN_RR_LIQ,
            "max_hold": MAX_HOLD,
        },
        "span": {"from": iso(base[0]["t"]), "to": iso(base[-1]["t"]), "candles": len(base)},
        "structure": {
            "piv2": structure_stats(base, PIV_MICRO),
            "piv10": structure_stats(base, PIV_STRUCT),
        },
        "fvg": fvg_stats(base),
        "poi_formation_by_year": dict(sorted(poi_formation.items())),
        "poi_events": aggregate_records(records),
        "trades": {
            "fixed_all": summarize_trades(fixed_trades),
            "liquidity_all": summarize_trades(liq_trades),
            "fixed_by_year": trades_by(fixed_trades, lambda t: year(t["entry_time"])),
            "liquidity_by_year": trades_by(liq_trades, lambda t: year(t["entry_time"])),
            "fixed_by_session": trades_by(fixed_trades, lambda t: t["session"]),
            "liquidity_by_session": trades_by(liq_trades, lambda t: t["session"]),
        },
        "examples": best_examples(records),
    }

    with open(OUT_JSON, "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=2)
    write_report(out)
    print(f"JSON: {OUT_JSON}")
    print(f"MD:   {OUT_MD}")


if __name__ == "__main__":
    main()
