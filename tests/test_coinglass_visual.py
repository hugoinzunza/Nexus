import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from core.module_base import ModuleContext
from modules.coinglass.visual import (
    VisualSnapshotError,
    build_visual_indicator,
    normalize_visual_snapshot,
)
from modules.coinglass.visual_collector import (
    parse_money,
    parse_tooltip,
    parse_whale_order,
)
from modules.coinglass.shadow import replay_shadow, shadow_plan

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 7, 24, 18, 0, tzinfo=timezone.utc)


def snapshot():
    return {
        "research_only": True,
        "execution_enabled": False,
        "mode": "research",
        "source": "coinglass_authorized_browser",
        "captured_at": NOW.isoformat(),
        "symbol": "BTCUSDT",
        "price": 64_238,
        "liquidation_map": {
            "range": "visible",
            "current_price": 64_238,
            "levels": [
                {"price": 65_691, "intensity_usd": 33_720_000, "cumulative_usd": 345_610_000},
                {"price": 65_601, "intensity_usd": 32_570_000, "cumulative_usd": 281_160_000},
                {"price": 64_791, "intensity_usd": 28_990_000, "cumulative_usd": 118_570_000},
                {"price": 64_746, "intensity_usd": 25_710_000, "cumulative_usd": 89_580_000},
                {"price": 63_666, "intensity_usd": 30_200_000, "cumulative_usd": 47_850_000},
                {"price": 63_486, "intensity_usd": 29_520_000, "cumulative_usd": 119_360_000},
                {"price": 63_531, "intensity_usd": 28_070_000, "cumulative_usd": 89_840_000},
                {"price": 62_856, "intensity_usd": 18_720_000, "cumulative_usd": 221_630_000},
            ],
        },
        "liquidation_heatmap": {
            "model": "2",
            "range": "24h",
            "levels": [
                {"price": 64_482.8, "intensity_usd": 8_850_000, "timestamp": "14:50"},
                {"price": 64_703.8, "intensity_usd": 13_360_000, "timestamp": "14:50"},
                {"price": 64_924.8, "intensity_usd": 13_850_000, "timestamp": "14:50"},
                {"price": 66_029.8, "intensity_usd": 15_510_000, "timestamp": "14:50"},
                {"price": 63_598.8, "intensity_usd": 15_970_000, "timestamp": "14:50"},
                {"price": 63_377.8, "intensity_usd": 20_380_000, "timestamp": "14:50"},
                {"price": 63_156.8, "intensity_usd": 12_730_000, "timestamp": "14:50"},
                {"price": 62_935.8, "intensity_usd": 9_900_000, "timestamp": "14:50"},
            ],
        },
        "depth_delta": {
            "range_pct": 1,
            "interval": "15m",
            "series": [
                {"timestamp": "11:30", "delta_usd": 25_840_000, "price": 65_100},
                {"timestamp": "12:30", "delta_usd": 20_370_000, "price": 64_900},
                {"timestamp": "13:30", "delta_usd": 13_850_000, "price": 64_500},
                {"timestamp": "14:30", "delta_usd": 12_470_000, "price": 64_238},
            ],
        },
        "whale_orders": {
            "active_only": True,
            "range": "visible_near_price",
            "rows": [
                {
                    "side": "ask",
                    "price": 64_750,
                    "amount_usd": 1_630_000,
                    "duration": "4H 15m",
                    "market": "S",
                    "exchange": "binance",
                },
                {
                    "side": "bid",
                    "price": 63_750,
                    "amount_usd": 1_800_000,
                    "duration": "4H 31m",
                    "market": "S",
                    "exchange": "coinbase pro",
                },
                {
                    "side": "bid",
                    "price": 61_300,
                    "amount_usd": 78_600_000,
                    "duration": "1D 3H",
                    "market": "S",
                    "exchange": "binance",
                },
                {
                    "side": "ask",
                    "price": 65_500,
                    "amount_usd": 1_290_000,
                    "duration": "3m 10s",
                    "market": "S",
                    "exchange": "binance",
                },
            ],
        },
        "provenance": {
            "method": "tooltip_scan",
            "urls": [
                "https://www.coinglass.com/es/pro/futures/LiquidationMap",
                "https://www.coinglass.com/es/pro/futures/LiquidationHeatMapNew",
            ],
            "collector_version": "test",
        },
    }


def test_visual_snapshot_is_normalized_and_never_enables_execution():
    clean = normalize_visual_snapshot(snapshot(), now=NOW)

    assert clean["research_only"] is True
    assert clean["execution_enabled"] is False
    assert clean["mode"] == "research"
    assert clean["source"] == "coinglass_authorized_browser"
    assert clean["symbol"] == "BTCUSDT"
    assert len(clean["liquidation_heatmap"]["levels"]) == 8
    assert len(clean["whale_orders"]["rows"]) == 4
    assert build_visual_indicator(clean, now=NOW)["execution_enabled"] is False


def test_visual_indicator_exposes_nearest_levels_and_decelerating_depth():
    indicator = build_visual_indicator(snapshot(), now=NOW + timedelta(seconds=30))

    assert indicator["validated"] is False
    assert indicator["execution_enabled"] is False
    assert indicator["levels"]["nearest_above"]["price"] == 64_482.8
    assert indicator["levels"]["nearest_below"]["price"] == 63_598.8
    assert indicator["levels"]["strongest_below"]["price"] == 63_377.8
    assert indicator["depth"]["latest_delta_usd"] == 12_470_000
    assert indicator["depth"]["decelerating"] is True
    assert indicator["components"]["whale_bid_pressure"] > 0
    assert indicator["levels"]["nearest_whale_ask"]["price"] == 64_750
    assert indicator["coverage"]["whale_orders"] == 4
    assert -100 <= indicator["score"] <= 100
    assert "no predice" in indicator["warning"]


def test_visual_snapshot_rejects_stale_or_execution_payloads():
    stale = snapshot()
    stale["captured_at"] = (NOW - timedelta(hours=1)).isoformat()
    with pytest.raises(VisualSnapshotError, match="ventana temporal"):
        normalize_visual_snapshot(stale, now=NOW)

    unsafe = snapshot()
    unsafe["execution_enabled"] = True
    with pytest.raises(VisualSnapshotError, match="execution_enabled"):
        normalize_visual_snapshot(unsafe, now=NOW)


def test_visual_tooltip_parser_handles_coinglass_spanish_values():
    parsed = parse_tooltip(
        "2026-07-24 14:50\n"
        "Precio: 64,482.8\n"
        "Apalancamiento Liquidación: $8.85M\n"
        "Liquidación acumulada: $118.57M"
    )

    assert parse_money("$454.52K") == 454_520
    assert parsed["price"] == 64_482.8
    assert parsed["intensity_usd"] == 8_850_000
    assert parsed["cumulative_usd"] == 118_570_000


def test_visual_tooltip_parser_handles_new_stacked_tooltip_markup():
    parsed = parse_tooltip(
        "65688\n"
        "Apalancamiento de Liquidación Corta Acumulada\n"
        "342.89M\n"
        "Apalancamiento 10x\n"
        "1.20M\n"
        "Apalancamiento 50x\n"
        "7.93M\n"
        "Apalancamiento 100x\n"
        "21.87M"
    )

    assert parsed["price"] == 65_688
    assert parsed["cumulative_usd"] == 342_890_000
    assert parsed["intensity_usd"] == 31_000_000


def test_visual_tooltip_parser_handles_depth_delta_pairs():
    parsed = parse_tooltip("Delta\n-$11.82M\nPrecio BTC\n$65.07K")

    assert parsed["delta_usd"] == -11_820_000
    assert parsed["price"] == 65_070


def test_visual_whale_order_parser_uses_side_exchange_and_duration():
    parsed = parse_whale_order(
        "S\n61300\n$78.60M\n1D 3H",
        background_class="large-order-item-bg ovv2-item-bg-l",
        exchange_src=(
            "https://cdn.coinglasscdn.com/static/exchanges/coinbase%20pro.png"
        ),
    )

    assert parsed == {
        "side": "bid",
        "price": 61_300,
        "amount_usd": 78_600_000,
        "duration": "1D 3H",
        "market": "S",
        "exchange": "Coinbase",
    }


def test_visual_snapshot_rejects_canceled_whale_orders():
    unsafe = snapshot()
    unsafe["whale_orders"]["active_only"] = False

    with pytest.raises(VisualSnapshotError, match="activas"):
        normalize_visual_snapshot(unsafe, now=NOW)


def test_shadow_plan_and_replay_are_virtual_forward_only():
    indicator = build_visual_indicator(snapshot(), now=NOW)
    indicator.update({
        "score": 30,
        "price": 65_000,
        "captured_at": NOW.isoformat(),
        "levels": {
            "nearest_above": {"price": 66_000, "intensity_usd": 10_000_000},
            "nearest_below": {"price": 63_500, "intensity_usd": 10_000_000},
        },
    })
    plan = shadow_plan(indicator)
    later = {
        **indicator,
        "score": 0,
        "price": 66_100,
        "captured_at": (NOW + timedelta(minutes=5)).isoformat(),
    }
    result = replay_shadow([
        {"captured_at": indicator["captured_at"], "indicator": indicator},
        {"captured_at": later["captured_at"], "indicator": later},
    ])

    assert plan["action"] == "virtual_entry"
    assert plan["execution_enabled"] is False
    assert result["closed_trades"] == 1
    assert result["recent_trades"][0]["exit_reason"] == "target"
    assert result["metrics"]["total_net_pct"] > 0
    assert result["execution_enabled"] is False


def test_visual_ingest_is_separate_from_api_dashboard(monkeypatch, tmp_path):
    import modules.coinglass.module as module

    dashboard_path = tmp_path / "dashboard.json"
    visual_path = tmp_path / "visual.json"
    dashboard_path.write_text(json.dumps({
        "research_only": True,
        "execution_enabled": False,
        "mode": "research",
        "advanced": {"price": 64_000, "capabilities": {}},
    }))
    monkeypatch.setattr(module, "STATE_PATH", str(dashboard_path))
    monkeypatch.setattr(module, "VISUAL_STATE_PATH", str(visual_path))
    monkeypatch.setattr(
        module,
        "VISUAL_HISTORY_PATH",
        str(tmp_path / "visual-history.json"),
    )
    monkeypatch.setenv("NEXUS_INGEST_TOKEN", "secret")
    monkeypatch.setattr(module, "build_visual_indicator", lambda data: {
        "research_only": True,
        "score": 1,
        "captured_at": data["captured_at"],
    })
    monkeypatch.setattr(
        module,
        "normalize_visual_snapshot",
        lambda body: {**body, "symbol": "BTCUSDT"},
    )
    instance = module.CoinGlassModule(
        ModuleContext("coinglass", str(tmp_path), {}, lambda _message: None)
    )

    status, _, _ = instance.api_post(
        "visual-ingest",
        snapshot(),
        {"x-nexus-token": "secret"},
    )
    state_status, _, raw = instance.api("state", {}, user=None)
    state = json.loads(raw)

    assert status == 200
    assert state_status == 200
    assert json.loads(dashboard_path.read_text())["advanced"]["price"] == 64_000
    assert visual_path.stat().st_mode & 0o777 == 0o600
    assert state["visual_snapshot"]["source"] == "coinglass_authorized_browser"
    assert state["visual_indicator"]["score"] == 1


def test_visual_collector_and_model_have_no_bot_or_order_dependency():
    source = (
        (ROOT / "modules/coinglass/visual.py").read_text()
        + (ROOT / "modules/coinglass/visual_collector.py").read_text()
        + (ROOT / "modules/coinglass/shadow.py").read_text()
    )
    html = (ROOT / "modules/coinglass/public/index.html").read_text()
    script = (ROOT / "modules/coinglass/public/app.js").read_text()

    assert "modules.bot" not in source
    assert "place_order" not in source
    assert "execution_enabled" in source
    assert "Mapa visual" in html
    assert "SESIÓN AUTORIZADA" in html
    assert "renderVisual" in script
