import json
import subprocess
from pathlib import Path

from modules.command_center.contracts import CONTRACT_V1_FINGERPRINT
from modules.command_center.market_ribbon import MarketRibbonService
from modules.command_center.module import CommandCenterModule
from modules.command_center.module_registry import command_center_module_registry


ROOT = Path(__file__).resolve().parents[1]
PUBLIC = ROOT / "modules" / "command_center" / "public"
NOW = 1_800_000_000_000


def _provider_payload(url: str):
    if "finance.yahoo.com" in url:
        if "%5EGSPC" in url:
            symbol, price, previous = "^GSPC", 6000.0, 5940.0
        elif "%5EVIX" in url:
            symbol, price, previous = "^VIX", 18.0, 20.0
        else:
            symbol, price, previous = "DX-Y.NYB", 101.5, 100.0
        return {
            "chart": {
                "result": [
                    {
                        "meta": {
                            "symbol": symbol,
                            "regularMarketPrice": price,
                            "chartPreviousClose": previous,
                            "regularMarketTime": NOW // 1000,
                            "priceHint": 2,
                        }
                    }
                ]
            }
        }
    if "api.coingecko.com" in url:
        return {
            "data": {
                "total_market_cap": {"usd": 3_000_000_000_000},
                "market_cap_change_percentage_24h_usd": 2.5,
                "updated_at": NOW // 1000,
            }
        }
    if "fapi.binance.com" in url:
        return [
            {
                "symbol": symbol,
                "lastPrice": price,
                "priceChangePercent": change,
                "closeTime": NOW,
            }
            for symbol, price, change in (
                ("BTCUSDT", "70000", "1.2"),
                ("ETHUSDT", "3500", "-0.4"),
                ("SOLUSDT", "180", "0.8"),
                ("XRPUSDT", "2.1", "-1.1"),
            )
        ]
    raise AssertionError(f"URL inesperada: {url}")


def test_agregador_publica_los_ocho_activos_en_orden_y_con_timestamp() -> None:
    service = MarketRibbonService(
        fetch_json=_provider_payload,
        clock_ms=lambda: NOW,
    )

    snapshot = service.snapshot()

    assert [row["symbol"] for row in snapshot["assets"]] == [
        "SPX",
        "VIX",
        "DXY",
        "TOTAL",
        "BTCUSDT.P",
        "ETHUSDT.P",
        "SOLUSDT.P",
        "XRPUSDT.P",
    ]
    assert snapshot["provider_errors"] == []
    assert all(row["observed_at_ms"] == NOW for row in snapshot["assets"])
    assert all(row["freshness"] == "live" for row in snapshot["assets"])
    assert snapshot["assets"][0]["change_pct"] == 1.01
    assert snapshot["assets"][0]["chart_mode"] == "external_only"
    assert snapshot["assets"][3]["chart_mode"] == "external_only"
    assert snapshot["assets"][4]["chart_mode"] == "tradingview"
    assert snapshot["assets"][3]["source"] == "CoinGecko"
    assert snapshot["assets"][4]["source"] == "Binance Futures"


def test_fallo_de_proveedor_conserva_ultimo_valor_y_expone_degradacion() -> None:
    now = [NOW]
    failing = [False]

    def fetch(url):
        if failing[0]:
            raise TimeoutError("provider timeout")
        return _provider_payload(url)

    service = MarketRibbonService(
        fetch_json=fetch,
        clock_ms=lambda: now[0],
        ttl_ms=1000,
    )
    baseline = service.snapshot()
    failing[0] = True
    now[0] += 40 * 60_000

    degraded = service.snapshot()

    assert [row["price"] for row in degraded["assets"]] == [
        row["price"] for row in baseline["assets"]
    ]
    assert {row["provider"] for row in degraded["provider_errors"]} == {
        "yahoo",
        "coingecko",
        "binance-futures",
    }
    assert degraded["assets"][0]["freshness"] == "current"
    assert degraded["assets"][3]["freshness"] == "stale"
    assert degraded["assets"][4]["freshness"] == "stale"


def test_endpoint_es_autenticado_read_only_y_fuera_del_wire_abi() -> None:
    class Ribbon:
        def snapshot(self):
            return {"generated_at_ms": NOW, "assets": []}

    module = object.__new__(CommandCenterModule)
    module.market_ribbon = Ribbon()
    module.context = type("Context", (), {"log": lambda *_args: None})()

    unauthorized = module.api("market-ribbon", {}, user=None)
    authorized = module.api("market-ribbon", {}, user={"id": 1})

    assert unauthorized[0] == 401
    assert authorized[0] == 200
    assert json.loads(authorized[2])["generated_at_ms"] == NOW
    assert command_center_module_registry().stats()["attached_factories"] == 0
    assert CONTRACT_V1_FINGERPRINT == (
        "b0a8a7efa623a1aae4b681c3cfc42790d36a6a14fbc689688026c523f2e49b46"
    )


def test_frontend_normaliza_orden_formato_y_frescura_sin_inventar() -> None:
    script_uri = (PUBLIC / "command-center.js").resolve().as_uri()
    node = f"""
      import({json.dumps(script_uri)}).then((module) => {{
        const rows = module.normalizeMarketRibbon({{
          assets: [
            {{ id: "btcusdt", symbol: "BTCUSDT.P", chart_symbol: "BTCUSDT",
               tv_symbol: "BINANCE:BTCUSDT.P", price: 70000,
               change_pct: 1.2, freshness: "live", kind: "futures" }},
            {{ id: "spx", symbol: "SPX", chart_symbol: "SPX",
               tv_symbol: "SP:SPX", chart_mode: "external_only",
               price_decimals: 2, price: null,
               change_pct: null, freshness: "invented", kind: "index" }}
          ]
        }});
        process.stdout.write(JSON.stringify({{
          ids: rows.map((row) => row.id),
          spx: rows[0],
          btcPrice: module.formatMarketPrice(rows[4]),
          exactIndex: module.formatMarketPrice({{
            price: 7437.63, priceDecimals: 2, kind: "index"
          }}),
          spxMode: rows[0].chartMode,
          spxUrl: module.tradingViewAnalysisUrl(rows[0])
        }}));
      }});
    """
    result = subprocess.run(
        ["node", "--input-type=module", "-e", node],
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(result.stdout)

    assert payload["ids"] == [
        "spx",
        "vix",
        "dxy",
        "total",
        "btcusdt",
        "ethusdt",
        "solusdt",
        "xrpusdt",
    ]
    assert payload["spx"]["price"] is None
    assert payload["spx"]["freshness"] == "unknown"
    assert payload["btcPrice"] != "--"
    assert payload["exactIndex"].endswith("437,63")
    assert payload["spxMode"] == "external_only"
    assert payload["spxUrl"].endswith("symbol=SP%3ASPX")


def test_b4_reutiliza_banda_superior_y_seleccion_remonta_chart_provider() -> None:
    page = (PUBLIC / "index.html").read_text(encoding="utf-8")
    script = (PUBLIC / "command-center.js").read_text(encoding="utf-8")
    css = (PUBLIC / "command-center.css").read_text(encoding="utf-8")
    adapter = (PUBLIC / "tradingview-spike.js").read_text(encoding="utf-8")

    assert page.count('class="market-ribbon"') == 1
    assert 'id="attention-band"' not in page
    assert 'id="market-ribbon-list"' in page
    assert 'id="full-analysis-link"' in page
    assert "grid-template-columns: repeat(8, minmax(0, 1fr));" in css
    assert "setChartLabels" in script
    assert "activeChartAdapter.destroy()" in script
    assert "method: \"POST\"" not in script
    for symbol in ("SP:SPX", "TVC:VIX", "TVC:DXY", "CRYPTOCAP:TOTAL"):
        assert symbol not in adapter
    assert "openTradingViewAnalysis(asset)" in script
    assert 'button.dataset.destination' in script
    assert 'asset.chartMode === "external_only"' in script
    assert "font-size: var(--font-md);" in css


def test_b4_documenta_val_0020_sin_cerrar_val_0019() -> None:
    validation = (ROOT / "docs" / "VALIDATION_LOG.md").read_text(
        encoding="utf-8"
    )
    rfc = (ROOT / "docs" / "RFC_COMMAND_CENTER.md").read_text(
        encoding="utf-8"
    )

    assert "VAL-0019" in validation
    assert "PENDIENTE perceptualmente" in validation
    assert "VAL-0020" in validation
    assert "Market Ribbon" in rfc
