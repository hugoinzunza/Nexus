import asyncio
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
    collect_with_retry,
    parse_money,
    parse_tooltip,
    parse_whale_order,
)
from modules.coinglass.shadow import replay_shadow, shadow_plan

ROOT = Path(__file__).resolve().parents[1]
# Anclado al reloj REAL, no a una fecha fija. El recorte del historial público
# (`_recent_by_time`, ventana de 24 h) corre contra `datetime.now()` dentro del
# módulo, así que un NOW fijo convierte estos tests en una bomba de tiempo: pasan
# el día que se escriben y fallan solos cuando el fixture cruza las 24 h. Ya pasó
# el 2026-07-25 con NOW = 2026-07-24T18:00. Los tests que necesitan un instante
# determinista lo pasan explícito por `now=`, relativo a este ancla.
# Hora fija (18:00) pero DÍA de hoy: los tooltips del heatmap vienen en "HH:MM" y
# se resuelven contra la fecha de la captura, así que la hora tiene que ser estable
# para que los desfases esperados no dependan de cuándo corre la suite; y el día
# tiene que ser el de hoy para caer siempre dentro de la ventana de 24 h.
NOW = datetime.now(timezone.utc).replace(hour=18, minute=0, second=0, microsecond=0)


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
    # El "más cercano" es el PRIMER PELDAÑO de la escalera (2026-07-26). Antes se
    # elegía con un umbral absoluto de 5M y eso reportaba el imán más lejos de lo
    # que estaba; se afirma la INVARIANTE en vez de un número mágico.
    niveles = indicator["levels"]
    assert niveles["nearest_above"] == niveles["escalera_arriba"][0]
    assert niveles["nearest_below"] == niveles["escalera_abajo"][0]
    assert niveles["nearest_above"]["price"] > indicator["price"]
    assert niveles["nearest_below"]["price"] < indicator["price"]
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


def test_visual_collector_retries_with_a_fresh_browser_session(monkeypatch):
    calls = 0

    async def flaky_collect(profile, *, headless=True):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("browser closed")
        return {"research_only": True}

    async def no_wait(_seconds):
        return None

    monkeypatch.setattr(
        "modules.coinglass.visual_collector.collect",
        flaky_collect,
    )
    monkeypatch.setattr(
        "modules.coinglass.visual_collector.asyncio.sleep",
        no_wait,
    )

    result = asyncio.run(
        collect_with_retry(Path("/tmp/profile"), attempts=2)
    )

    assert result == {"research_only": True}
    assert calls == 2


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
    book_history_path = tmp_path / "visual-book-history.json"
    monkeypatch.setattr(
        module,
        "VISUAL_BOOK_HISTORY_PATH",
        str(book_history_path),
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
    book_history = json.loads(book_history_path.read_text())
    assert book_history[0]["research_only"] is True
    assert len(book_history[0]["bids"]) == 2
    assert len(book_history[0]["asks"]) == 2
    assert state["visual_snapshot"]["source"] == "coinglass_authorized_browser"
    assert state["visual_orderbook_history"] == book_history
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
    # Marcadores de que la capa visual sigue cableada. Antes se usaban "Mapa visual"
    # y "SESIÓN AUTORIZADA", que desaparecieron al fusionar esa pestaña con el Radar
    # (2026-07-26). Se reemplazan por marcadores del mismo bloque que sí sobreviven,
    # sin aflojar lo que este test protege: aislamiento de ejecución.
    assert "Cobertura del colector" in html
    assert "tooltip scan" in script
    assert "renderVisual" in script
    assert "visual_orderbook_history" in script
    assert "Historial de muros ballena" in html


def test_score_formula_esta_congelada_y_los_muros_quedan_fuera():
    """Candado de la fórmula del Radar (auditoría 2026-07-24).

    El puntaje debe ser exactamente 0.50·heatmap + 0.30·mapa + 0.20·delta,
    renormalizado por el peso disponible, y la presión de muros ballena NO
    puede entrar. Sin este test, agregar `whale_bid_pressure` al cálculo pasa
    la suite en verde y promueve al score una variable sin forward.
    """
    indicator = build_visual_indicator(snapshot(), now=NOW)
    c = indicator["components"]

    pesos = {"heatmap_attraction": 0.50, "map_attraction": 0.30, "depth_delta": 0.20}
    disponible = sum(w for k, w in pesos.items() if c[k] is not None)
    esperado = round(max(-100, min(100, sum(
        c[k] * w for k, w in pesos.items() if c[k] is not None) / disponible * 100)), 1)

    assert indicator["score"] == esperado, "la fórmula del score cambió sin actualizar el test"
    assert "whale_bid_pressure" in c, "la presión de muros debe seguir publicándose aparte"

    # Un desbalance de muros extremo no puede mover el puntaje ni una décima.
    cargado = snapshot()
    cargado["whale_orders"]["rows"] = [
        {"side": "bid", "price": 64_200 - i, "amount_usd": 900_000_000,
         "duration": "5H", "market": "S", "exchange": "binance"}
        for i in range(4)
    ]
    sesgado = build_visual_indicator(cargado, now=NOW)

    assert sesgado["components"]["whale_bid_pressure"] == 1.0
    assert sesgado["score"] == indicator["score"], \
        "los muros ballena entraron al score: no hay forward que lo justifique"


def test_niveles_del_heatmap_reportan_su_desfase_temporal():
    """El tooltip del heatmap trae su propio reloj; hay que compararlo con la
    captura. Sin esta medición no se puede saber si el 50% del score sale de
    una columna vieja del gráfico (hallazgo P0 de la auditoría 2026-07-24)."""
    indicator = build_visual_indicator(snapshot(), now=NOW)
    lag = indicator["coverage"]["heatmap_lag_seconds"]

    assert lag is not None, "el desfase del heatmap debe medirse, no ignorarse"
    assert lag == 11_400  # tooltip 14:50 UTC vs captura 18:00 UTC = 3h10m
    assert indicator["stale_heatmap"] is True


def test_radar_declara_pesos_frescura_y_dependencia_de_la_muestra():
    """La UI del Radar debe ser auditable: pesos explícitos, aviso de frescura,
    cambio de modelo declarado y muestra no presentada como independiente."""
    script = (ROOT / "modules/coinglass/public/app.js").read_text()

    assert "50% heatmap · 30% mapa · 20% delta" in script
    assert "NO entran al puntaje" in script
    assert "age_seconds" in script and "heatmap_lag_seconds" in script
    assert "OTRA fórmula" in script, "el cambio silencioso de modelo debe avisarse"
    assert "no solapadas" in script, "no presentar 2.016 capturas como independientes"
    assert "Math.abs(c.heatmap_attraction + c.map_attraction)" not in script, \
        "el consenso debe conservar el signo"


def test_reason_escapa_html_del_payload_de_ingesta():
    """El texto de `reason` viene del payload (token compartido) y se interpola
    en innerHTML. Debe escaparse en la fuente (auditoría 2026-07-24)."""
    script = (ROOT / "modules/coinglass/public/app.js").read_text()
    cuerpo = script.split("function reason(capability)")[1].split("\n}")[0]

    assert "escapeHtml(" in cuerpo, "reason() debe escapar antes de devolver"


def test_canceladas_prefiere_la_etiqueta_y_deja_traza_si_no_puede():
    """Se intenta identificar el checkbox por su ETIQUETA (antes se usaba `.first`
    a ciegas, que apagaría el control equivocado si CoinGlass agrega otro filtro).

    Si no hay etiqueta identificable, se cae al comportamiento histórico pero se
    REGISTRA `cancel_filter` para no afirmar `active_only` sin verificar. Fallar
    duro dejaba al colector sin datos cada 5 minutos, que es peor que un dato
    marcado como no verificado.
    """
    source = (ROOT / "modules/coinglass/visual_collector.py").read_text()
    bloque = source.split("async def _collect_whale_orders")[1].split("\nasync def")[0]

    assert "has-text" in bloque, "debe intentarse por etiqueta primero"
    assert "by_label" in bloque and "first_checkbox_unverified" in bloque, \
        "debe quedar traza de cómo se excluyeron las canceladas"
    assert "cancel_filter" in bloque


def test_dedup_de_muros_distingue_spot_de_futuros():
    """Un muro de igual precio y monto en spot y en futuros son DOS órdenes."""
    source = (ROOT / "modules/coinglass/visual_collector.py").read_text()
    bloque = source.split("async def _collect_whale_orders")[1].split("async def")[0]
    clave = bloque.split("key = (")[1].split("parsed[key]")[0]

    assert "market" in clave, "la clave de dedup debe incluir el venue"


def test_el_ancla_de_tiempo_sigue_al_reloj_real():
    """Candado contra la bomba de tiempo del 2026-07-25.

    `NOW` era una fecha fija (2026-07-24T18:00). El recorte del historial público
    corre contra `datetime.now()` DENTRO del módulo, así que los tests que pasan
    por `api("state")` pasaron el día que se escribieron y empezaron a fallar solos
    cuando el fixture cruzó las 24 h. Un test que se pudre con el calendario es
    peor que no tenerlo: falla sin que nadie haya tocado el código.
    """
    real = datetime.now(timezone.utc)
    assert abs((NOW - real).total_seconds()) < 24 * 3600, \
        "NOW quedo fuera de la ventana de 24 h: volvio a ser una fecha fija"
    assert NOW.hour == 18, \
        "la HORA debe ser estable o los desfases esperados del heatmap se mueven"
    assert NOW.date() == real.date()


def test_tooltip_marca_los_campos_inferidos():
    """Las heurísticas de relleno son necesarias (formatos sin etiqueta), pero un
    tooltip a medio pintar no puede confundirse con uno completo."""
    completo = parse_tooltip(
        "2026-07-24 14:50\nPrecio: 64,482.8\n"
        "Apalancamiento Liquidación: $8.85M\nLiquidación acumulada: $118.57M"
    )
    assert "inferred" not in completo

    apilado = parse_tooltip(
        "65688\nApalancamiento de Liquidación Corta Acumulada\n342.89M\n"
        "Apalancamiento 10x\n1.20M\nApalancamiento 50x\n7.93M\n"
        "Apalancamiento 100x\n21.87M"
    )
    assert apilado["inferred"] == ["price"], "el precio sin etiqueta es inferido"
    assert apilado["intensity_parts"] == 3, "deben registrarse los buckets sumados"


def test_colector_falla_cerrado_si_el_grafico_no_es_btc():
    """Las URLs no llevan símbolo: el activo depende del perfil de Chrome."""
    from modules.coinglass.visual_collector import _assert_chart_matches_symbol

    niveles_btc = [{"price": p} for p in (63_000, 64_000, 65_000)]
    _assert_chart_matches_symbol(niveles_btc, 64_238)      # no levanta

    niveles_eth = [{"price": p} for p in (3_100, 3_200, 3_300)]
    with pytest.raises(RuntimeError, match="no parece BTCUSDT"):
        _assert_chart_matches_symbol(niveles_eth, 64_238)


def test_historial_publico_se_recorta_por_tiempo_no_por_conteo():
    """288 entradas son 24 h solo si el timer nunca falló."""
    from modules.coinglass.module import _recent_by_time

    viejas = [{"captured_at": (NOW - timedelta(days=3)).isoformat()} for _ in range(5)]
    frescas = [{"captured_at": (NOW - timedelta(hours=2)).isoformat()} for _ in range(3)]
    recortado = _recent_by_time(viejas + frescas, hours=24, cap=288)

    assert len(recortado) == 3, "las entradas de hace 3 días no son 'últimas 24 h'"
    assert _recent_by_time([{"captured_at": "sin-formato"}], hours=24, cap=288) == []


def test_lag_del_heatmap_parsea_el_formato_real_de_produccion():
    """En producción el tooltip trae "YYYY-MM-DD HH:MM" (verificado en el VPS),
    no "HH:MM". Con el parser viejo el desfase salía None y el hallazgo P0 quedaba
    sin medir. Se ignoran las etiquetas que no son hora (p.ej. "Precio")."""
    snap = snapshot()
    tooltip = NOW + timedelta(hours=1, minutes=45)          # 19:45 del día de NOW
    snap["liquidation_heatmap"]["levels"] = [
        {**nivel, "timestamp": tooltip.strftime("%Y-%m-%d %H:%M")}
        for nivel in snap["liquidation_heatmap"]["levels"]
    ]
    snap["liquidation_heatmap"]["levels"][0]["timestamp"] = "Precio"

    indicator = build_visual_indicator(snap, now=NOW)
    lag = indicator["coverage"]["heatmap_lag_seconds"]

    # captura 18:00 UTC vs tooltip del mismo día 19:45 -> -6300 s
    assert lag == -6_300
    assert indicator["stale_heatmap"] is False   # negativo no es "atrasado"

    # Y el caso real observado: captura del día SIGUIENTE a la 01:09
    captura = tooltip + timedelta(hours=5, minutes=24, seconds=15)
    snap["captured_at"] = captura.isoformat()
    tardio = build_visual_indicator(snap, now=captura + timedelta(seconds=45))
    assert tardio["coverage"]["heatmap_lag_seconds"] == 19_455   # 5 h 24 min
    assert tardio["stale_heatmap"] is True


def test_paso_del_libro_se_mide_no_se_inventa():
    """El `interval` del depth delta decía "15m" a mano, pero el paso real depende
    del zoom del gráfico: `depth_slope` era una derivada de horizonte desconocido.
    """
    from modules.coinglass.visual_collector import _paso_observado

    cada_hora = [{"timestamp": "2026-07-24 10:00"}, {"timestamp": "2026-07-24 11:00"},
                 {"timestamp": "2026-07-24 12:00"}, {"timestamp": "2026-07-24 13:00"}]
    assert _paso_observado(cada_hora) == "1h"

    cada_15 = [{"timestamp": "10:00"}, {"timestamp": "10:15"},
               {"timestamp": "10:30"}, {"timestamp": "10:45"}]
    assert _paso_observado(cada_15) == "15m"

    assert _paso_observado([{"timestamp": "10:00"}]) is None
    assert _paso_observado([{"timestamp": "Precio"}, {"timestamp": ""}]) is None


def test_heatmap_prefiere_la_columna_mas_reciente_que_devuelva_datos():
    """El eje X del heatmap es TIEMPO: una columna fija muestrea un instante.
    Estaba clavado en 0.75 (~6h atrás en vista 24h, confirmado en producción).
    Ahora se barre desde el borde y se registra la columna usada.
    """
    from modules.coinglass.visual_collector import HEATMAP_COLUMNAS

    assert HEATMAP_COLUMNAS[0] > 0.95, "debe intentar primero la columna más reciente"
    assert HEATMAP_COLUMNAS == tuple(sorted(HEATMAP_COLUMNAS, reverse=True)), \
        "las candidatas van de la más reciente a la más antigua"
    assert 0.75 in HEATMAP_COLUMNAS, "el valor histórico queda como último recurso"

    source = (ROOT / "modules/coinglass/visual_collector.py").read_text()
    assert '"x_ratio": heatmap_x' in source, \
        "la columna usada debe quedar registrada en el snapshot"
    assert "_scan_vertical(page, x_ratio=0.75)" not in source, \
        "ya no puede quedar clavado en una columna fija"


def test_grafico_del_libro_tiene_eje_precio_linea_de_precio_y_muros_marcados():
    """Antes era una nube de rectángulos sin eje Y ni referencia temporal: no se
    podía saber a qué precio estaba cada muro ni qué hizo el precio.
    """
    script = (ROOT / "modules/coinglass/public/app.js").read_text()
    html = (ROOT / "modules/coinglass/public/index.html").read_text()
    bloque = script.split("function drawOrderbook()")[1].split("\nfunction ")[0]

    # eje Y con precios y eje X con horas reales de captura
    assert "fmt(p, 0), L - 8, y" in bloque, "el eje Y debe rotular precios"
    assert "captured_at" in bloque and "toLocaleTimeString" in bloque, \
        "el eje X debe mostrar la hora real de las capturas"

    # linea de precio superpuesta sobre los muros
    assert "snapshots.forEach" in bloque and "ctx.stroke()" in bloque
    assert "Number(snap.price)" in bloque, "debe dibujar el precio por captura"

    # los muros mas grandes quedan etiquetados, no solo sombreados
    assert "sort((a, b) => b.usd - a.usd)" in bloque
    assert "compactUsd(m.usd)" in bloque

    # ya no mezcla el heatmap de la API (muerto: 401) con los muros visuales
    assert "orderbook_heatmap" not in bloque, \
        "el heatmap de profundidad de la API esta 401; no debe mezclarse"

    # leyenda al click, con la advertencia de spoofing
    assert "CÓMO SE LEE ESTE GRÁFICO" in html
    assert "spoofing" in html


def test_brujula_mide_alcance_y_no_afirma_direccion():
    """El Radar mostraba un número grande que se leía como veredicto. Ahora la
    lectura principal es una brújula de TERRENO: el largo de cada aguja es la
    probabilidad histórica de alcance, no un pronóstico.
    """
    script = (ROOT / "modules/coinglass/public/app.js").read_text()
    html = (ROOT / "modules/coinglass/public/index.html").read_text()
    css = (ROOT / "modules/coinglass/public/styles.css").read_text()
    bloque = script.split("function drawCompass(")[1].split("\nfunction ")[0]

    # el largo de la aguja viene de la tasa de alcance, no de la distancia
    assert 'alcance_historico?.["4h"]' in bloque
    assert "fraccion * largoMax" in bloque

    # los muros del libro se dibujan como anillos CON su monto
    assert "ellipse(cx" in bloque and "compactUsd(m.amount_usd)" in bloque
    # y con separación en píxeles para que las etiquetas no se pisen
    assert "Math.abs(y - otra) >= 26" in bloque

    # encuadre honesto, visible en el lienzo y en la leyenda
    assert "terreno, no destino" in bloque
    assert "Terreno, no destino" in html
    assert "no un pronóstico" in html
    assert ".chart-frame.brujula" in css

    # el score sin validar deja de ser lo más grande de la pantalla
    assert "font-size: 24px" in css.split(".score b {")[1].split("}")[0]
    assert "sin validar" in script


def test_el_encuadre_del_libro_se_ancla_al_precio_no_a_los_muros():
    """REGRESIÓN: al reescribir el gráfico se perdió el filtro de distancia y dos
    muros lejanos (120k y 125k con BTC en 64k) estiraban el eje Y de 57k a 130k,
    aplastando toda la acción del precio en una banda de píxeles ilegible.
    """
    script = (ROOT / "modules/coinglass/public/app.js").read_text()
    bloque = script.split("function drawOrderbook()")[1].split("\nfunction ")[0]

    # el rango sale del precio, no del min/max de todos los muros
    assert "const pmin = Math.min(...precios)" in bloque
    assert "muros.map((m) => m.p).concat(precios)" not in bloque, \
        "el eje no puede tomar su rango de los muros lejanos"

    # los muros fuera del encuadre no se dibujan ni se etiquetan
    assert "if (m.p < min || m.p > max) continue;" in bloque
    assert "filter((m) => m.p >= min && m.p <= max)" in bloque

    # y las etiquetas de muros se separan en pixeles
    assert "Math.abs(y - otra) < 24" in bloque


def test_mapa_visual_suma_eje_precio_muros_y_alcance():
    """El mapa mostraba barras sin eje Y (solo el precio actual) y sin relación con
    el libro. Ahora trae eje de precios, los muros del libro sobre el MISMO eje
    (para ver confluencia) y la tasa de alcance del clúster más cercano.
    """
    script = (ROOT / "modules/coinglass/public/app.js").read_text()
    html = (ROOT / "modules/coinglass/public/index.html").read_text()
    bloque = script.split("function drawVisualLevels()")[1].split("\nfunction ")[0]

    assert "fmt(p, 0), L - 8, y" in bloque, "el eje Y debe rotular precios"
    assert "nearest_whale_ask" in bloque and "closePath(); ctx.fill()" in bloque, \
        "los muros del libro se dibujan como rombos en el mismo eje de precio"
    assert 'alcance_historico?.["4h"]' in bloque, "falta la tasa de alcance"
    # La banda mayor sigue destacada, ahora con el texto de la escalera. Antes se
    # rotulaba "mayor clúster"; el cambio es deliberado (2026-07-26).
    assert "el mayor" in bloque

    # las columnas de etiquetas no pueden compartir la misma x
    assert "const L = 78, R = 232" in bloque
    # el alcance ya no es un caso especial de los dos más cercanos: es una columna
    # propia con su encabezado, y CADA banda escribe en ella
    assert "colProb" in bloque and "SE ALCANZA EN 4h" in bloque

    assert "confluencia" in html, "la leyenda debe explicar la confluencia"


def test_flujo_de_muros_distingue_consumido_de_retirado():
    """El gráfico pasa de "foto de muros" a "flujo": comparando capturas marca los
    que aparecen, los que el precio se comió y los que se retiraron sin ser
    tocados — esa última es la firma del spoofing.
    """
    script = (ROOT / "modules/coinglass/public/app.js").read_text()
    html = (ROOT / "modules/coinglass/public/index.html").read_text()
    bloque = script.split("function flujoDeMuros(")[1].split("\nfunction ")[0]

    # el matcheo usa un paso FIJO derivado de una referencia, no del propio precio
    assert "referencia" in bloque and "* 0.0005" in bloque
    assert "Math.round(precio / paso)" in bloque
    assert "precio / (precio * TOL)" not in script, \
        "ese divisor es 1/TOL, constante: metia todos los muros en un bucket"

    # consumido vs retirado se decide por si el precio recorrio el nivel
    assert "m.p >= lo && m.p <= hi" in bloque
    assert '"consumido" : "retirado"' in bloque

    # y la inferencia se declara como tal en la leyenda
    assert "es una inferencia" in html
    assert "spoofing" in html


def test_el_libro_tiene_zoom_al_precio_de_ahora():
    """Sin acotar la ventana, dos muros lejanos aplastan el 'ahora'."""
    script = (ROOT / "modules/coinglass/public/app.js").read_text()
    html = (ROOT / "modules/coinglass/public/index.html").read_text()

    assert 'data-zoom="0.5"' in html and 'data-zoom="0"' in html
    assert "let bookZoom" in script
    assert "bookZoom = Number(button.dataset.zoom)" in script
    # con zoom, la ventana se centra en el precio de la ultima captura
    assert "ahora * (1 - bookZoom / 100)" in script
    # y el recorrido del precio nunca queda fuera del marco
    assert "min = Math.min(min, Math.min(...precios))" in script


def test_lo_que_se_cae_de_la_ventana_se_archiva_en_vez_de_perderse(tmp_path):
    """2.016 capturas cada 5 min son EXACTAMENTE 7 días: todo lo anterior se perdía.

    El estudio del imán con niveles REALES no es backtesteable —sólo se puede
    registrar hacia adelante— así que cada día sin archivo destruía un día de datos
    irrecuperable. Acá se fija que lo descartado quede en disco.
    """
    from modules.coinglass import module as mod

    archivo = tmp_path / "archivo.jsonl"
    viejas = [{"captured_at": f"2026-07-{d:02d}T00:00:00+00:00", "price": 60_000 + d}
              for d in range(1, 4)]

    res = mod._archivar_descartadas(str(archivo), viejas)
    assert res["escritas"] == 3 and res["error"] is None

    lineas = archivo.read_text(encoding="utf-8").strip().split("\n")
    assert len(lineas) == 3
    assert json.loads(lineas[0])["price"] == 60_001

    # es APPEND: una segunda tanda no pisa la primera
    mod._archivar_descartadas(str(archivo), [{"captured_at": "x", "price": 1}])
    assert len(archivo.read_text(encoding="utf-8").strip().split("\n")) == 4


def test_el_archivo_deja_de_escribir_en_vez_de_rotar_en_silencio(tmp_path, monkeypatch):
    """Perder datos calladamente es justo el problema que este archivo resuelve, así
    que al llegar al tope se detiene y lo dice."""
    from modules.coinglass import module as mod

    archivo = tmp_path / "archivo.jsonl"
    archivo.write_text("x" * 500, encoding="utf-8")
    monkeypatch.setattr(mod, "MAX_ARCHIVE_BYTES", 100)

    res = mod._archivar_descartadas(str(archivo), [{"captured_at": "a"}])
    assert res["lleno"] is True and res["escritas"] == 0
    assert archivo.read_text(encoding="utf-8") == "x" * 500   # no lo toca

    estado = mod._estado_del_archivo(str(archivo))
    assert estado["lleno"] is True


def test_archivar_no_puede_romper_la_ingesta(tmp_path):
    """Ya pasó una vez: un guard mío fallando cerrado le costó un ciclo de captura al
    colector. Un error de disco acá se reporta, no propaga."""
    from modules.coinglass import module as mod

    ruta_imposible = str(tmp_path / "no" / "existe" / "a.jsonl")
    res = mod._archivar_descartadas(ruta_imposible, [{"captured_at": "a"}])
    assert res["error"] is not None
    assert res["escritas"] == 0


def test_el_estado_expone_si_el_archivo_esta_creciendo(tmp_path):
    """Un archivo que falla en silencio es peor que no tenerlo: da la sensación de
    estar guardando. Por eso el estado lo publica."""
    from modules.coinglass import module as mod

    archivo = tmp_path / "archivo.jsonl"
    assert mod._estado_del_archivo(str(archivo))["existe"] is False

    mod._archivar_descartadas(str(archivo), [{"captured_at": "a"}, {"captured_at": "b"}])
    estado = mod._estado_del_archivo(str(archivo))
    assert estado["existe"] is True and estado["bytes"] > 0
    assert "ultima_escritura" in estado
    # NO debe contar lineas: leeria cientos de MB en cada carga de la pagina
    assert "capturas" not in estado

    fuente = (ROOT / "modules/coinglass/module.py").read_text()
    assert 'data["visual_book_archive"]' in fuente, \
        "el estado debe publicarlo o nadie se entera si deja de crecer"


def test_el_archivo_no_cruza_research_con_ejecucion():
    """La separacion research<->ejecucion se mantiene: el join con los setups se hace
    OFFLINE por captured_at, sin que trading importe coinglass ni al reves."""
    cg = (ROOT / "modules/coinglass/module.py").read_text()
    assert "modules.trading" not in cg and "setups_store" not in cg


def test_el_colector_guarda_copia_local_append_only(tmp_path):
    """Hasta ahora el historial vivía SOLO en la instancia remota, y de un lado que
    el token no puede leer (sirve para escribir, no para leer). La copia local
    resuelve el acceso sin abrir ninguna vía de lectura nueva en la web.
    """
    from modules.coinglass.visual_collector import archivar_local

    destino = tmp_path / "sub" / "archivo.jsonl"
    assert archivar_local(snapshot(), destino) is None      # crea el directorio
    assert archivar_local(snapshot(), destino) is None      # y es APPEND

    lineas = destino.read_text(encoding="utf-8").strip().split("\n")
    assert len(lineas) == 2
    fila = json.loads(lineas[0])
    assert fila["price"] == 64_238
    assert sorted(fila) == ["asks", "bids", "captured_at", "price"]
    # mismos muros que el snapshot, separados por lado
    assert [64_750, 1_630_000] in fila["asks"]
    assert [63_750, 1_800_000] in fila["bids"]
    assert len(fila["bids"]) == 2 and len(fila["asks"]) == 2


def test_la_copia_local_nunca_puede_costar_un_ciclo_de_captura(tmp_path):
    """Ya pasó: un guard mío fallando cerrado le costó una recolección entera al
    colector. Un problema de disco se reporta y se sigue."""
    from modules.coinglass.visual_collector import archivar_local

    # un archivo donde un directorio ocupa el lugar del fichero
    ocupado = tmp_path / "ocupado.jsonl"
    ocupado.mkdir()
    assert archivar_local(snapshot(), ocupado) is not None   # devuelve el error

    # y un snapshot corrupto tampoco levanta
    roto = {"captured_at": "x", "whale_orders": {"rows": [{"side": "bid"}]}}
    assert archivar_local(roto, tmp_path / "b.jsonl") is not None


def test_el_archivo_local_es_opcional_y_va_por_env():
    """Debe poder desplegarse sin cambiar la unidad de systemd."""
    src = (ROOT / "modules/coinglass/visual_collector.py").read_text()
    assert "--archivo-local" in src
    assert "NEXUS_BOOK_ARCHIVE" in src
    assert "aviso_archivo" in src, "un fallo silencioso no serviria de nada"


def test_el_muro_dominante_no_se_recorta_por_el_radio_de_5pct():
    """Hallazgo de la auditoría 2026-07-26, medido en producción: los CUATRO muros
    mayores del libro caían fuera del radio de ±5% y el mayor —78,7M, 43x la
    mediana— quedaba excluido por 6 dólares (−5,01%). La brújula, el mapa y la
    lectura del momento mostraban muros menores mientras ignoraban la pared real.

    `strongest_*` conserva el radio (mide presión cerca del precio, y ahí el radio
    es correcto). `dominant_*` no lo lleva.
    """
    snap = snapshot()
    snap["whale_orders"]["rows"].append({
        "side": "bid", "price": 61_300, "amount_usd": 78_600_000,
        "duration": "2D", "market": "S", "exchange": "binance",
    })
    indicator = build_visual_indicator(snap, now=NOW)
    niveles = indicator["levels"]

    # el de 61.300 esta a -4.6% del precio de 64.238... se fuerza mas lejos
    assert niveles["dominant_whale_bid"]["amount_usd"] == 78_600_000

    lejano = snapshot()
    lejano["whale_orders"]["rows"].append({
        "side": "bid", "price": 55_000, "amount_usd": 99_000_000,
        "duration": "3D", "market": "S", "exchange": "binance",
    })
    niveles = build_visual_indicator(lejano, now=NOW)["levels"]
    assert niveles["dominant_whale_bid"]["amount_usd"] == 99_000_000, \
        "el muro mas grande quedo fuera por el radio: es justo el bug corregido"
    # y el de radio corto NO lo toma, porque mide otra cosa
    assert niveles["strongest_whale_bid"]["amount_usd"] != 99_000_000
    assert niveles["dominant_whale_bid"]["distance_pct"] < -5


def test_los_marcadores_de_flujo_no_dependen_del_muro_mas_grande():
    """El corte era `maxUsd * 0.55`. Con el bid persistente de 78,7M fijando el
    maximo, el corte quedaba en 43M contra una MEDIANA de muro de 1,8M: 1 de 41
    muros podia marcar. Verificado en produccion: 0 de 14 eventos se dibujaban.
    Un ranking relativo (top-N) no depende de la escala del mayor.
    """
    script = (ROOT / "modules/coinglass/public/app.js").read_text()
    bloque = script.split("const marcables")[1].split(";")[0]
    assert "maxUsd" not in bloque, "volvio el umbral atado al muro mas grande"
    assert ".slice(0, 40)" in bloque, "debe haber tope de marcadores"
    assert "sort((a, b) => b.usd - a.usd)" in bloque


def test_el_flujo_acumula_los_muros_que_comparten_bucket():
    """Con `Map.set` el segundo muro del bucket pisaba al primero: su monto
    desaparecia del diff y, si uno se retiraba, el bucket seguia ocupado y no
    habia evento."""
    script = (ROOT / "modules/coinglass/public/app.js").read_text()
    bloque = script.split("function flujoDeMuros(")[1].split("\nfunction ")[0]
    assert "previo.usd += usd" in bloque, "los muros del mismo bucket deben sumarse"
    assert "const indexar" in bloque


def test_la_dedup_de_etiquetas_es_lineal():
    """Era `findIndex` dentro de `filter`: ~11.500 muros -> ~130M comparaciones en
    CADA redraw (zoom, resize). En movil congelaba la pestana."""
    script = (ROOT / "modules/coinglass/public/app.js").read_text()
    bloque = script.split("const vistos = new Set()")[1].split("// --- eje X")[0]
    assert "vistos.has(k)" in bloque and "vistos.add(k)" in bloque
    assert "findIndex" not in bloque


def test_el_intervalo_del_libro_se_mide_no_se_cablea():
    """Mismo defecto que el "4h" cableado de la pestana Flujo, que resulto ser 1h."""
    script = (ROOT / "modules/coinglass/public/app.js").read_text()
    assert "function intervaloMedido" in script
    assert "intervaloMedido(snapshots)" in script
    assert "· cada 5 min ·" not in script, "el intervalo volvio a estar cableado"


def test_la_brujula_usa_la_misma_convencion_de_color_que_el_resto():
    """Arriba = rojo (asks/resistencia), abajo = verde (bids/soporte), igual que el
    libro y el mapa visual. Estaba invertido solo en la brujula, asi que el mismo
    nivel se pintaba de un color en una pestana y del opuesto en otra."""
    script = (ROOT / "modules/coinglass/public/app.js").read_text()
    bloque = script.split("// agujas: LARGO = probabilidad de alcance")[1][:700]
    assert '[arriba, -1, "ARRIBA", "#ef6370"]' in bloque
    assert '[abajo, 1, "ABAJO", "#24c88a"]' in bloque


def test_la_ui_muestra_la_salud_del_archivo_historico():
    """El estado publica `visual_book_archive` desde el 2026-07-25 para que se note
    si deja de crecer, pero la UI no lo renderizaba: el modo de falla exacto que
    ese dato venia a evitar."""
    script = (ROOT / "modules/coinglass/public/app.js").read_text()
    html = (ROOT / "modules/coinglass/public/index.html").read_text()
    assert "state.visual_book_archive" in script
    assert "ultima_escritura" in script and "ARCHIVO LLENO" in script
    assert 'id="ahora-fresco"' in html


def test_la_lectura_del_momento_junta_los_cuatro_datos():
    """Estaban repartidos en cuatro pestanas: iman en Radar, muro y flujo en Libro,
    frescura en Mapa visual."""
    html = (ROOT / "modules/coinglass/public/index.html").read_text()
    script = (ROOT / "modules/coinglass/public/app.js").read_text()
    for campo in ("ahora-iman", "ahora-muro", "ahora-flujo", "ahora-fresco"):
        assert f'id="{campo}"' in html
        assert f'id="{campo}-meta"' in html
    assert "function renderAhora" in script
    assert "renderAhora();" in script
    # la edad del muro dominante: un muro de dias no es lo mismo que uno de 5 min
    assert "function edadDelMuro" in script


def test_la_pestana_mapa_visual_se_fusiono_con_el_radar():
    """Las dos mostraban el MISMO score y la MISMA descomposición de componentes, y
    los niveles cercanos aparecían en tres lugares a la vez (strip, brújula y tabla
    de alcance). Es el "mucha información" que marcó Hugo.
    """
    html = (ROOT / "modules/coinglass/public/index.html").read_text()
    script = (ROOT / "modules/coinglass/public/app.js").read_text()

    assert 'data-tab="visual"' not in html, "la pestaña duplicada sigue ahí"
    assert 'id="view-visual"' not in html
    # lo único que NO estaba duplicado vive ahora dentro del Radar
    radar = html.split('id="view-model"')[1]
    assert 'id="visual-level-chart"' in radar
    assert 'id="visual-coverage"' in radar
    # y el score y los componentes quedan UNA sola vez
    assert html.count('id="visual-score"') == 0
    assert html.count('id="visual-components"') == 0
    assert html.count('id="model-components"') == 1
    assert html.count('id="pressure-score"') == 1
    assert 'if (button.dataset.tab === "model") { renderVisual(); renderModel(); }' in script


def test_ningun_render_apunta_a_un_elemento_que_ya_no_existe():
    """Candado de la fusión: borrar bloques del HTML deja `$()` devolviendo null y
    la pestaña entera revienta en silencio."""
    import re
    script = (ROOT / "modules/coinglass/public/app.js").read_text()
    html = (ROOT / "modules/coinglass/public/index.html").read_text()
    usados = set(re.findall(r'\$\("([a-z0-9-]+)"\)', script))
    usados |= set(re.findall(r'message\("([a-z0-9-]+)"', script))
    existen = set(re.findall(r'id="([a-z0-9-]+)"', html))
    faltan = sorted(usados - existen)
    assert not faltan, f"app.js referencia ids inexistentes: {faltan}"


def test_la_escalera_muestra_que_hay_DESPUES_del_primer_cluster():
    """El mapa mostraba solo el clúster más cercano de cada lado: si el precio lo
    rompía, no había forma de saber qué venía después. La escalera devuelve la
    secuencia hacia arriba y hacia abajo, cada peldaño con su tasa de alcance.
    """
    indicator = build_visual_indicator(snapshot(), now=NOW)
    niveles = indicator["levels"]
    arriba = niveles["escalera_arriba"]
    abajo = niveles["escalera_abajo"]

    assert len(arriba) >= 2 and len(abajo) >= 2, "una escalera de un peldaño no es escalera"
    precio = indicator["price"]

    # ordenadas de la más cercana a la más lejana, cada una del lado correcto
    for lado, esperado_arriba in ((arriba, True), (abajo, False)):
        distancias = [abs(b["price"] - precio) for b in lado]
        assert distancias == sorted(distancias), "los peldaños no van de cerca a lejos"
        for b in lado:
            assert (b["price"] > precio) is esperado_arriba
            assert b["intensity_usd"] > 0
            assert b["niveles"] >= 1

    # el primer peldaño de arriba coincide con el clúster más cercano de siempre
    assert abs(arriba[0]["price"] - niveles["nearest_above"]["price"]) < precio * 0.01


def test_la_probabilidad_de_alcance_baja_al_alejarse():
    """Es la propiedad que hace útil la escalera: cada peldaño más lejos se alcanza
    menos seguido. Si subiera, la tabla de tasas estaría mal construida."""
    niveles = build_visual_indicator(snapshot(), now=NOW)["levels"]
    for lado in (niveles["escalera_arriba"], niveles["escalera_abajo"]):
        tasas = [(b.get("alcance_historico") or {}).get("4h") for b in lado]
        tasas = [t for t in tasas if t is not None]
        if len(tasas) >= 2:
            assert tasas == sorted(tasas, reverse=True), \
                f"la tasa de alcance sube al alejarse: {tasas}"


def test_el_corte_de_la_escalera_es_RELATIVO_no_un_umbral_en_dolares():
    """Medido en producción: con el corte fijo de 5M sobrevivían 7 niveles de 114,
    porque el MÁXIMO de esa captura era 6,69M y la mediana 1,09M. Un umbral
    absoluto sobre un dato que cambia de escala deja la vista vacía los días
    tranquilos. Acá se escala todo el heatmap /100 y la escalera debe seguir viva.
    """
    chico = snapshot()
    for nivel in chico["liquidation_heatmap"]["levels"]:
        nivel["intensity_usd"] = nivel["intensity_usd"] / 100      # todo bajo 1M
    niveles = build_visual_indicator(chico, now=NOW)["levels"]
    assert niveles["escalera_arriba"], "la escalera se vacio al bajar la escala"
    assert niveles["escalera_abajo"]

    fuente = (ROOT / "modules/coinglass/visual.py").read_text()
    bloque = fuente.split("def _escalera(")[1].split("\ndef ")[0]
    assert "montos[len(montos) // 2]" in bloque, "el corte debe ser la mediana"
    assert "5_000_000" not in bloque and "5e6" not in bloque


def test_la_escalera_agrupa_niveles_contiguos_en_bandas():
    """El heatmap trae ~114 niveles y muchos son vecinos: listarlos sueltos seria
    ruido. Dos niveles a 0,05% uno del otro son UNA banda, con los montos sumados."""
    pegados = snapshot()
    pegados["liquidation_heatmap"]["levels"] = [
        {"price": 64_500, "intensity_usd": 6_000_000, "timestamp": "14:50"},
        {"price": 64_520, "intensity_usd": 4_000_000, "timestamp": "14:50"},
        {"price": 66_000, "intensity_usd": 5_000_000, "timestamp": "14:50"},
        {"price": 63_000, "intensity_usd": 5_000_000, "timestamp": "14:50"},
        {"price": 62_000, "intensity_usd": 5_000_000, "timestamp": "14:50"},
    ]
    arriba = build_visual_indicator(pegados, now=NOW)["levels"]["escalera_arriba"]
    banda = arriba[0]
    assert banda["niveles"] == 2, "los dos niveles pegados debian fundirse"
    assert banda["intensity_usd"] == 10_000_000, "los montos deben sumarse"
    assert 64_500 <= banda["price"] <= 64_520


def test_el_grafico_y_la_tabla_leen_la_MISMA_fuente():
    """Si el gráfico filtra por un umbral y la tabla por otro, cuentan historias
    distintas del mismo momento."""
    script = (ROOT / "modules/coinglass/public/app.js").read_text()
    dibujo = script.split("function drawVisualLevels()")[1].split("\nfunction ")[0]
    assert "escalera_arriba" in dibujo and "escalera_abajo" in dibujo
    # se busca la EXPRESION del filtro, no la mención en un comentario
    assert "intensity_usd) >= 5e6" not in dibujo, "volvio el umbral absoluto al grafico"
    tabla = script.split("function renderAlcance(")[1].split("\nfunction ")[0]
    assert "escalera_arriba" in tabla and "escalera_abajo" in tabla
    assert "fila-precio" in tabla, "falta la fila del precio actual al medio"


def test_los_muros_no_mandan_en_el_encuadre_del_grafico():
    """Los muros ballena viven a ±5% mientras las bandas caen dentro de ±2%: si el
    eje los incluye, TODA la escalera se aplasta en una franja del medio. Es el
    mismo error que ya habíamos corregido en el gráfico del libro, cometido otra
    vez acá. Los muros fuera de rango se fijan al borde y se marcan con flecha.
    """
    script = (ROOT / "modules/coinglass/public/app.js").read_text()
    dibujo = script.split("function drawVisualLevels()")[1].split("\nfunction ")[0]
    encuadre = dibujo.split("const todos =")[1].split("const fuerte")[0]
    assert "muros" not in encuadre, "los muros volvieron a definir el eje"
    # y siguen dibujándose, fijados al borde
    assert "p > max ? 1 : p < min ? -1 : 0" in dibujo
    assert "↑" in dibujo and "↓" in dibujo


def test_cada_banda_lleva_su_probabilidad_en_el_grafico():
    """Era el pedido de Hugo: que el gráfico -no solo la tabla- muestre los niveles
    con sus porcentajes. Antes solo dos niveles tenían su tasa dibujada."""
    script = (ROOT / "modules/coinglass/public/app.js").read_text()
    dibujo = script.split("function drawVisualLevels()")[1].split("\nfunction ")[0]
    assert "SE ALCANZA EN 4h" in dibujo, "falta el encabezado de la columna"
    # la barrita de probabilidad se dibuja dentro del bucle de bandas, no aparte
    bucle = dibujo.split("for (const row of")[1].split("// encabezado")[0]
    assert 'alcance_historico?.["4h"]' in bucle
    assert "anchoProb" in bucle and "distance_pct" in bucle


def test_los_muros_del_borde_del_umbral_no_cuentan_como_retirados():
    """CoinGlass solo lista muros sobre US$1M, así que los que rondan esa cifra
    cruzan el umbral de ida y vuelta y entran y salen de la captura sin que nadie los
    ponga ni los quite. Medido en producción: el 48% de los eventos eran muros de
    1,00M a 1,10M, con precios que hacían retirado->nuevo->retirado->nuevo. Al
    descartarlos, el conteo pasó de 22 nuevos / 22 retirados a 10 / 12.

    Contarlos inflaba justo el número que se presenta como firma de spoofing.
    """
    script = (ROOT / "modules/coinglass/public/app.js").read_text()
    bloque = script.split("function flujoDeMuros(")[1].split("\nfunction ")[0]

    assert "const piso = Math.min" in bloque, "falta el piso del umbral"
    assert "enElBorde" in bloque
    # se descartan en AMBAS direcciones: un muro del borde no es nuevo ni retirado
    assert bloque.count("if (enElBorde(m.usd)) { borde++; continue; }") == 2
    assert "borde," in bloque and "piso }" in bloque, "el conteo debe salir de la funcion"

    # y el pie declara lo descartado: un conteo que esconde su filtro miente
    assert "eventos descartados por rondar el umbral" in script
    html = (ROOT / "modules/coinglass/public/index.html").read_text()
    assert "Umbral de CoinGlass" in html
    assert "48%" in html, "la magnitud medida debe quedar escrita"


def test_los_graficos_tienen_leyenda_visible_sin_abrir_nada():
    """Un rombo celeste o un círculo ámbar no se adivinan. La explicación larga sigue
    en el desplegable, pero los símbolos tienen que identificarse de inmediato."""
    html = (ROOT / "modules/coinglass/public/index.html").read_text()
    assert html.count('class="leyenda-inline"') == 2, \
        "leyenda visible en el libro Y en la escalera"

    libro = html.split('id="orderbook-chart"')[1].split("</ul>")[0]
    for simbolo in ("◇", "✕", "○"):
        assert simbolo in libro, f"falta el simbolo {simbolo} en la leyenda del libro"
    assert "retirado" in libro and "consumido" in libro and "nuevo" in libro
    assert "g-bid" in libro and "g-ask" in libro, "faltan las muestras de color"

    escalera = html.split('id="visual-level-chart"')[1].split("</ul>")[0]
    assert "◆" in escalera and "↑↓" in escalera
    assert "probabilidad" in escalera

    css = (ROOT / "modules/coinglass/public/styles.css").read_text()
    assert ".leyenda-inline" in css and "g-bid" in css


def test_el_libro_muestra_la_distancia_de_los_muros():
    """Sin la distancia hay que restar de cabeza para saber si un muro está cerca.
    La escalera ya la mostraba; el libro no."""
    script = (ROOT / "modules/coinglass/public/app.js").read_text()
    dibujo = script.split("function drawOrderbook()")[1].split("\nfunction ")[0]
    assert 'signed((m.p / ahora - 1) * 100, "%")' in dibujo


def test_el_iman_mas_cercano_no_se_elige_con_umbral_absoluto():
    """El artefacto del umbral de US$1M en los MUROS hizo preguntar si el heatmap
    tenía el mismo problema. Tiene uno del mismo tipo, por otro mecanismo: nuestro
    propio `minimum_usd=5_000_000` en `_nearest`.

    Medido en producción (2026-07-26, máximo de la captura 6,98M): hacia arriba se
    saltaba un clúster de 4,89M a +0,19% y reportaba +0,34%; hacia abajo se saltaba
    4,43M a −0,86% y reportaba −1,16%, un 35% más lejos. Esa distancia alimenta la
    probabilidad de alcance, las agujas de la brújula y el veredicto: la tasa a 4h
    hacia abajo pasó de ~10% a 16% al corregirlo.
    """
    fuente = (ROOT / "modules/coinglass/visual.py").read_text()
    bloque = fuente.split('"nearest_above"')[1].split('"strongest_above"')[0]
    assert "escalera_arriba[0]" in bloque and "escalera_abajo[0]" in bloque
    # `_nearest` se eliminó: quedó sin uso al reemplazarlo por la escalera
    assert "def _nearest(" not in fuente, "volvio la seleccion por umbral absoluto"

    # Un clúster sustancial cerca del precio no puede quedar fuera por ser < 5M.
    # El escenario usa varios niveles por lado, como el heatmap real (~58 por lado):
    # con solo tres, la mediana descarta al más cercano y eso NO es el bug que este
    # test persigue —lo verifiqué y era mi escenario el irreal, no el código—.
    snap = snapshot()
    snap["liquidation_heatmap"]["levels"] = [
        {"price": 64_300, "intensity_usd": 4_500_000, "timestamp": "14:50"},
        {"price": 64_600, "intensity_usd": 4_600_000, "timestamp": "14:50"},
        {"price": 64_900, "intensity_usd": 1_000_000, "timestamp": "14:50"},
        {"price": 65_400, "intensity_usd": 900_000, "timestamp": "14:50"},
        {"price": 64_100, "intensity_usd": 4_400_000, "timestamp": "14:50"},
        {"price": 63_800, "intensity_usd": 4_300_000, "timestamp": "14:50"},
        {"price": 63_500, "intensity_usd": 800_000, "timestamp": "14:50"},
        {"price": 63_000, "intensity_usd": 700_000, "timestamp": "14:50"},
    ]
    niveles = build_visual_indicator(snap, now=NOW)["levels"]
    assert niveles["nearest_above"]["price"] == 64_300, \
        "el cluster de 4,5M mas cercano quedo fuera por el umbral"
    assert niveles["nearest_below"]["price"] == 64_100


def test_los_niveles_en_cero_no_pueden_ser_el_iman_mas_cercano():
    """CoinGlass muestra "0.00M" para lo despreciable y el parser devuelve 0. Medido
    en producción: 5 de 114 niveles venían en 0 y el MÁS CERCANO al precio era uno de
    ellos, así que sin filtrarlos "el imán más cercano" podía ser un nivel sin
    liquidez. Lo descubrí al intentar forzar que el más cercano entrara siempre."""
    snap = snapshot()
    snap["liquidation_heatmap"]["levels"] = [
        {"price": 64_250, "intensity_usd": 0, "timestamp": "14:50"},
        {"price": 64_500, "intensity_usd": 6_000_000, "timestamp": "14:50"},
        {"price": 64_800, "intensity_usd": 5_000_000, "timestamp": "14:50"},
        {"price": 64_230, "intensity_usd": 0, "timestamp": "14:50"},
        {"price": 63_900, "intensity_usd": 6_500_000, "timestamp": "14:50"},
        {"price": 63_600, "intensity_usd": 5_500_000, "timestamp": "14:50"},
    ]
    niveles = build_visual_indicator(snap, now=NOW)["levels"]
    assert niveles["nearest_above"]["price"] == 64_500
    assert niveles["nearest_below"]["price"] == 63_900
    for lado in ("escalera_arriba", "escalera_abajo"):
        assert all(b["intensity_usd"] > 0 for b in niveles[lado])


def test_el_bot_virtual_lee_los_mismos_niveles_que_la_ui():
    """`shadow_plan` usa nearest_above/below como objetivo y stop. Si la UI y el bot
    virtual leyeran niveles distintos, sus resultados no serian comparables con lo
    que se ve en pantalla."""
    indicator = build_visual_indicator(snapshot(), now=NOW)
    plan = shadow_plan(indicator)
    niveles = indicator["levels"]
    if plan["action"] == "virtual_entry":
        objetivos = {niveles["nearest_above"]["price"], niveles["nearest_below"]["price"]}
        assert plan["target"] in objetivos and plan["stop"] in objetivos
