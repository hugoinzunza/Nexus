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
    assert "Mapa visual" in html
    assert "SESIÓN AUTORIZADA" in html
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
    snap["liquidation_heatmap"]["levels"] = [
        {**nivel, "timestamp": "2026-07-24 19:45"}
        for nivel in snap["liquidation_heatmap"]["levels"]
    ]
    snap["liquidation_heatmap"]["levels"][0]["timestamp"] = "Precio"

    indicator = build_visual_indicator(snap, now=NOW)
    lag = indicator["coverage"]["heatmap_lag_seconds"]

    # captura 2026-07-24 18:00 UTC vs tooltip del mismo día 19:45 -> -6300 s
    assert lag == -6_300
    assert indicator["stale_heatmap"] is False   # negativo no es "atrasado"

    # Y el caso real observado: captura del día siguiente a la 01:09
    snap["captured_at"] = "2026-07-25T01:09:15+00:00"
    tardio = build_visual_indicator(snap, now=datetime(2026, 7, 25, 1, 10, tzinfo=timezone.utc))
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
    assert "mayor clúster" in bloque

    # las tres columnas de etiquetas no pueden compartir la misma x
    assert "const L = 78, R = 232" in bloque
    assert "width - 10, y + dy" in bloque, "el alcance va al borde, desplazado"

    assert "confluencia" in html, "la leyenda debe explicar la confluencia"
