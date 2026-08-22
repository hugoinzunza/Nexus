import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PUBLIC = ROOT / "modules" / "command_center" / "public"


def _run_node(body: str) -> dict:
    module_uri = (PUBLIC / "nexux-chart-provider.js").resolve().as_uri()
    script = f"""
      import * as chart from {json.dumps(module_uri)};
      {body}
    """
    result = subprocess.run(
        ["node", "--input-type=module", "-e", script],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout)


def test_nexux_chart_es_proveedor_principal_con_reversion_explicita() -> None:
    page = (PUBLIC / "index.html").read_text(encoding="utf-8")
    command_center = (PUBLIC / "command-center.js").read_text(encoding="utf-8")
    provider = (PUBLIC / "nexux-chart-provider.js").read_text(encoding="utf-8")

    assert '/static/vendor/lightweight-charts.standalone.production.js' in page
    assert "NexUX Chart · fuente declarada" in page
    assert "Sincronizando NexUX Trading" in page
    assert '"NexUX Chart · fuente declarada"' in command_center
    assert 'new NexuxChartProvider()' in command_center
    assert 'parameters.get("provider") === "tradingview"' in command_center
    assert 'new TradingViewWidgetAdapter()' in command_center
    assert 'https://fapi.binance.com/fapi/v1/klines' not in provider
    assert '/m/trading/api/candles?' in provider
    assert 'wss://fstream.binance.com/stream?streams=' in provider
    assert "@bookTicker" in provider
    assert "Lightweight Charts™" in provider


def test_temporalidades_sinteticas_se_agregan_sin_inventar_ohlc() -> None:
    payload = _run_node(
        """
        const base = [
          {t: 0, o: 10, h: 12, l: 9, c: 11, v: 2},
          {t: 900000, o: 11, h: 14, l: 10, c: 13, v: 3},
          {t: 1800000, o: 13, h: 15, l: 8, c: 9, v: 5},
          {t: 2700000, o: 9, h: 10, l: 7, c: 8, v: 4}
        ];
        process.stdout.write(JSON.stringify({
          fortyFive: chart.aggregateCandles(base, "45m"),
          direct: chart.aggregateCandles(base.slice(0, 1), "15m"),
          spec: chart.intervalSpec("3h")
        }));
        """
    )

    assert payload["fortyFive"] == [
        {"t": 0, "o": 10, "h": 15, "l": 8, "c": 9, "v": 10},
        {"t": 2_700_000, "o": 9, "h": 10, "l": 7, "c": 8, "v": 4},
    ]
    assert payload["direct"] == [
        {"t": 0, "o": 10, "h": 12, "l": 9, "c": 11, "v": 2}
    ]
    assert payload["spec"] == {
        "source": "1h",
        "durationMs": 10_800_000,
        "aggregate": 3,
    }


def test_normalizacion_binance_falla_cerrado_ante_velas_incompletas() -> None:
    payload = _run_node(
        """
        let invalid;
        try { chart.normalizeBinanceKline([1, "2"]); }
        catch (error) { invalid = error.code; }
        process.stdout.write(JSON.stringify({
          candle: chart.normalizeBinanceKline([1000, "1", "3", "0.5", "2", "7"]),
          invalid
        }));
        """
    )

    assert payload == {
        "candle": {"t": 1000, "o": 1, "h": 3, "l": 0.5, "c": 2, "v": 7},
        "invalid": "nexux-chart.invalid-candle",
    }


def test_estilos_del_grafico_respetan_superficie_estable_y_estado_del_feed() -> None:
    styles = (PUBLIC / "command-center.css").read_text(encoding="utf-8")

    assert ".nexux-chart-canvas" in styles
    assert 'inset: 0;' in styles
    assert '.nexux-chart-feed[data-state="live"]' in styles
    assert '.nexux-chart-feed[data-state="degraded"]' in styles
    assert '.nexux-chart-now.visible' in styles


def test_capa_de_indicadores_reutiliza_las_velas_del_grafico() -> None:
    payload = _run_node(
        """
        const closes = Array.from({length: 40}, (_, index) => 100 + index);
        const candles = closes.map((close, index) => ({
          t: index * 60000,
          o: close - 0.5,
          h: close + 1,
          l: close - 1,
          c: close,
          v: index + 1,
        }));
        process.stdout.write(JSON.stringify({
          ema: chart.emaValues(closes, 21),
          rsi: chart.rsiValues(closes, 14),
          adx: chart.adxValues(candles, 14),
        }));
        """
    )

    assert len(payload["ema"]) == 40
    assert payload["ema"][0] == 100
    assert payload["ema"][-1] > payload["ema"][20]
    assert payload["rsi"][:14] == [None] * 14
    assert payload["rsi"][-1] > 99
    assert payload["adx"][-1] > 99


def test_selector_expone_solo_capas_honestas_y_persistentes() -> None:
    provider = (PUBLIC / "nexux-chart-provider.js").read_text(encoding="utf-8")
    command_center = (PUBLIC / "command-center.js").read_text(encoding="utf-8")
    styles = (PUBLIC / "command-center.css").read_text(encoding="utf-8")

    assert '"nexux.command-center.chart-indicators.v4"' in provider
    assert "volume: false" in provider
    for legacy in ("structure", "fvg", "ob", "cdc"):
        assert f"{legacy}: false" in provider
    assert '["volume", "Volumen"' in provider
    assert '["structure", "Estructura NexUX"' in provider
    assert '["ema", "EMA 21 / 55"' in provider
    assert '["rsi", "RSI 14"' in provider
    assert '["adx", "ADX 14"' in provider
    assert '["fvg", "FVG"' in provider
    assert '["ob", "Order Blocks"' in provider
    assert '["cdc", "CDC"' in provider
    assert 'fetcher(`/m/trading/api/smc?' in provider
    assert 'SMC_INTERVALS.has(this.interval)' in provider
    assert "this.series.attachPrimitive(this.smcPrimitive)" in provider
    # El dibujo de FVG, OB y CDC se comparte con NexUX Trading desde el gate 2:
    # el proveedor normaliza y delega, no interpreta el payload por su cuenta.
    assert 'from "../../../static/nexux-smc-primitive.js"' in provider
    assert "normalizarAnalisis(payload.analysis" in provider
    assert "dibujarSmc(context, capas" in provider
    canonico = (ROOT / "static" / "nexux-smc-primitive.js").read_text(encoding="utf-8")
    assert "analysis.cdc_events" in canonico
    assert "analysis.fvgs" in canonico
    assert "analysis.pois" in canonico
    assert "this.#refreshStructure();" in provider
    assert "revision !== this.structureRevision" in provider
    assert "await this.#loadStructure()" not in provider
    assert "setInterval(() => this.#refresh().catch(() => {}), 15_000)" not in provider
    assert "#refreshStructure({ clear = false } = {})" in provider
    assert "this.#refreshStructure({ clear: true });" in provider
    assert "adapter.setInterval(interval)" in command_center
    assert '"nexux.command-center.chart-interval.v1"' in command_center
    assert "localStorage.setItem(CHART_INTERVAL_STORAGE_KEY, interval)" in command_center
    assert "this.structureAnalysis = null;\n      this.#applyStructureLines();" in provider
    assert 'const smcLabel = legacySmc ? "SMC legado" : "SMC";' in provider
    assert ".nexux-chart-indicator-menu" in styles
    assert '.nexux-chart-indicator-menu[hidden]' in styles


def test_command_center_consume_velas_y_stream_de_nexux() -> None:
    provider = (PUBLIC / "nexux-chart-provider.js").read_text(encoding="utf-8")

    assert 'instrument: symbol.local' in provider
    assert 'timeframe: spec.source' in provider
    assert 'payload.candles.map' in provider
    assert 'stream: payload.stream_vivo || null' in provider
    assert 'this.liveStream = page.stream' in provider
    assert 'const kline = this.liveStream' in provider
    assert 'const symbol = kline.split("@")[0]' in provider
    assert 'source: "nexux-trading"' not in provider  # no hardcode por evento
    assert 'this.source = "nexux-trading"' in provider


def test_temporalidades_sinteticas_derivan_de_las_tfs_canonicas() -> None:
    payload = _run_node(
        """
        process.stdout.write(JSON.stringify({
          threeMinutes: chart.intervalSpec("3m"),
          thirtyMinutes: chart.intervalSpec("30m"),
          twoHours: chart.intervalSpec("2h"),
          oneWeek: chart.intervalSpec("1W")
        }));
        """
    )

    assert payload == {
        "threeMinutes": {"source": "1m", "durationMs": 180_000, "aggregate": 3},
        "thirtyMinutes": {"source": "15m", "durationMs": 1_800_000, "aggregate": 2},
        "twoHours": {"source": "1h", "durationMs": 7_200_000, "aggregate": 2},
        "oneWeek": {"source": "1D", "durationMs": 604_800_000, "aggregate": 7},
    }
