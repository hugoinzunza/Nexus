"""Validate browser-derived CoinGlass snapshots and build research context."""
from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any

MAX_LEVELS = 400
MAX_DEPTH_POINTS = 500
MAX_WHALE_ORDERS = 500
MAX_SNAPSHOT_AGE_SECONDS = 30 * 60


class VisualSnapshotError(ValueError):
    """Raised when a visual snapshot is unsafe or malformed."""


def _float(value: Any) -> float | None:
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (TypeError, ValueError):
        return None


def _iso(value: Any) -> datetime:
    if not isinstance(value, str):
        raise VisualSnapshotError("captured_at requerido")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise VisualSnapshotError("captured_at invalido") from exc
    if parsed.tzinfo is None:
        raise VisualSnapshotError("captured_at debe incluir zona horaria")
    return parsed.astimezone(timezone.utc)


def _levels(rows: Any, *, amount_key: str) -> list[dict[str, Any]]:
    if not isinstance(rows, list) or len(rows) > MAX_LEVELS:
        raise VisualSnapshotError("niveles visuales invalidos")
    clean = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        price = _float(row.get("price"))
        amount = _float(row.get(amount_key))
        if price is None or price <= 0 or amount is None or amount < 0:
            continue
        normalized = {
            "price": round(price, 2),
            amount_key: round(amount, 2),
        }
        cumulative = _float(row.get("cumulative_usd"))
        if cumulative is not None and cumulative >= 0:
            normalized["cumulative_usd"] = round(cumulative, 2)
        timestamp = row.get("timestamp")
        if timestamp is not None:
            normalized["timestamp"] = timestamp
        clean.append(normalized)
    return clean


def normalize_visual_snapshot(
    snapshot: dict[str, Any],
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    if not isinstance(snapshot, dict):
        raise VisualSnapshotError("snapshot visual invalido")
    if snapshot.get("research_only") is not True:
        raise VisualSnapshotError("research_only debe ser true")
    if snapshot.get("execution_enabled") is not False:
        raise VisualSnapshotError("execution_enabled debe ser false")
    if snapshot.get("mode") != "research":
        raise VisualSnapshotError("mode debe ser research")
    if snapshot.get("source") != "coinglass_authorized_browser":
        raise VisualSnapshotError("fuente visual no reconocida")
    if snapshot.get("symbol") not in {"BTCUSDT", "BTCUSDT.P"}:
        raise VisualSnapshotError("solo BTCUSDT esta habilitado")

    captured = _iso(snapshot.get("captured_at"))
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    age = (now - captured).total_seconds()
    if age < -120 or age > MAX_SNAPSHOT_AGE_SECONDS:
        raise VisualSnapshotError("snapshot visual fuera de ventana temporal")

    map_data = snapshot.get("liquidation_map") or {}
    heatmap_data = snapshot.get("liquidation_heatmap") or {}
    depth_data = snapshot.get("depth_delta") or {}
    price = _float(map_data.get("current_price") or snapshot.get("price"))
    if price is None or price <= 0:
        raise VisualSnapshotError("precio actual invalido")
    map_levels = _levels(map_data.get("levels"), amount_key="intensity_usd")
    heatmap_levels = _levels(heatmap_data.get("levels"), amount_key="intensity_usd")

    raw_depth = depth_data.get("series", [])
    if not isinstance(raw_depth, list) or len(raw_depth) > MAX_DEPTH_POINTS:
        raise VisualSnapshotError("serie depth delta invalida")
    depth_series = []
    for row in raw_depth:
        if not isinstance(row, dict):
            continue
        delta = _float(row.get("delta_usd"))
        point_price = _float(row.get("price"))
        timestamp = row.get("timestamp")
        if delta is None or point_price is None or point_price <= 0 or timestamp is None:
            continue
        depth_series.append({
            "timestamp": timestamp,
            "delta_usd": round(delta, 2),
            "price": round(point_price, 2),
        })

    whale_data = snapshot.get("whale_orders") or {
        "active_only": True,
        "rows": [],
    }
    if whale_data.get("active_only") is not True:
        raise VisualSnapshotError("solo se aceptan ordenes ballena activas")
    raw_whales = whale_data.get("rows", [])
    if not isinstance(raw_whales, list) or len(raw_whales) > MAX_WHALE_ORDERS:
        raise VisualSnapshotError("ordenes ballena invalidas")
    whale_orders = []
    for row in raw_whales:
        if not isinstance(row, dict) or row.get("side") not in {"bid", "ask"}:
            continue
        order_price = _float(row.get("price"))
        amount = _float(row.get("amount_usd"))
        if order_price is None or order_price <= 0 or amount is None or amount <= 0:
            continue
        whale_orders.append({
            "side": row["side"],
            "price": round(order_price, 2),
            "amount_usd": round(amount, 2),
            "duration": str(row.get("duration") or "unknown")[:80],
            "market": str(row.get("market") or "unknown")[:20],
            "exchange": str(row.get("exchange") or "unknown")[:80],
        })

    if len(map_levels) < 4 or len(heatmap_levels) < 4:
        raise VisualSnapshotError("cobertura insuficiente del mapa visual")

    provenance = snapshot.get("provenance") or {}
    urls = provenance.get("urls") if isinstance(provenance, dict) else None
    if not isinstance(urls, list) or not urls:
        raise VisualSnapshotError("provenance.urls requerido")

    return {
        "research_only": True,
        "execution_enabled": False,
        "mode": "research",
        "source": "coinglass_authorized_browser",
        "captured_at": captured.isoformat(),
        "symbol": "BTCUSDT",
        "price": round(price, 2),
        "liquidation_map": {
            "range": str(map_data.get("range") or "unknown"),
            "levels": map_levels,
        },
        "liquidation_heatmap": {
            "model": str(heatmap_data.get("model") or "unknown"),
            "range": str(heatmap_data.get("range") or "unknown"),
            "levels": heatmap_levels,
        },
        "depth_delta": {
            "range_pct": _float(depth_data.get("range_pct")),
            "interval": str(depth_data.get("interval") or "unknown"),
            "series": depth_series,
        },
        "whale_orders": {
            "active_only": True,
            "range": str(whale_data.get("range") or "unknown"),
            "rows": whale_orders,
        },
        "provenance": {
            "method": "tooltip_scan",
            "urls": [str(url)[:500] for url in urls[:8]],
            "collector_version": str(provenance.get("collector_version") or "unknown")[:80],
        },
    }


def _weighted_side(
    levels: list[dict[str, Any]],
    price: float,
    *,
    amount_key: str,
    above: bool,
    radius_pct: float = 5.0,
) -> float:
    total = 0.0
    for row in levels:
        is_above = row["price"] > price
        distance = abs(row["price"] / price - 1) * 100
        if is_above != above or distance > radius_pct:
            continue
        amount_m = row[amount_key] / 1_000_000
        total += math.log1p(amount_m) / max(distance, 0.15)
    return total


def _asymmetry(above: float, below: float) -> float | None:
    total = above + below
    return (above - below) / total if total > 0 else None


def _nearest(
    levels: list[dict[str, Any]],
    price: float,
    *,
    above: bool,
    minimum_usd: float,
) -> dict[str, Any] | None:
    candidates = [
        row for row in levels
        if (row["price"] > price) == above and row["intensity_usd"] >= minimum_usd
    ]
    if not candidates:
        return None
    row = min(candidates, key=lambda item: abs(item["price"] - price))
    return {
        **row,
        "distance_pct": round((row["price"] / price - 1) * 100, 3),
    }


def _strongest(
    levels: list[dict[str, Any]],
    price: float,
    *,
    above: bool,
    radius_pct: float = 5.0,
) -> dict[str, Any] | None:
    candidates = [
        row for row in levels
        if (row["price"] > price) == above
        and abs(row["price"] / price - 1) * 100 <= radius_pct
    ]
    if not candidates:
        return None
    row = max(candidates, key=lambda item: item["intensity_usd"])
    return {
        **row,
        "distance_pct": round((row["price"] / price - 1) * 100, 3),
    }


def build_visual_indicator(
    snapshot: dict[str, Any],
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    clean = normalize_visual_snapshot(snapshot, now=now)
    price = clean["price"]
    map_levels = clean["liquidation_map"]["levels"]
    heatmap_levels = clean["liquidation_heatmap"]["levels"]
    whale_orders = clean["whale_orders"]["rows"]

    map_up = _weighted_side(map_levels, price, amount_key="intensity_usd", above=True)
    map_down = _weighted_side(map_levels, price, amount_key="intensity_usd", above=False)
    heat_up = _weighted_side(heatmap_levels, price, amount_key="intensity_usd", above=True)
    heat_down = _weighted_side(heatmap_levels, price, amount_key="intensity_usd", above=False)
    map_asymmetry = _asymmetry(map_up, map_down)
    heatmap_asymmetry = _asymmetry(heat_up, heat_down)

    depth = clean["depth_delta"]["series"]
    latest_delta = depth[-1]["delta_usd"] if depth else None
    previous_delta = depth[-4]["delta_usd"] if len(depth) >= 4 else (
        depth[0]["delta_usd"] if len(depth) >= 2 else None
    )
    depth_component = (
        math.tanh(latest_delta / 20_000_000) if latest_delta is not None else None
    )
    depth_slope = (
        latest_delta - previous_delta
        if latest_delta is not None and previous_delta is not None else None
    )
    nearby_whales = [
        row for row in whale_orders
        if abs(row["price"] / price - 1) * 100 <= 5
    ]
    whale_bids = sum(
        row["amount_usd"] for row in nearby_whales if row["side"] == "bid"
    )
    whale_asks = sum(
        row["amount_usd"] for row in nearby_whales if row["side"] == "ask"
    )
    whale_pressure = _asymmetry(whale_bids, whale_asks)

    def whale_level(side: str, *, strongest: bool) -> dict[str, Any] | None:
        candidates = [row for row in nearby_whales if row["side"] == side]
        if not candidates:
            return None
        row = (
            max(candidates, key=lambda item: item["amount_usd"])
            if strongest
            else min(candidates, key=lambda item: abs(item["price"] - price))
        )
        return {
            **row,
            "distance_pct": round((row["price"] / price - 1) * 100, 3),
        }

    components = [
        (heatmap_asymmetry, 0.50),
        (map_asymmetry, 0.30),
        (depth_component, 0.20),
    ]
    available_weight = sum(weight for value, weight in components if value is not None)
    score = (
        sum(value * weight for value, weight in components if value is not None)
        / available_weight * 100
        if available_weight else None
    )
    score = round(max(-100, min(100, score)), 1) if score is not None else None
    age = (
        ((now or datetime.now(timezone.utc)).astimezone(timezone.utc)
         - _iso(clean["captured_at"])).total_seconds()
    )
    return {
        "research_only": True,
        "execution_enabled": False,
        "validated": False,
        "name": "CoinGlass Visual Context v1",
        "captured_at": clean["captured_at"],
        "age_seconds": round(age),
        "price": price,
        "score": score,
        "label": (
            "sin cobertura" if score is None
            else "atracción superior" if score >= 18
            else "atracción inferior" if score <= -18
            else "liquidez equilibrada"
        ),
        "components": {
            "heatmap_attraction": round(heatmap_asymmetry, 4)
            if heatmap_asymmetry is not None else None,
            "map_attraction": round(map_asymmetry, 4)
            if map_asymmetry is not None else None,
            "depth_delta": round(depth_component, 4)
            if depth_component is not None else None,
            "whale_bid_pressure": round(whale_pressure, 4)
            if whale_pressure is not None else None,
        },
        "depth": {
            "latest_delta_usd": latest_delta,
            "slope_usd": depth_slope,
            "decelerating": (
                latest_delta > 0 and depth_slope < 0
                if latest_delta is not None and depth_slope is not None else None
            ),
        },
        "levels": {
            "nearest_above": _nearest(
                heatmap_levels, price, above=True, minimum_usd=5_000_000
            ),
            "nearest_below": _nearest(
                heatmap_levels, price, above=False, minimum_usd=5_000_000
            ),
            "strongest_above": _strongest(heatmap_levels, price, above=True),
            "strongest_below": _strongest(heatmap_levels, price, above=False),
            "nearest_whale_ask": whale_level("ask", strongest=False),
            "nearest_whale_bid": whale_level("bid", strongest=False),
            "strongest_whale_ask": whale_level("ask", strongest=True),
            "strongest_whale_bid": whale_level("bid", strongest=True),
        },
        "coverage": {
            "map_levels": len(map_levels),
            "heatmap_levels": len(heatmap_levels),
            "depth_points": len(depth),
            "whale_orders": len(whale_orders),
        },
        "warning": (
            "Contexto experimental: localiza liquidez, muros ballena y "
            "desequilibrios; no predice por sí solo la dirección ni habilita órdenes."
        ),
    }
