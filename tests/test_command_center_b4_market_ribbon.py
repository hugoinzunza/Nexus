import json
import subprocess
from pathlib import Path

from core.module_base import ModuleContext
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
    stats = service.stats()
    assert stats["status"] == "degraded"
    assert stats["refresh_count"] == 2
    assert stats["cache_hit_count"] == 0
    assert stats["last_refresh_ms"] == now[0]
    assert stats["last_refresh_duration_ms"] >= 0
    assert stats["cached_providers"] == [
        "binance-futures",
        "coingecko",
        "yahoo",
    ]
    assert stats["current_error_providers"] == [
        "binance-futures",
        "coingecko",
        "yahoo",
    ]
    assert stats["provider_successes"] == {
        "binance-futures": 1,
        "coingecko": 1,
        "yahoo": 1,
    }
    assert stats["provider_failures"] == {
        "binance-futures": 1,
        "coingecko": 1,
        "yahoo": 1,
    }


def test_telemetria_distingue_cache_de_refresh_sin_exponer_precios() -> None:
    service = MarketRibbonService(
        fetch_json=_provider_payload,
        clock_ms=lambda: NOW,
    )

    assert service.stats()["status"] == "idle"
    service.snapshot()
    service.snapshot()
    stats = service.stats()

    assert stats["status"] == "ready"
    assert stats["refresh_count"] == 1
    assert stats["cache_hit_count"] == 1
    assert stats["last_refresh_ms"] == NOW
    assert stats["last_refresh_duration_ms"] >= 0
    assert stats["current_error_providers"] == []
    assert stats["provider_failures"] == {}
    assert "price" not in json.dumps(stats)


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


def test_health_expone_telemetria_del_ribbon_sin_forzar_un_refresh(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.setenv(
        "NEXUX_CONTEXT_RECORDER_PATH",
        str(tmp_path / "context.jsonl"),
    )
    module = CommandCenterModule(
        ModuleContext(
            "command_center",
            str(ROOT / "modules" / "command_center"),
            {},
            lambda _message: None,
        )
    )

    health = module.health()

    assert health["market_ribbon"]["status"] == "idle"
    assert health["market_ribbon"]["refresh_count"] == 0
    assert health["market_ribbon"]["cached_providers"] == []
    assert health["context_recorder"]["status"] == "idle"
    assert health["context_recorder"]["sequence"] == 0
    assert health["context_recorder"]["enabled"] is False
    assert health["context_recorder"]["activation_blockers"] == [
        "not_requested",
        "persistence_unconfirmed",
        "backup_unconfirmed",
    ]
    assert health["context_recorder"]["collector_running"] is False
    assert health["context_recorder"]["poll_seconds"] == 30.0
    assert health["context_interpreter"]["status"] == "ready"
    assert health["context_interpreter"]["claims"] == 0
    assert health["context_interpreter"]["abstentions"] == 0


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


def test_insight_layer_deriva_amplitud_y_se_abstiene_sin_cobertura() -> None:
    script_uri = (PUBLIC / "command-center.js").resolve().as_uri()
    node = f"""
      import({json.dumps(script_uri)}).then((module) => {{
        const asset = (id, changePct, freshness = "live") => ({{
          id, changePct, freshness
        }});
        const result = {{
          strong: module.deriveMarketInsight([
            asset("btcusdt", 3.2), asset("ethusdt", 2.6),
            asset("solusdt", 2.1), asset("xrpusdt", -0.2)
          ]),
          cautious: module.deriveMarketInsight([
            asset("btcusdt", 0.2), asset("ethusdt", 0.1),
            asset("solusdt", 0.3), asset("xrpusdt", -0.1)
          ]),
          bearish: module.deriveMarketInsight([
            asset("btcusdt", -1.4), asset("ethusdt", -0.8),
            asset("solusdt", -0.6), asset("xrpusdt", 0.2)
          ]),
          mixed: module.deriveMarketInsight([
            asset("btcusdt", 1.4), asset("ethusdt", -0.8),
            asset("solusdt", 0.6), asset("xrpusdt", -0.2)
          ]),
          absent: module.deriveMarketInsight([
            asset("btcusdt", 3.2, "stale"), asset("ethusdt", 2.6, "unknown"),
            asset("solusdt", 2.1), asset("xrpusdt", -0.2)
          ])
        }};
        process.stdout.write(JSON.stringify(result));
      }});
    """
    result = subprocess.run(
        ["node", "--input-type=module", "-e", node],
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(result.stdout)

    assert payload["strong"]["text"] == "Cripto avanza con fuerza"
    assert payload["cautious"]["text"] == "Cripto avanza con cautela"
    assert payload["bearish"]["text"] == "Cripto mantiene tono bajista"
    assert payload["mixed"]["text"] == "Cripto opera sin dirección común"
    assert payload["absent"] == {
        "state": "unknown",
        "text": "Contexto insuficiente",
        "evidence": "2/4 activos cripto con lectura vigente",
    }


def test_insight_layer_reutiliza_pulso_sin_agregar_modulos() -> None:
    page = (PUBLIC / "index.html").read_text(encoding="utf-8")
    script = (PUBLIC / "command-center.js").read_text(encoding="utf-8")

    assert page.count('class="market-ribbon"') == 1
    assert 'id="market-ribbon-insight"' in page
    assert "deriveMarketInsight(state.assets)" in script
    assert "desde hace" not in script


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
    assert script.count('method: "POST"') == 1
    assert '"/m/command-center/api/media-command"' in script
    for symbol in ("SP:SPX", "TVC:VIX", "TVC:DXY", "CRYPTOCAP:TOTAL"):
        assert symbol not in adapter
    assert 'document.createElement(external ? "a" : "button")' in script
    assert 'control.target = "_blank"' in script
    assert 'control.rel = "noopener noreferrer"' in script
    assert 'control.dataset.destination' in script
    assert "control.title = [" in script
    assert "button.title = [" not in script
    assert 'querySelectorAll("button.market-asset")' in script
    assert 'asset.chartMode === "external_only"' in script
    assert "font-size: var(--font-md);" in css
    assert ".market-change {" in css
    assert "font-size: 15px;" in css
    for color in ("#19d9ff", "#20edac", "#ffbd3e", "#ff4168"):
        assert color in css


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
