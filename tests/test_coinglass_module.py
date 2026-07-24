import json
from pathlib import Path

from core.module_base import ModuleContext
from datetime import datetime, timezone

from modules.coinglass.provider import build_dashboard, fetch_advanced, update_dashboard

ROOT = Path(__file__).resolve().parents[1]


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload
        self.headers = {}

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def read(self):
        return json.dumps(self.payload).encode()


def test_advanced_provider_normalizes_maps_heatmap_book_and_large_orders():
    def opener(request, timeout):
        assert timeout in {15, 30}
        url = request.full_url
        if "fapi.binance.com" in url:
            return FakeResponse({"price": "65432.1"})
        if "liquidation%2Fmap" in url or "liquidation/map" in url:
            data = {"data": {
                "66000": [[66000, 1_500_000, 25, None], [66000, 500_000, 50, None]],
                "64000": [[64000, 900_000, 20, None]],
            }}
        elif "aggregated-heatmap" in url:
            data = {
                "y_axis": [64000, 65000, 66000],
                "liquidation_leverage_data": [[0, 1, 200_000], [1, 2, 900_000]],
                "price_candlesticks": [[1, "65000", "65100", "64900", "65050", "10"]],
            }
        elif "orderbook/history" in url:
            data = [[1, [[64000, 2.5]], [[66000, 3.5]]]]
        elif "large-limit-order" in url:
            data = [{
                "price": 64000,
                "current_usd_value": 1_200_000,
                "order_side": 2,
                "start_time": 1,
                "order_state": 1,
            }]
        else:
            raise AssertionError(url)
        return FakeResponse({"code": "0", "msg": "success", "data": data})

    advanced = fetch_advanced("private", opener=opener)

    assert advanced["price"] == 65432.1
    assert advanced["liquidation_map"][0] == {
        "price": 66000.0,
        "amount_usd": 2_000_000.0,
        "leverages": [25, 50],
    }
    assert advanced["liquidation_heatmap"]["points"] == [
        [1, 2, 900000.0],
        [0, 1, 200000.0],
    ]
    assert advanced["orderbook_heatmap"][0]["bids"] == [[64000.0, 2.5]]
    assert advanced["large_orders"][0]["side"] == "buy"
    assert all(row["available"] for row in advanced["capabilities"].values())
    assert "private" not in json.dumps(advanced)


def test_advanced_provider_marks_unavailable_capability_without_failing_everything():
    def opener(request, timeout):
        if "fapi.binance.com" in request.full_url:
            return FakeResponse({"price": "65000"})
        if "liquidation/map" in request.full_url:
            return FakeResponse({"code": "401", "msg": "Professional plan required"})
        return FakeResponse({"code": "0", "msg": "success", "data": []})

    advanced = fetch_advanced("key", opener=opener)

    assert advanced["capabilities"]["liquidation_map"]["available"] is False
    assert "Professional" in advanced["capabilities"]["liquidation_map"]["reason"]
    assert advanced["capabilities"]["large_orders"]["available"] is True


def test_orderbook_heatmap_negotiates_4h_when_1h_is_not_in_plan():
    def opener(request, timeout):
        url = request.full_url
        if "fapi.binance.com" in url:
            return FakeResponse({"price": "65000"})
        if "orderbook/history" in url and "interval=1h" in url:
            return FakeResponse({"code": "400", "msg": "interval unavailable"})
        return FakeResponse({"code": "0", "msg": "success", "data": []})

    advanced = fetch_advanced("key", opener=opener)

    assert advanced["capabilities"]["orderbook_heatmap"] == {
        "available": True,
        "interval": "4h",
    }


def test_dashboard_is_research_only_and_pressure_is_transparent():
    basic = {
        "captured_at": "2026-07-24T15:00:00+00:00",
        "indicators": {
            "funding": {"close_pct": [0.01]},
            "open_interest": {"close_btc": [100, 101]},
            "top_traders": {"long_pct": [60]},
            "orderbook": {"bid_ask_ratio": [2]},
        },
    }
    advanced = {
        "captured_at": "2026-07-24T15:00:00+00:00",
        "price": 65000,
        "capabilities": {},
        "liquidation_map": [
            {"price": 66000, "amount_usd": 2_000_000},
            {"price": 64000, "amount_usd": 1_000_000},
        ],
    }

    dashboard = build_dashboard(basic, [basic], advanced)

    assert dashboard["research_only"] is True
    assert dashboard["execution_enabled"] is False
    assert dashboard["mode"] == "research"
    model = dashboard["experimental_pressure"]
    assert model["validated"] is False
    assert model["status"] == "collecting"
    assert model["minimum_for_calibration"] == 100
    assert set(model["components"]) == {
        "liquidation_attraction",
        "orderbook_imbalance",
        "positioning_contrarian",
        "funding_contrarian",
    }


def test_dashboard_cache_avoids_requery_and_never_persists_key(tmp_path):
    basic = {
        "captured_at": "2026-07-24T15:00:00+00:00",
        "indicators": {},
    }
    advanced = {
        "captured_at": "2026-07-24T15:00:00+00:00",
        "price": 65000,
        "capabilities": {},
    }
    path = tmp_path / "dashboard.json"
    first = update_dashboard(
        "private-key",
        path,
        basic,
        [basic],
        now=datetime(2026, 7, 24, 15, 0, tzinfo=timezone.utc),
        advanced_fetcher=lambda _key: advanced,
    )
    second = update_dashboard(
        "private-key",
        path,
        basic,
        [basic],
        now=datetime(2026, 7, 24, 15, 4, tzinfo=timezone.utc),
        advanced_fetcher=lambda _key: (_ for _ in ()).throw(AssertionError("cache miss")),
    )

    assert first["advanced"] == second["advanced"]
    assert path.stat().st_mode & 0o777 == 0o600
    assert "private-key" not in path.read_text()


def test_module_ingest_rejects_execution_payload(monkeypatch, tmp_path):
    import modules.coinglass.module as module

    monkeypatch.setattr(module, "STATE_PATH", str(tmp_path / "coinglass.json"))
    monkeypatch.setenv("NEXUS_INGEST_TOKEN", "secret")
    context = ModuleContext("coinglass", str(tmp_path), {}, lambda _message: None)
    instance = module.CoinGlassModule(context)

    status, _, raw = instance.api_post(
        "ingest",
        {"research_only": True, "execution_enabled": True, "mode": "research"},
        {"x-nexus-token": "secret"},
    )

    assert status == 400
    assert "sin ejecucion" in json.loads(raw)["error"]


def test_module_is_enabled_protected_and_has_no_executor_dependency():
    config = json.loads((ROOT / "config/nexus.json").read_text())
    app = (ROOT / "core/app.py").read_text()
    source = (
        (ROOT / "modules/coinglass/module.py").read_text()
        + (ROOT / "modules/coinglass/provider.py").read_text()
    )

    assert config["modules"]["coinglass"]["enabled"] is True
    assert '"coinglass"' in app[app.index("_LOGIN_REQUIRED"):app.index("def _gate")]
    assert "modules.bot" not in source
    assert "place_order" not in source
    assert "execution_enabled" in source


def test_panel_exposes_real_research_views_and_no_signal_language():
    html = (ROOT / "modules/coinglass/public/index.html").read_text()
    script = (ROOT / "modules/coinglass/public/app.js").read_text()

    assert "Mapa de liquidaciones" in html
    assert "Libro de órdenes" in html
    assert "Radar" in html
    assert "MODELO 0 · NO VALIDADO" in html
    assert "No es una señal" in html
    assert "drawLevelMap" in script
    assert "drawLiquidationHeatmap" in script
    assert "drawOrderbook" in script
