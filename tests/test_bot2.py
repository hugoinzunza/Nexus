import json
from pathlib import Path

from core.module_base import ModuleContext
from modules.bot2 import strategy
from modules.bot2.module import Bot2Module
from modules.inteligencia import fases


ROOT = Path(__file__).resolve().parents[1]


def _candles(n=90):
    rows = []
    price = 100.0
    for i in range(n):
        # Ondas deterministas para producir swings sin mirar datos futuros.
        change = (1.5 if (i // 8) % 2 == 0 else -1.0)
        close = price + change
        rows.append({"t": 1_700_000_000_000 + i * 3_600_000,
                     "o": price, "h": max(price, close) + 0.4,
                     "l": min(price, close) - 0.4, "c": close, "v": 1})
        price = close
    return rows


def test_fases_no_cambian_al_agregar_futuro():
    completo = _candles(90)
    base = completo[:70]
    antes = fases.ciclos_confirmados(base, "1h")
    despues = fases.ciclos_confirmados(completo, "1h")
    ids = {x["id"]: x for x in despues}
    for ciclo in antes:
        assert ids[ciclo["id"]]["available_at"] == ciclo["available_at"]
        assert ids[ciclo["id"]]["phase_i"] == ciclo["phase_i"]
        assert ids[ciclo["id"]]["phase_ii"] == ciclo["phase_ii"]


def test_motor_es_research_y_sin_ejecucion():
    result = strategy.analyze(_candles(140), "1h", "structure_break")
    assert result["research_only"] is True
    assert result["execution_enabled"] is False
    assert result["rules"]["min_net_rr"] == 2.0
    assert isinstance(result["watchlist"], list)
    for watch in result["watchlist"]:
        assert watch["as_of"] == _candles(140)[-1]["t"]
        assert "eligible_next_open" in watch


def test_modulo_expone_btc_eth_y_variantes():
    context = ModuleContext("bot2", str(ROOT / "modules" / "bot2"), {
        "pairs": ["BTCUSDT", "ETHUSDT"], "timeframes": ["1h", "4h", "1d"],
    }, lambda _msg: None)
    module = Bot2Module(context)
    status, _, body = module.api("state", {}, None)
    data = json.loads(body)
    assert status == 200
    assert data["pairs"] == ["BTCUSDT", "ETHUSDT"]
    assert data["variants"] == list(strategy.VARIANTS)
    assert data["execution_enabled"] is False


def test_bot2_no_importa_ejecucion_ni_credenciales():
    source = (ROOT / "modules" / "bot2" / "module.py").read_text()
    strategy_source = (ROOT / "modules" / "bot2" / "strategy.py").read_text()
    forbidden = ("modules.bot", "binance_client", "BINANCE_API", "create_order")
    for token in forbidden:
        assert token not in source
        assert token not in strategy_source


def test_vista_declara_research_y_menu_visible():
    html = (ROOT / "modules" / "bot2" / "public" / "index.html").read_text()
    shell = (ROOT / "static" / "nexux-shell.js").read_text()
    assert "RESEARCH ONLY" in html
    assert "sin órdenes reales" in html
    assert "Entradas en vigilancia" in html
    assert "/m/bot2/" in shell
    assert '"bot2"' in (ROOT / "config" / "nexus.json").read_text()


def test_atr_es_media_simple_de_true_range():
    velas = [{"t": i, "o": 100, "h": 110, "l": 90, "c": 100} for i in range(20)]
    valores = strategy.atr_values(velas)
    assert valores[12] is None          # sin ATR antes de 14 velas
    assert valores[14] == 20 and valores[19] == 20
    con_gap = [{"t": i, "o": 100, "h": 100, "l": 100, "c": 100} for i in range(20)]
    con_gap[5] = {"t": 5, "o": 100, "h": 130, "l": 100, "c": 100}
    assert abs(strategy.atr_values(con_gap)[14] - 30 / 14) < 1e-9  # |h - prev_close|


def test_bucket_semanal_ancla_en_lunes_utc():
    import datetime
    UTC = datetime.timezone.utc
    ms = lambda *a: int(datetime.datetime(*a, tzinfo=UTC).timestamp() * 1000)
    lunes = ms(2026, 8, 10)
    assert strategy._bucket_t(ms(2026, 8, 12, 15), "1w") == lunes
    assert strategy._bucket_t(lunes, "1w") == lunes
    assert strategy._bucket_t(ms(2026, 8, 9, 23), "1w") == lunes - 604_800_000


def test_simulacion_convierte_costos_a_r_y_es_conservadora_intrabar():
    base = {"side": "long", "entry": 100.0, "stop": 98.0, "target": 106.0,
            "cost_r": 0.06, "net_rr": 2.94, "entry_idx": 1}
    velas = [{"t": 0, "o": 100, "h": 100, "l": 100, "c": 100},
             {"t": 1, "o": 100, "h": 101, "l": 99, "c": 100},
             {"t": 2, "o": 100, "h": 107, "l": 99, "c": 106}]
    gana = strategy._simulate(velas, dict(base))
    assert gana["status"] == "win" and abs(gana["result_r"] - 2.94) < 1e-9
    ambas = [velas[0], velas[1], {"t": 2, "o": 100, "h": 107, "l": 97, "c": 106}]
    pierde = strategy._simulate(ambas, dict(base))
    # SL y TP en la misma vela: cuenta SL, y la perdida carga el costo completo
    assert pierde["status"] == "loss" and abs(pierde["result_r"] - (-1.06)) < 1e-9


def test_linea_de_tendencia_interpola_y_no_divide_por_cero():
    a, b = {"idx": 10, "price": 100.0}, {"idx": 20, "price": 110.0}
    assert strategy._line_value(a, b, 15) == 105.0
    assert strategy._line_value(a, b, 25) == 115.0
    mismo = {"idx": 5, "price": 100.0}
    assert strategy._line_value(mismo, {"idx": 5, "price": 103.0}, 9) == 103.0
