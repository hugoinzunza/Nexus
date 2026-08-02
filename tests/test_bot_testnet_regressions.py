from pathlib import Path

from modules.bot.bot_store import BotStore
from modules.bot.executor import BotExecutor, ordenar_resuelto


class _AvgZeroClient:
    def __init__(self, *, cum_quote=0.0):
        self.cum_quote = cum_quote
        self.queries = 0

    def market_order(self, *_args, **_kwargs):
        return {
            "status": "FILLED",
            "executedQty": "2",
            "avgPrice": "0",
            "cumQuote": str(self.cum_quote),
        }

    def get_order(self, _symbol, _client_id):
        self.queries += 1
        return {
            "status": "FILLED",
            "executed_qty": 2.0,
            "avg_price": 101.5,
        }


def test_avg_price_cero_usa_cum_quote_antes_del_mark():
    cli = _AvgZeroClient(cum_quote=202.0)

    result = ordenar_resuelto(cli, "BTCUSDT", "BUY", 2, "fill-1")

    assert result["avg_price"] == 101.0
    assert cli.queries == 0


def test_avg_price_cero_consulta_la_orden_confirmada_si_no_hay_quote():
    cli = _AvgZeroClient()

    result = ordenar_resuelto(cli, "BTCUSDT", "BUY", 2, "fill-2")

    assert result["avg_price"] == 101.5
    assert cli.queries == 1


def test_cierre_cancela_la_generacion_activa_del_stop():
    sid = "setup:testnet:1"
    ex = BotExecutor(store=None, log=lambda _message: None, config={})
    base = ex._aid(sid)

    class _Client:
        canceled = []

        def algo_open_orders(self, _symbol):
            return [
                {
                    "algo_id": 42,
                    "client_algo_id": base + "g2",
                    "status": "NEW",
                },
                {
                    "algo_id": 99,
                    "client_algo_id": "stop-de-otro-trade",
                    "status": "NEW",
                },
            ]

        def cancel_algo_order(self, **kwargs):
            self.canceled.append(kwargs)

    cli = _Client()
    ex._cancel_native_stops(cli, "BTCUSDT", sid)

    assert cli.canceled == [{"algo_id": 42, "client_algo_id": None}]


def test_store_conserva_hora_del_setup_y_estado_del_stop(tmp_path):
    store = BotStore(path=str(tmp_path / "bot_trades.json"))
    rec = {
        "setup_id": "setup:1",
        "symbol": "ADAUSDT",
        "pair": "ADA_USDT",
        "dir": "short",
        "mode": "live",
        "qty": 10,
        "entry_price": 0.16,
        "ts": 200,
        "setup_created_at": 100,
        "sin_stop_nativo": True,
        "risk_drift_pct": 23.1,
    }

    trade = store.open_trade(rec)

    assert trade["opened_at"] == 200
    assert trade["setup_created_at"] == 100
    assert trade["sin_stop_nativo"] is True
    assert trade["risk_drift_pct"] == 23.1


def test_executor_registra_hora_de_fill_no_hora_de_creacion():
    source = (
        Path(__file__).parents[1] / "modules/bot/executor.py"
    ).read_text()
    start = source.index("def registro_apertura")
    block = source[start:start + 2600]

    assert '"ts": time.time()' in block
    assert '"setup_created_at": t.get("ts_created")' in block


def test_riesgo_post_fill_usa_precio_y_qty_ejecutados():
    source = (
        Path(__file__).parents[1] / "modules/bot/executor.py"
    ).read_text()
    start = source.index("El riesgo se recalcula SIEMPRE con el fill")
    block = source[start:start + 1300]

    assert "actual_notional = entry_price * qty" in block
    assert "sl_frac = abs(entry_price - sl) / entry_price" in block
    assert "risk_usd_est = abs(entry_price - sl) * qty" in block
    assert "risk_drift_pct" in block
