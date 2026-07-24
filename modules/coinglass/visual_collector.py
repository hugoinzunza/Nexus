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
    if intensity_components:
        result["intensity_usd"] = sum(intensity_components)
    if "price" not in result:
        for line in lines:
            value = parse_money(line)
            if value is not None and 1_000 < value < 1_000_000:
                result["price"] = value
                break
    if "intensity_usd" not in result:
        monetary = [
            parse_money(line) for line in lines
            if "$" in line or re.search(r"\d\s*[KMB]\b", line, re.IGNORECASE)
        ]
        monetary = [value for value in monetary if value is not None and value > 100_000]
        if monetary:
            result["intensity_usd"] = monetary[-1]
    if lines:
        result["timestamp"] = lines[0]
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


async def _collect_whale_orders(page) -> list[dict[str, Any]]:
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
        key = (
            item["side"],
            round(item["price"]),
            round(item["amount_usd"]),
            item["exchange"],
        )
        parsed[key] = item
    return list(parsed.values())


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
        heatmap_rows = await _scan_vertical(page, x_ratio=0.75)

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
            "levels": [{
                "price": row["price"],
                "intensity_usd": row["intensity_usd"],
                "timestamp": row.get("timestamp"),
            } for row in heatmap_rows],
        },
        "depth_delta": {
            "range_pct": 1,
            "interval": "15m",
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
                f"({type(exc).__name__}); reiniciando navegador",
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
        )
        if args.once:
            return
        await asyncio.sleep(max(60, args.interval))


if __name__ == "__main__":
    asyncio.run(run(parse_args()))
