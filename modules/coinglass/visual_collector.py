#!/usr/bin/env python3
"""Collect authorized CoinGlass chart tooltips into a research-only snapshot.

This collector uses its own persistent Chromium profile. It never reads a
personal Chrome profile and has no dependency on the trading bot.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

MAP_URL = "https://www.coinglass.com/es/pro/futures/LiquidationMap"
HEATMAP_URL = "https://www.coinglass.com/es/pro/futures/LiquidationHeatMapNew"
DEPTH_URL = "https://www.coinglass.com/es/pro/depth-delta"
LARGE_ORDERBOOK_URL = "https://www.coinglass.com/large-orderbook-statistics"
DEFAULT_PROFILE = Path.home() / ".config/nexux/coinglass-visual-profile"
COLLECTOR_VERSION = "0.2.1"
DEFAULT_COLLECTION_ATTEMPTS = 2
MONEY_RE = re.compile(r"([-+]?\$?\s*[\d.,]+)\s*([KMB])?", re.IGNORECASE)
BINANCE_PRICE_URL = "https://fapi.binance.com/fapi/v1/ticker/price?symbol=BTCUSDT"
EXCHANGE_ALIASES = {
    "270": "Binance",
    "coinbase pro": "Coinbase",
}


def _number(raw: str) -> float | None:
    text = raw.replace("$", "").replace(" ", "")
    if "," in text and "." in text:
        text = text.replace(",", "")
    elif text.count(",") == 1 and len(text.rsplit(",", 1)[-1]) <= 2:
        text = text.replace(",", ".")
    else:
        text = text.replace(",", "")
    try:
        return float(text)
    except ValueError:
        return None


def parse_money(text: str) -> float | None:
    match = MONEY_RE.search(text)
    if not match:
        return None
    value = _number(match.group(1))
    if value is None:
        return None
    multiplier = {"K": 1e3, "M": 1e6, "B": 1e9}.get(
        (match.group(2) or "").upper(), 1
    )
    return round(value * multiplier, 6)


def parse_tooltip(text: str) -> dict[str, Any]:
    """Parse Spanish/English ECharts tooltip text without fixed line order."""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    result: dict[str, Any] = {"raw": " | ".join(lines)[:600]}
    intensity_components: list[float] = []
    for line in lines:
        lowered = line.casefold()
        value = parse_money(line)
        if value is None:
            continue
        if "precio" in lowered or "price" in lowered:
            result["price"] = value
        elif "acumul" in lowered or "cumulative" in lowered:
            result["cumulative_usd"] = value
        elif "delta" in lowered:
            result["delta_usd"] = value
        elif (
            "liquida" in lowered
            or "intens" in lowered
            or "leverage" in lowered
        ):
            result["intensity_usd"] = value
    for index, label in enumerate(lines[:-1]):
        lowered = label.casefold()
        has_inline_amount = (
            ":" in label
            or "$" in label
            or re.search(r"\d[\d.,]*\s*[KMB]\b", label, re.IGNORECASE)
        )
        if has_inline_amount:
            continue
        value = parse_money(lines[index + 1])
        if value is None:
            continue
        if "precio" in lowered or "price" in lowered:
            result["price"] = value
        elif "acumul" in lowered or "cumulative" in lowered:
            result["cumulative_usd"] = value
        elif "delta" in lowered:
            result["delta_usd"] = value
        elif (
            "liquida" in lowered
            or "intens" in lowered
            or "leverage" in lowered
            or "apalancamiento" in lowered
        ):
            intensity_components.append(value)
    # `inferred` marca qué campos NO vinieron etiquetados sino de una heurística
    # de relleno. Los formatos apilados de CoinGlass no etiquetan el precio, así
    # que las heurísticas son necesarias; lo que no se puede es confundir un
    # tooltip completo con uno a medio pintar. Quien consume decide.
    inferred: list[str] = []
    if intensity_components:
        result["intensity_usd"] = sum(intensity_components)
        # Los buckets 10x/50x/100x se suman; si se renderizaron menos, la
        # intensidad sale silenciosamente baja. Se registra cuántos hubo.
        result["intensity_parts"] = len(intensity_components)
    if "price" not in result:
        for line in lines:
            value = parse_money(line)
            if value is not None and 1_000 < value < 1_000_000:
                result["price"] = value
                inferred.append("price")
                break
    if "intensity_usd" not in result:
        monetary = [
            parse_money(line) for line in lines
            if "$" in line or re.search(r"\d\s*[KMB]\b", line, re.IGNORECASE)
        ]
        monetary = [value for value in monetary if value is not None and value > 100_000]
        if monetary:
            result["intensity_usd"] = monetary[-1]
            inferred.append("intensity_usd")
    if lines:
        result["timestamp"] = lines[0]
    if inferred:
        result["inferred"] = inferred
    return result


def parse_whale_order(
    text: str,
    *,
    background_class: str,
    exchange_src: str,
) -> dict[str, Any] | None:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if len(lines) < 4:
        return None
    price = _number(lines[1])
    amount = parse_money(lines[2])
    side = (
        "bid" if "ovv2-item-bg-l" in background_class
        else "ask" if "ovv2-item-bg-s" in background_class
        else None
    )
    if price is None or price <= 0 or amount is None or amount <= 0 or side is None:
        return None
    exchange = unquote(Path(urlparse(exchange_src).path).stem) if exchange_src else "unknown"
    exchange = EXCHANGE_ALIASES.get(exchange, exchange)
    return {
        "side": side,
        "price": price,
        "amount_usd": amount,
        "duration": lines[3][:80],
        "market": lines[0][:20],
        "exchange": exchange[:80],
    }


def public_btc_price() -> float:
    request = urllib.request.Request(BINANCE_PRICE_URL, headers={"accept": "application/json"})
    with urllib.request.urlopen(request, timeout=15) as response:
        value = float(json.loads(response.read().decode("utf-8"))["price"])
    if not 1_000 < value < 1_000_000:
        raise RuntimeError("Precio publico BTC fuera de rango")
    return value


async def _largest_canvas(page):
    canvases = page.locator("canvas")
    candidates = []
    for index in range(await canvases.count()):
        canvas = canvases.nth(index)
        box = await canvas.bounding_box()
        if box and box["width"] > 500 and box["height"] > 250:
            candidates.append((index, canvas, box))
    if not candidates:
        raise RuntimeError("CoinGlass no expuso un canvas de datos")
    top_y = min(row[2]["y"] for row in candidates)
    top_group = [
        row for row in candidates
        if abs(row[2]["y"] - top_y) < 2
    ]
    _, canvas, box = max(
        top_group,
        key=lambda row: (row[2]["width"] * row[2]["height"], row[0]),
    )
    return canvas, box


async def _tooltip_text(page) -> str:
    selectors = (
        ".cg-toolti-box:visible",
        ".cg-tooltip-item:visible",
    )
    for selector in selectors:
        tooltip = page.locator(selector).last
        try:
            if selector == ".cg-tooltip-item:visible":
                tooltip = tooltip.locator("xpath=..")
            return await tooltip.inner_text(timeout=80)
        except Exception:  # noqa: BLE001
            continue
    return ""


async def _scan_vertical(page, *, x_ratio: float, samples: int = 150) -> list[dict[str, Any]]:
    canvas, box = await _largest_canvas(page)
    await canvas.scroll_into_view_if_needed()
    box = await canvas.bounding_box()
    if not box:
        raise RuntimeError("Canvas de CoinGlass sin geometria visible")
    seen: dict[tuple[int, int], dict[str, Any]] = {}
    for index in range(samples):
        y = 12 + index / max(1, samples - 1) * (box["height"] - 24)
        await page.mouse.move(
            box["x"] + box["width"] * x_ratio,
            box["y"] + y,
        )
        parsed = parse_tooltip(await _tooltip_text(page))
        price = parsed.get("price")
        intensity = parsed.get("intensity_usd")
        if price and intensity is not None:
            seen[(round(price), round(intensity))] = parsed
    return list(seen.values())


def _paso_observado(rows: list[dict[str, Any]]) -> str | None:
    """Paso temporal MEDIDO entre puntos consecutivos del barrido, como etiqueta.

    Los tooltips traen su hora; el paso real depende del zoom del gráfico, así que
    hardcodear "15m" convertía `depth_slope` en una derivada de horizonte
    desconocido. Se usa la mediana de las diferencias para ignorar huecos.
    """
    marcas = []
    for row in rows:
        raw = str(row.get("timestamp") or "").strip()
        if not raw:
            continue
        try:
            marcas.append(datetime.fromisoformat(raw))
            continue
        except ValueError:
            pass
        partes = raw.split(":")
        if len(partes) >= 2 and partes[0].strip().isdigit() and partes[1][:2].isdigit():
            marcas.append(datetime(2000, 1, 1, int(partes[0]) % 24, int(partes[1][:2])))
    if len(marcas) < 3:
        return None
    marcas.sort()
    deltas = sorted((b - a).total_seconds() for a, b in zip(marcas, marcas[1:])
                    if (b - a).total_seconds() > 0)
    if not deltas:
        return None
    paso = deltas[len(deltas) // 2]
    if paso % 3600 == 0:
        return f"{int(paso // 3600)}h"
    return f"{int(round(paso / 60))}m"


async def _probe_column(page, x_ratio: float, samples: int = 12) -> int:
    """Sondeo BARATO: ¿esta columna del canvas devuelve tooltips? Cuenta cuántos.

    Se usa para elegir la columna antes de gastar 150 hovers en ella.
    """
    canvas, box = await _largest_canvas(page)
    box = await canvas.bounding_box()
    if not box:
        return 0
    encontrados = 0
    for index in range(samples):
        y = 12 + index / max(1, samples - 1) * (box["height"] - 24)
        await page.mouse.move(box["x"] + box["width"] * x_ratio, box["y"] + y)
        parsed = parse_tooltip(await _tooltip_text(page))
        if parsed.get("price") and parsed.get("intensity_usd") is not None:
            encontrados += 1
    return encontrados


# Columnas candidatas del heatmap, de la MÁS RECIENTE a la más antigua. El eje X
# del heatmap es tiempo: hovear una columna fija muestrea un instante. Antes estaba
# clavado en 0.75, que en una vista de 24h son ~6 horas atrás (confirmado en
# produccion: captura 01:09 con tooltip de 19:45). Se elige la columna más a la
# derecha que efectivamente devuelva tooltips, porque el borde puro suele caer en
# el margen del eje y no devuelve nada.
HEATMAP_COLUMNAS = (0.985, 0.965, 0.94, 0.90, 0.85, 0.78, 0.75)


async def _scan_heatmap_reciente(page, samples: int = 150) -> tuple[list[dict[str, Any]], float]:
    """Escanea la columna MÁS RECIENTE del heatmap que devuelva datos.

    Devuelve (filas, x_ratio_usado) para que el x_ratio quede registrado en el
    snapshot: si mañana CoinGlass cambia el layout, se ve en el dato en vez de
    degradar en silencio.
    """
    elegida = HEATMAP_COLUMNAS[-1]
    for x_ratio in HEATMAP_COLUMNAS:
        if await _probe_column(page, x_ratio) >= 3:
            elegida = x_ratio
            break
    return await _scan_vertical(page, x_ratio=elegida, samples=samples), elegida


async def _scan_levels_horizontal(
    page,
    *,
    y_ratio: float = 0.55,
    samples: int = 160,
) -> list[dict[str, Any]]:
    canvas, box = await _largest_canvas(page)
    await canvas.scroll_into_view_if_needed()
    box = await canvas.bounding_box()
    if not box:
        raise RuntimeError("Canvas de CoinGlass sin geometria visible")
    seen: dict[tuple[int, int], dict[str, Any]] = {}
    for index in range(samples):
        x = 12 + index / max(1, samples - 1) * (box["width"] - 24)
        await page.mouse.move(
            box["x"] + x,
            box["y"] + box["height"] * y_ratio,
        )
        parsed = parse_tooltip(await _tooltip_text(page))
        price = parsed.get("price")
        intensity = parsed.get("intensity_usd")
        if price and intensity is not None:
            seen[(round(price), round(intensity))] = parsed
    return list(seen.values())


async def _scan_horizontal(page, *, y_ratio: float = 0.5, samples: int = 48) -> list[dict[str, Any]]:
    canvas, box = await _largest_canvas(page)
    await canvas.scroll_into_view_if_needed()
    box = await canvas.bounding_box()
    if not box:
        raise RuntimeError("Canvas de CoinGlass sin geometria visible")
    seen: dict[str, dict[str, Any]] = {}
    for index in range(samples):
        x = box["width"] * (0.45 + index / max(1, samples - 1) * 0.53)
        await page.mouse.move(
            box["x"] + x,
            box["y"] + box["height"] * y_ratio,
        )
        parsed = parse_tooltip(await _tooltip_text(page))
        if parsed.get("delta_usd") is not None and parsed.get("price"):
            seen[str(parsed.get("timestamp"))] = parsed
    return list(seen.values())


async def _open_chart(page, url: str) -> None:
    await page.goto(url, wait_until="domcontentloaded", timeout=90_000)
    await page.wait_for_selector("canvas", timeout=90_000)
    await page.wait_for_timeout(4_000)
    await _dismiss_consent(page)
    await page.wait_for_timeout(2_000)


def _assert_chart_matches_symbol(rows: list[dict[str, Any]], btc_price: float,
                                 tolerance: float = 0.25) -> None:
    """Falla cerrado si el gráfico no es el activo que decimos publicar.

    Las URLs de CoinGlass no llevan símbolo: el activo depende del estado guardado
    en el perfil de Chrome. Si alguien dejó el chart en ETH, o cambia el default,
    publicaríamos niveles de otro activo etiquetados `BTCUSDT`. La mediana de los
    niveles tiene que caer cerca del precio real de BTC; con otro activo la
    diferencia es de un orden de magnitud, no del 25%.
    """
    prices = sorted(row["price"] for row in rows if row.get("price"))
    if not prices or not btc_price:
        raise RuntimeError("sin niveles o sin precio de referencia para validar el simbolo")
    median = prices[len(prices) // 2]
    if abs(median / btc_price - 1) > tolerance:
        raise RuntimeError(
            f"el grafico no parece BTCUSDT: mediana de niveles {median:,.0f} vs "
            f"precio BTC {btc_price:,.0f}; revise el simbolo del perfil"
        )


async def _collect_whale_orders(page) -> list[dict[str, Any]]:
    # El control de "mostrar canceladas" se busca por su ETIQUETA, no por ser el
    # primer checkbox del DOM: si CoinGlass agrega otro filtro antes, desmarcar
    # `.first` apagaría el control equivocado y se publicarían canceladas con
    # active_only=True (bandera autoafirmada que el servidor cree).
    checkbox = None
    filtro_verificado = False
    for label in ("cancelad", "cancel"):
        candidate = page.locator(f"label:has-text('{label}') input[type=checkbox]").first
        try:
            if await candidate.count() > 0:
                checkbox, filtro_verificado = candidate, True
                break
        except Exception:  # noqa: BLE001 - selector no soportado por el DOM actual
            continue
    if checkbox is None:
        # Sin etiqueta identificable se cae al primer checkbox (comportamiento
        # histórico) pero se REGISTRA que la exclusión no está verificada, en vez
        # de romper la recolección o de afirmar `active_only` a ciegas. Fallar
        # duro dejaba al colector sin datos cada 5 min, que es peor.
        checkbox = page.locator("input[type=checkbox]").first
        if await page.locator("input[type=checkbox]").count() < 1:
            raise RuntimeError("CoinGlass no expuso el control de ordenes canceladas")
    if await checkbox.is_checked(timeout=1_000):
        await checkbox.uncheck(force=True)
        await page.wait_for_timeout(2_500)
    if await checkbox.is_checked(timeout=1_000):
        raise RuntimeError("No fue posible excluir ordenes ballena canceladas")
    rows = page.locator(".large-order-item")
    parsed: dict[tuple[str, int, int, str], dict[str, Any]] = {}
    for index in range(await rows.count()):
        row = rows.nth(index)
        item = parse_whale_order(
            await row.inner_text(),
            background_class=(
                await row.locator(".large-order-item-bg").first.get_attribute("class")
                or ""
            ),
            exchange_src=await row.locator("img").first.get_attribute("src") or "",
        )
        if not item:
            continue
        # `market` entra a la clave: un muro de igual precio y monto en spot y en
        # futuros son DOS órdenes, no una. Sin esto colapsaban en una sola.
        key = (
            item["side"],
            round(item["price"]),
            round(item["amount_usd"]),
            item["exchange"],
            item.get("market") or "unknown",
        )
        parsed[key] = item
    filas = list(parsed.values())
    for fila in filas:
        # Traza de CÓMO se excluyeron las canceladas: `by_label` es verificado,
        # `first_checkbox_unverified` es la heurística histórica.
        fila["cancel_filter"] = ("by_label" if filtro_verificado
                                else "first_checkbox_unverified")
    return filas


async def _dismiss_consent(page) -> None:
    """Remove Funding Choices overlay, preferring the least permissive action."""
    selectors = (
        "button.fc-cta-do-not-consent",
        "button:has-text('Do not consent')",
        "button:has-text('No consentir')",
        "button:has-text('Rechazar')",
        "button:has-text('Reject')",
        "button.fc-cta-consent",
        "button:has-text('Consentir')",
        "button:has-text('Aceptar')",
        "button:has-text('Accept')",
    )
    for selector in selectors:
        button = page.locator(selector).first
        try:
            if await button.is_visible(timeout=250):
                await button.click(timeout=2_000)
                await page.locator(".fc-dialog-overlay").wait_for(
                    state="hidden",
                    timeout=5_000,
                )
                return
        except Exception:  # noqa: BLE001
            continue


async def collect(profile: Path, *, headless: bool = True) -> dict[str, Any]:
    try:
        from playwright.async_api import async_playwright
    except ImportError as exc:
        raise RuntimeError(
            "Falta Playwright: pip install playwright && playwright install chromium"
        ) from exc

    profile.mkdir(parents=True, exist_ok=True)
    chrome_path = os.environ.get("COINGLASS_CHROME_PATH")
    async with async_playwright() as playwright:
        context = await playwright.chromium.launch_persistent_context(
            str(profile),
            headless=headless,
            executable_path=chrome_path or None,
            viewport={"width": 1600, "height": 1000},
            locale="es-CL",
        )
        page = context.pages[0] if context.pages else await context.new_page()

        await _open_chart(page, MAP_URL)
        map_rows = await _scan_levels_horizontal(page)

        await _open_chart(page, HEATMAP_URL)
        heatmap_rows, heatmap_x = await _scan_heatmap_reciente(page)

        await _open_chart(page, DEPTH_URL)
        depth_rows = await _scan_horizontal(page)

        await _open_chart(page, LARGE_ORDERBOOK_URL)
        whale_rows = await _collect_whale_orders(page)
        await context.close()

    if len(map_rows) < 4 or len(heatmap_rows) < 4 or len(whale_rows) < 4:
        raise RuntimeError(
            "Cobertura insuficiente "
            f"(map={len(map_rows)}, heatmap={len(heatmap_rows)}, "
            f"depth={len(depth_rows)}, whale={len(whale_rows)}); "
            "revise login, plan o cambios visuales"
        )
    current_price = public_btc_price()
    _assert_chart_matches_symbol(map_rows + heatmap_rows, current_price)

    return {
        "research_only": True,
        "execution_enabled": False,
        "mode": "research",
        "source": "coinglass_authorized_browser",
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "symbol": "BTCUSDT",
        "price": current_price,
        "liquidation_map": {
            "range": "visible",
            "current_price": current_price,
            "levels": [{
                "price": row["price"],
                "intensity_usd": row["intensity_usd"],
                **({"cumulative_usd": row["cumulative_usd"]}
                   if row.get("cumulative_usd") is not None else {}),
            } for row in map_rows],
        },
        "liquidation_heatmap": {
            "model": "2",
            "range": "24h",
            # Columna del canvas realmente muestreada. Queda en el dato para que un
            # cambio de layout de CoinGlass sea visible y no silencioso.
            "x_ratio": heatmap_x,
            "levels": [{
                "price": row["price"],
                "intensity_usd": row["intensity_usd"],
                "timestamp": row.get("timestamp"),
            } for row in heatmap_rows],
        },
        "depth_delta": {
            "range_pct": 1,
            # El intervalo se MIDE de las marcas de tiempo del propio tooltip; antes
            # decia "15m" a mano y el paso real depende del zoom del grafico, asi que
            # depth_slope era una derivada de horizonte desconocido.
            "interval": _paso_observado(depth_rows) or "desconocido",
            "series": [{
                "timestamp": row.get("timestamp"),
                "delta_usd": row["delta_usd"],
                "price": row["price"],
            } for row in depth_rows],
        },
        "whale_orders": {
            "active_only": True,
            "range": "visible_near_price",
            "rows": whale_rows,
        },
        "provenance": {
            "method": "tooltip_scan",
            "urls": [MAP_URL, HEATMAP_URL, DEPTH_URL, LARGE_ORDERBOOK_URL],
            "collector_version": COLLECTOR_VERSION,
        },
    }


async def collect_with_retry(
    profile: Path,
    *,
    headless: bool = True,
    attempts: int = DEFAULT_COLLECTION_ATTEMPTS,
) -> dict[str, Any]:
    """Retry a full browser session after transient Chrome/page failures."""
    last_error: Exception | None = None
    for attempt in range(1, max(1, attempts) + 1):
        try:
            return await collect(profile, headless=headless)
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            if attempt >= max(1, attempts):
                raise
            print(
                f"CoinGlass visual intento {attempt} fallo "
                f"({type(exc).__name__}: {exc}); reiniciando navegador",
                flush=True,
            )
            await asyncio.sleep(3)
    raise RuntimeError("CoinGlass visual no pudo iniciar") from last_error


async def bootstrap(profile: Path) -> None:
    """Open the dedicated profile and wait for the user to complete login."""
    try:
        from playwright.async_api import async_playwright
    except ImportError as exc:
        raise RuntimeError(
            "Falta Playwright: pip install playwright && playwright install chromium"
        ) from exc

    profile.mkdir(parents=True, exist_ok=True)
    async with async_playwright() as playwright:
        context = await playwright.chromium.launch_persistent_context(
            str(profile),
            headless=False,
            viewport={"width": 1500, "height": 940},
            locale="es-CL",
        )
        page = context.pages[0] if context.pages else await context.new_page()
        await page.goto(MAP_URL, wait_until="domcontentloaded", timeout=90_000)
        await page.wait_for_selector("canvas", timeout=90_000)
        await page.wait_for_timeout(4_000)
        await _dismiss_consent(page)
        print(
            "Ventana CoinGlass lista. Inicie sesion directamente en el navegador; "
            "el bootstrap terminara cuando CoinGlass confirme la sesion."
        )
        await page.wait_for_timeout(20 * 60 * 1000)
        await context.close()
        print("Bootstrap CoinGlass cerrado; el perfil dedicado quedo persistido.")


def archivar_local(snapshot: dict[str, Any], destino: Path) -> str | None:
    """Copia append-only del libro, en la misma máquina que captura.

    Hasta ahora el histórico vivía SOLO en la instancia remota, y de un lado que no
    se puede leer con el token (sirve para escribir, no para leer). Guardar acá una
    segunda copia resuelve el acceso sin abrir ninguna vía de lectura nueva en la
    web, y de paso el dato deja de estar en un único lugar.

    Se guarda la misma forma reducida que persiste el módulo —precio y muros— porque
    es lo que consumen los estudios; el snapshot completo ya queda en `--output`.

    Devuelve un mensaje de error si falla, None si salió bien. NUNCA levanta: un
    problema de disco no puede costar un ciclo de captura. Eso ya pasó una vez con un
    guard que fallaba cerrado y se perdió una recolección entera.
    """
    try:
        filas = snapshot.get("whale_orders", {}).get("rows") or []
        fila = {
            "captured_at": snapshot.get("captured_at"),
            "price": snapshot.get("price"),
            "bids": [[r["price"], r["amount_usd"]] for r in filas
                     if r.get("side") == "bid"],
            "asks": [[r["price"], r["amount_usd"]] for r in filas
                     if r.get("side") == "ask"],
        }
        destino.parent.mkdir(parents=True, exist_ok=True)
        with open(destino, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(fila, separators=(",", ":")) + "\n")
        return None
    except (OSError, KeyError, TypeError) as exc:
        return str(exc)


def publish(snapshot: dict[str, Any], remote_url: str, token: str) -> None:
    request = urllib.request.Request(
        remote_url.rstrip("/") + "/m/coinglass/api/visual-ingest",
        data=json.dumps(snapshot, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json", "X-Nexus-Token": token},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        if response.status != 200:
            raise RuntimeError(f"visual ingest HTTP {response.status}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", type=Path, default=DEFAULT_PROFILE)
    parser.add_argument("--remote-url", default=os.environ.get("NEXUS_REMOTE_URL", ""))
    parser.add_argument("--token", default=os.environ.get("NEXUS_INGEST_TOKEN", ""))
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--archivo-local",
        type=Path,
        default=(Path(os.environ["NEXUS_BOOK_ARCHIVE"])
                 if os.environ.get("NEXUS_BOOK_ARCHIVE") else None),
        help=("copia append-only del libro en esta máquina (JSONL). Sin esto, el "
              "histórico vive sólo en la instancia remota, que no se puede leer con "
              "el token de ingesta."),
    )
    parser.add_argument("--headed", action="store_true")
    parser.add_argument("--bootstrap", action="store_true")
    parser.add_argument("--interval", type=int, default=300)
    parser.add_argument(
        "--attempts",
        type=int,
        default=DEFAULT_COLLECTION_ATTEMPTS,
    )
    parser.add_argument("--once", action="store_true")
    return parser.parse_args()


async def run(args: argparse.Namespace) -> None:
    if args.bootstrap:
        await bootstrap(args.profile)
        return
    while True:
        snapshot = await collect_with_retry(
            args.profile,
            headless=not args.headed,
            attempts=args.attempts,
        )
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(
                json.dumps(snapshot, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            os.chmod(args.output, 0o600)
        aviso_archivo = None
        if args.archivo_local:
            aviso_archivo = archivar_local(snapshot, args.archivo_local)
        if args.remote_url:
            if not args.token:
                raise RuntimeError("NEXUS_INGEST_TOKEN requerido para publicar")
            publish(snapshot, args.remote_url, args.token)
        indicator_time = snapshot["captured_at"]
        print(
            f"CoinGlass visual {indicator_time}: "
            f"{len(snapshot['liquidation_map']['levels'])} mapa, "
            f"{len(snapshot['liquidation_heatmap']['levels'])} heatmap, "
            f"{len(snapshot['depth_delta']['series'])} delta, "
            f"{len(snapshot['whale_orders']['rows'])} whale"
            + (f" · ARCHIVO LOCAL FALLO: {aviso_archivo}" if aviso_archivo else "")
        )
        if args.once:
            return
        await asyncio.sleep(max(60, args.interval))


if __name__ == "__main__":
    asyncio.run(run(parse_args()))
