"""Validate browser-derived CoinGlass snapshots and build research context."""
from __future__ import annotations

import json
import math
import os
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

    has_whale_section = "whale_orders" in snapshot
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
    if has_whale_section and len(whale_orders) < 4:
        raise VisualSnapshotError("cobertura insuficiente de ordenes ballena")

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
            # Columna del canvas realmente muestreada: se propaga para que el
            # desfase del heatmap sea auditable desde el indicador. Sin esto la
            # normalización la descartaba y el dato se perdía en el camino.
            "x_ratio": _float(heatmap_data.get("x_ratio")),
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


def _escalera(
    levels: list[dict[str, Any]],
    price: float,
    *,
    above: bool,
    peldanos: int = 5,
    tolerancia: float = 0.002,
) -> list[dict[str, Any]]:
    """Bandas de liquidez hacia un lado, de la más cercana a la más lejana.

    El mapa mostraba SOLO el clúster más cercano de cada lado, así que si el precio
    lo rompía no había forma de saber qué venía después. Esto devuelve la escalera.

    Dos decisiones que importan:

    1. **Se agrupan** los niveles contiguos dentro de `tolerancia` (0,2%) en una
       banda, sumando montos. El heatmap trae ~114 niveles y muchos son vecinos:
       listarlos sueltos seria ruido, no una escalera.
    2. **El corte es RELATIVO** (la mediana de las bandas de ese lado), no un umbral
       fijo en dólares. Medido en producción: con el corte fijo de 5M sobrevivían 7
       niveles de 114 porque el MÁXIMO de esa captura era 6,69M y la mediana 1,09M.
       Un umbral absoluto sobre un dato que cambia de escala deja la vista vacía en
       los días tranquilos y saturada en los volátiles.
    """
    lado = [row for row in levels if (row["price"] > price) == above]
    if not lado:
        return []
    lado.sort(key=lambda row: abs(row["price"] - price))

    bandas: list[dict[str, Any]] = []
    for row in lado:
        anterior = bandas[-1] if bandas else None
        if anterior and abs(row["price"] / anterior["price"] - 1) <= tolerancia:
            total = anterior["intensity_usd"] + row["intensity_usd"]
            if total > 0:      # precio promedio ponderado por monto
                anterior["price"] = round(
                    (anterior["price"] * anterior["intensity_usd"]
                     + row["price"] * row["intensity_usd"]) / total, 2)
            anterior["intensity_usd"] = round(total, 2)
            anterior["niveles"] += 1
        else:
            bandas.append({"price": row["price"],
                           "intensity_usd": row["intensity_usd"],
                           "niveles": 1})

    montos = sorted(banda["intensity_usd"] for banda in bandas)
    corte = montos[len(montos) // 2] if montos else 0
    seleccion = [banda for banda in bandas if banda["intensity_usd"] >= corte]

    salida = []
    for banda in seleccion[:peldanos]:
        nivel = {**banda,
                 "distance_pct": round((banda["price"] / price - 1) * 100, 3)}
        salida.append(_con_alcance(nivel, arriba=above))
    return salida


_TOUCH_RATES_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                 "touch_rates.json")
_TOUCH_RATES: dict[str, Any] | None = None


def _touch_rates() -> dict[str, Any]:
    global _TOUCH_RATES
    if _TOUCH_RATES is None:
        try:
            with open(_TOUCH_RATES_PATH, encoding="utf-8") as fh:
                _TOUCH_RATES = json.load(fh)
        except (OSError, ValueError):
            _TOUCH_RATES = {}
    return _TOUCH_RATES


def probabilidad_de_alcance(distancia_pct: float | None, arriba: bool) -> dict | None:
    """Tasa base HISTÓRICA de que el precio recorra `distancia_pct` en cada
    horizonte. Es lo único que se puede afirmar con estos datos sin inventar
    dirección: no dice a dónde va, dice cuán lejos suele llegar.

    Se interpola entre los buckets tabulados (`research/coinglass_touch_rates.py`)
    y se reporta el `n` para que nadie lea la cifra como si fuera una certeza.
    """
    tabla = _touch_rates()
    horizontes = tabla.get("horizontes") or {}
    if distancia_pct is None or not horizontes:
        return None
    objetivo = abs(float(distancia_pct))
    salida: dict[str, Any] = {"distancia_pct": round(objetivo, 3)}
    for etiqueta, bloque in horizontes.items():
        curva = bloque.get("p_arriba" if arriba else "p_abajo") or {}
        puntos = sorted((float(k), v) for k, v in curva.items())
        if not puntos:
            continue
        if objetivo <= puntos[0][0]:
            p = puntos[0][1]
        elif objetivo >= puntos[-1][0]:
            p = puntos[-1][1]
        else:
            p = puntos[-1][1]
            for (x0, y0), (x1, y1) in zip(puntos, puntos[1:]):
                if x0 <= objetivo <= x1:
                    peso = (objetivo - x0) / (x1 - x0) if x1 > x0 else 0.0
                    p = y0 + peso * (y1 - y0)
                    break
        salida[etiqueta] = round(100 * p, 1)
        salida["n"] = bloque.get("n")
    return salida


def _con_alcance(nivel: dict[str, Any] | None, *, arriba: bool) -> dict[str, Any] | None:
    """Agrega al nivel su tasa base de alcance. Es la cifra que responde 'qué tan
    probable es llegar hasta ahí', sin afirmar hacia dónde va el precio."""
    if not nivel:
        return nivel
    tasas = probabilidad_de_alcance(nivel.get("distance_pct"), arriba)
    return {**nivel, "alcance_historico": tasas} if tasas else nivel


def _clock_lag_seconds(levels: list[dict[str, Any]], captured_at: str) -> int | None:
    """Segundos entre el reloj del tooltip (HH:MM, sin fecha) y la captura.

    El tooltip solo trae hora del día, así que se ancla al día de la captura y
    se elige la vuelta más cercana (±12 h). Positivo = el dato va ATRASADO
    respecto de la captura. None si ningún nivel trae hora legible.
    """
    base = _iso(captured_at)
    completos: list[datetime] = []
    horas: list[tuple[int, int]] = []
    for level in levels:
        raw = str(level.get("timestamp") or "").strip()
        if not raw:
            continue
        # Producción entrega "YYYY-MM-DD HH:MM" (verificado en el VPS 2026-07-25);
        # el formato corto "HH:MM" también aparece. Cualquier otra cosa ("Precio")
        # se ignora en vez de inventar una hora.
        try:
            completos.append(datetime.fromisoformat(raw).replace(tzinfo=base.tzinfo))
            continue
        except ValueError:
            pass
        partes = raw.split(":")
        if len(partes) >= 2 and partes[0].strip().isdigit() and partes[1][:2].isdigit():
            horas.append((int(partes[0]), int(partes[1][:2])))
    if completos:
        return int((base - max(completos)).total_seconds())
    if not horas:
        return None
    hora, minuto = max(horas)
    sellado = base.replace(hour=hora % 24, minute=minuto, second=0, microsecond=0)
    lag = (base - sellado).total_seconds()
    if lag > 43_200:                     # cruzó medianoche hacia atrás
        lag -= 86_400
    elif lag < -43_200:
        lag += 86_400
    return int(lag)


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

    heatmap_lag = _clock_lag_seconds(heatmap_levels, clean["captured_at"])

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

    def dominant_whale(side: str) -> dict[str, Any] | None:
        """El muro más grande del libro, SIN el radio de ±5%.

        `nearby_whales` recorta a ±5% porque eso es lo correcto para medir presión
        cerca del precio. Pero para "cuál es la pared que importa" ese recorte
        miente: las órdenes grandes y pacientes se posan LEJOS justamente por eso.
        Medido en producción (2026-07-26): los cuatro muros mayores del libro
        estaban todos fuera del radio, y el mayor —78,7M, 43x la mediana— quedaba
        excluido por 6 dólares (−5,01% contra un corte de 5%). La brújula y el
        mapa mostraban muros menores mientras ignoraban el dominante.
        """
        candidates = [row for row in whale_orders if row["side"] == side]
        if not candidates:
            return None
        row = max(candidates, key=lambda item: item["amount_usd"])
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
            "nearest_above": _con_alcance(_nearest(
                heatmap_levels, price, above=True, minimum_usd=5_000_000), arriba=True),
            "nearest_below": _con_alcance(_nearest(
                heatmap_levels, price, above=False, minimum_usd=5_000_000), arriba=False),
            "strongest_above": _strongest(heatmap_levels, price, above=True),
            "strongest_below": _strongest(heatmap_levels, price, above=False),
            "nearest_whale_ask": whale_level("ask", strongest=False),
            "nearest_whale_bid": whale_level("bid", strongest=False),
            "strongest_whale_ask": whale_level("ask", strongest=True),
            "strongest_whale_bid": whale_level("bid", strongest=True),
            # Sin radio: la pared más grande del libro, esté donde esté.
            "dominant_whale_ask": dominant_whale("ask"),
            "dominant_whale_bid": dominant_whale("bid"),
            # La escalera completa: qué hay DESPUÉS del primer clúster. Mostrar solo
            # el más cercano dejaba ciego a lo que viene si el precio lo rompe.
            "escalera_arriba": _escalera(heatmap_levels, price, above=True),
            "escalera_abajo": _escalera(heatmap_levels, price, above=False),
        },
        "coverage": {
            "map_levels": len(map_levels),
            "heatmap_levels": len(heatmap_levels),
            "depth_points": len(depth),
            "whale_orders": len(whale_orders),
            # Desfase entre el reloj del tooltip del heatmap y la captura. El
            # heatmap es tiempo×precio y se muestrea en una columna fija del
            # canvas: si esa columna no es la vigente, el componente de mayor
            # peso del score describe el pasado. Medirlo es la única forma de
            # saberlo (auditoría 2026-07-24); no altera el puntaje.
            "heatmap_lag_seconds": heatmap_lag,
        },
        # Señal de observabilidad: el heatmap va más de media hora atrás de la
        # captura. No bloquea nada, se muestra en la UI.
        "stale_heatmap": (heatmap_lag is not None and heatmap_lag > 1_800),
        "warning": (
            "Contexto experimental: localiza liquidez, muros ballena y "
            "desequilibrios; no predice por sí solo la dirección ni habilita órdenes."
        ),
    }
