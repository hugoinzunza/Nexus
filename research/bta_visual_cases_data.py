"""Datos OHLC para casos visuales del chart BTA.

Cruza las capturas manuales del TradingView del profe con la historia local de
BTCUSDT 15m. No intenta reemplazar la lectura visual: sólo deja números base
para revisar en la mañana.
"""
from __future__ import annotations

import json
import os
import sys
import time

WT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if WT not in sys.path:
    sys.path.insert(0, WT)

from modules.trading import smc  # noqa: E402

DATA = os.path.join(WT, "data", "klines_BTCUSDT_15m.json")
FUTURES_RECENT = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                              "bta_btcusdtp_15m_recent.json")
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                   "bta_visual_cases_data.json")


CASES = [
    {
        "key": "2026-06-24_discount_poi_confirmacion",
        "center": "2026-06-24 12:00",
        "days_before": 7,
        "days_after": 7,
        "visual": "Mapa premium/discount, CDC, strong high, minimo 57.758.",
    },
    {
        "key": "2026-06-17_blue_range_premium_discount",
        "center": "2026-06-17 12:00",
        "days_before": 7,
        "days_after": 7,
        "visual": "Rango amplio azul/gris, premium POI, counter POI, discount POI.",
    },
    {
        "key": "2026-06-11_premium_discount_check",
        "center": "2026-06-11 12:00",
        "days_before": 5,
        "days_after": 7,
        "visual": "CDC, premium POI con check, desplazamiento desde discount.",
    },
    {
        "key": "2026-05-27_drop_to_orange_target",
        "center": "2026-05-27 12:00",
        "days_before": 7,
        "days_after": 7,
        "visual": "Continuacion bajista hacia caja objetivo naranja.",
    },
    {
        "key": "2026-05-15_discount_cdc_zones",
        "center": "2026-05-15 12:00",
        "days_before": 7,
        "days_after": 7,
        "visual": "Discount POI, CDC perdido, zonas celestes de retest.",
    },
    {
        "key": "2025-11-05_zigzag_structure",
        "center": "2025-11-05 01:15",
        "days_before": 5,
        "days_after": 5,
        "visual": "Zigzag morado, pivotes celestes, medicion 0/1.",
    },
]


def parse_utc(s: str) -> int:
    return int(time.mktime(time.strptime(s + " UTC", "%Y-%m-%d %H:%M %Z")) * 1000)


def iso(ts_ms: int) -> str:
    return time.strftime("%Y-%m-%d %H:%M", time.gmtime(ts_ms / 1000))


def load(path=DATA):
    with open(DATA, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    data.sort(key=lambda c: c["t"])
    return data


def load_path(path):
    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    data.sort(key=lambda c: c["t"])
    return data


def fvg_count(candles):
    bull = bear = 0
    for i in range(2, len(candles)):
        if candles[i - 2]["h"] < candles[i]["l"]:
            bull += 1
        if candles[i - 2]["l"] > candles[i]["h"]:
            bear += 1
    return {"bull": bull, "bear": bear, "total": bull + bear}


def nearest_swings(points, center_idx, candles, side, n=5):
    before = [p for p in points if p["idx"] <= center_idx]
    after = [p for p in points if p["idx"] > center_idx]
    out = []
    for p in before[-n:] + after[:n]:
        out.append({
            "side": side,
            "time": iso(candles[p["idx"]]["t"]),
            "price": round(p["price"], 2),
            "bars_from_center": p["idx"] - center_idx,
        })
    return out


def max_move_after(candles, center_idx, horizon=96):
    base = candles[center_idx]["c"]
    end = min(len(candles), center_idx + horizon + 1)
    future = candles[center_idx + 1:end]
    if not future:
        return {}
    hi = max(c["h"] for c in future)
    lo = min(c["l"] for c in future)
    return {
        "close_at_center": round(base, 2),
        "max_up_pct": round((hi - base) / base * 100, 2),
        "max_down_pct": round((lo - base) / base * 100, 2),
        "future_high": round(hi, 2),
        "future_low": round(lo, 2),
    }


def main():
    spot_candles = load_path(DATA)
    futures_candles = load_path(FUTURES_RECENT) if os.path.isfile(FUTURES_RECENT) else []
    out = {"source": DATA, "futures_recent_source": FUTURES_RECENT, "cases": []}
    for case in CASES:
        center = parse_utc(case["center"])
        candles = spot_candles
        source = "spot_cache"
        if futures_candles and futures_candles[0]["t"] <= center <= futures_candles[-1]["t"]:
            candles = futures_candles
            source = "futures_recent"
        if center < candles[0]["t"] or center > candles[-1]["t"]:
            out["cases"].append({
                **case,
                "error": "centro_fuera_de_cache_local",
                "data_span": {"from": iso(candles[0]["t"]), "to": iso(candles[-1]["t"])},
            })
            continue
        start = center - case["days_before"] * 86_400_000
        end = center + case["days_after"] * 86_400_000
        window = [c for c in candles if start <= c["t"] <= end]
        if not window:
            out["cases"].append({**case, "error": "sin velas"})
            continue
        center_idx = min(range(len(candles)), key=lambda i: abs(candles[i]["t"] - center))
        window_global_start = candles.index(window[0])
        local_center_idx = center_idx - window_global_start
        sh2, sl2 = smc.swing_points(window, 2)
        sh10, sl10 = smc.swing_points(window, 10)
        high = max(window, key=lambda c: c["h"])
        low = min(window, key=lambda c: c["l"])
        out["cases"].append({
            **case,
            "data_source_used": source,
            "window": {"from": iso(window[0]["t"]), "to": iso(window[-1]["t"]),
                       "candles": len(window)},
            "range": {
                "high": round(high["h"], 2), "high_time": iso(high["t"]),
                "low": round(low["l"], 2), "low_time": iso(low["t"]),
                "range_pct": round((high["h"] - low["l"]) / low["l"] * 100, 2),
            },
            "fvg": fvg_count(window),
            "pivots": {
                "piv2": {"highs": len(sh2), "lows": len(sl2)},
                "piv10": {"highs": len(sh10), "lows": len(sl10)},
                "near_center_piv10": (
                    nearest_swings(sh10, local_center_idx, window, "high")
                    + nearest_swings(sl10, local_center_idx, window, "low")
                ),
            },
            "move_after_24h": max_move_after(candles, center_idx, 96),
            "move_after_72h": max_move_after(candles, center_idx, 288),
        })
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=2)
    print(OUT)


if __name__ == "__main__":
    main()
