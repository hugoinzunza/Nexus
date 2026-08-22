"""Gates de estabilizacion del grafico canonico de NexUX."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "modules/trading/public/app.js"
MODULE = ROOT / "modules/trading/module.py"
AUDIT = ROOT / "docs/NEXUX_CHART_AUDIT.md"


def _source(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _block(source: str, start: str, end: str) -> str:
    return source.split(start, 1)[1].split(end, 1)[0]


def test_la_auditoria_parte_en_nexux_y_command_center_solo_consume():
    audit = _source(AUDIT)
    assert "**Superficie canonica:** `modules/trading/`" in audit
    assert "Command Center" in audit and "consume esa superficie" in audit
    assert "no puede mantener un segundo motor" in audit


def test_velas_smc_y_backload_tienen_revisiones_independientes():
    app = _source(APP)
    assert "candlesRevision: 0, smcRevision: 0, olderRevision: 0" in app
    candles = _block(app, "async function loadCandles", "// Back-load")
    assert "const revision = ++card.candlesRevision" in candles
    assert "card.candlesRevision !== revision" in candles
    assert "cardEsVigente(card, tf)" in candles
    smc = _block(app, "async function loadSMC", "function applySMC")
    assert "const revision = ++card.smcRevision" in smc
    assert smc.count("card.smcRevision !== revision") >= 3
    assert smc.count("cardEsVigente(card, tf)") >= 3
    older = _block(app, "async function loadOlder", "// --- Render principal")
    assert "const revision = ++card.olderRevision" in older
    assert "card.olderRevision !== revision" in older


def test_el_socket_solo_puede_escribir_en_su_generacion_y_tarjeta():
    app = _source(APP)
    vivo = _block(app, "const vivoBinance =", "// Escribe la vela del stream")
    assert "generacion: 0" in vivo
    assert "const generacion = this.generacion" in vivo
    assert "this.ws === ws" in vivo
    assert "this.generacion === generacion" in vivo
    assert "this.card === card" in vivo
    assert "cardEsVigente(card, tf)" in vivo
    assert "this.generacion += 1" in vivo
    assert "if (!vigente()) return" in vivo


def test_cambiar_temporalidad_invalida_y_limpia_antes_de_recargar():
    app = _source(APP)
    selector = _block(app, "function buildTimeframeSelector", "// --- Expandir")
    for revision in ("candlesRevision", "smcRevision", "olderRevision"):
        assert f"card.{revision} += 1" in selector
    assert "if (vivoBinance.card === card) vivoBinance.cerrar()" in selector
    assert "card.series.setData([])" in selector
    assert selector.index("card.series.setData([])") < selector.index("loadCandles(symbol, card)")
    assert selector.index("card.series.setData([])") < selector.index("loadSMC(symbol, card)")


def test_ocultar_tarjeta_invalida_fetches_y_cierra_su_socket():
    app = _source(APP)
    pause = _block(app, "function pauseCard", "function resumeCard")
    for revision in ("candlesRevision", "smcRevision", "olderRevision"):
        assert f"card.{revision} += 1" in pause
    assert "if (vivoBinance.card === card) vivoBinance.cerrar()" in pause


def test_smc_legado_declara_su_limite_sin_tocar_su_feed():
    module = _source(MODULE)
    smc = _block(module, "def _smc_analysis", "\\n    def ")
    assert "_candles_cached" in smc
    assert "klines_push" not in smc
    api = _block(module, 'if subpath == "smc":', 'if subpath == "board":')
    assert '"id": "nexux.smc.course-legacy.v1"' in api
    assert '"nexux.smc.legacy.v1"' in api
    assert '"validated": False' in api
    assert '"bot3_compatible": False' in api
    assert '"causal_availability": False' in api


def test_capas_smc_legadas_no_quedan_encendidas_por_defecto():
    app = _source(APP)
    assert 'const IND_KEY = "nexus_trading_ind_v2"' in app
    defaults = _block(app, "const IND_DEFAULTS =", ";")
    assert "vol: true" in defaults
    assert "levels: false" in defaults
    assert "tpsl: false" in defaults
    apply = _block(app, "function applySMC", "function computeRibbon")
    assert "if (rng && indState.levels)" in apply
    renderer = _block(app, "class SMCRenderer", "class SMCPaneView")
    assert "show.levels && smc.range" in renderer
    # El gating de FVG/OB pasó al adaptador compartido (gate 2), pero la regla
    # es la misma: con `course` activo o sin `levels`, no se piden.
    assert "fvg: !course && show.levels" in renderer
    assert "ob: !course && (show.levels || show.htf)" in renderer
    assert "cdc: !course && Boolean(show.tpsl)" in renderer

    panel = _block(app, "function renderSMCPanel", "// El gráfico")
    assert "Contexto SMC legado · no Bot3" in panel
    assert "Capas legadas desactivadas" in panel
