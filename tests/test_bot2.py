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
