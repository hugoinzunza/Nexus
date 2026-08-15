"""Protección del runner a 3R (HYP-EXIT-002) — bandera oscura.

La evidencia de la cohorte solo aplica si producción calcula IGUAL que la
sombra: trigger = entry ± 3·riesgo, stop protegido = entry exacto
(protected_stop_rr = 0.0 en la spec congelada)."""
import copy
import json
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from modules.bot.bot_store import BotStore
from modules.bot.executor import (
    PROTECT3R_STOP_GEN, PROTECT3R_TRIGGER_RR, BotExecutor)


class ClienteFalso:
    def __init__(self, confirmar=True):
        self.confirmar = confirmar
        self.algo_orders = []
        self.cancelados = []

    def algo_stop_market(self, symbol, side, stop, qty=None, position_side=None,
                         client_algo_id=None):
        self.algo_orders.append({"symbol": symbol, "side": side, "stop": stop,
                                 "qty": qty, "position_side": position_side,
                                 "client_algo_id": client_algo_id})

    def get_algo_order(self, aid):
        if not self.confirmar:
            return None
        ultimo = self.algo_orders[-1]
        return {"client_algo_id": aid, "side": ultimo["side"],
                "position_side": ultimo["position_side"],
                "qty": ultimo["qty"], "trigger_price": ultimo["stop"],
                "status": "NEW"}

    def algo_open_orders(self, symbol):
        return [{"client_algo_id": o["client_algo_id"], "algo_id": i + 1}
                for i, o in enumerate(self.algo_orders)]

    def cancel_algo_order(self, algo_id=None, client_algo_id=None):
        self.cancelados.append(algo_id or client_algo_id)

    @staticmethod
    def round_qty(symbol, qty):
        return qty


def _executor(tmp_path, cliente, extra_cfg=None, trade_extra=None):
    store = BotStore(path=str(tmp_path / "bot_trades.json"))
    trade = {
        "setup_id": "S1", "key": "k", "symbol": "BTCUSDT", "pair": "BTC_USDT",
        "dir": "long", "mode": "live", "leverage": 10, "qty": 0.01,
        "entry_price": 100.0, "sl": 98.0, "tp": 130.0,
        "risk_usd": 0.02, "risk_usd_est": 0.02,  # riesgo/unidad = 2.0
        "fee_rate": 0.0005, "opened_at": 1,
    }
    trade.update(trade_extra or {})
    store.open_trade(trade)
    cfg = {"enabled": True, "live": True, "hedge": True, "pairs": ["BTCUSDT"]}
    cfg.update(extra_cfg or {})
    logs = []
    ex = BotExecutor(store, logs.append, config=cfg, client=cliente,
                     data_dir=str(tmp_path), kill_file=str(tmp_path / "kill"))
    return ex, store, cliente, logs


def _libro(store):
    return json.loads(pathlib.Path(store.path).read_text(encoding="utf-8"))


def test_bandera_apagada_es_identidad_total(tmp_path):
    ex, store, cliente, logs = _executor(tmp_path, ClienteFalso())
    antes = copy.deepcopy(_libro(store))
    ex.on_protect_tick("BTCUSDT", 200.0)  # muy por encima de 3R
    assert cliente.algo_orders == [] and cliente.cancelados == []
    assert _libro(store) == antes
    assert logs == []


def test_bajo_el_gatillo_no_hace_nada(tmp_path):
    ex, store, cliente, _ = _executor(
        tmp_path, ClienteFalso(), extra_cfg={"exit_protect_3r": True})
    # trigger = 100 + 3*2 = 106
    ex.on_protect_tick("BTCUSDT", 105.99)
    assert cliente.algo_orders == []
    assert _libro(store)[0]["sl"] == 98.0


def test_cruce_de_3r_mueve_el_stop_a_be_y_es_idempotente(tmp_path):
    ex, store, cliente, _ = _executor(
        tmp_path, ClienteFalso(), extra_cfg={"exit_protect_3r": True},
        trade_extra={"qty_open": 0.01})
    ex.on_protect_tick("BTCUSDT", 106.0)  # == entry + 3*riesgo, misma formula sombra
    assert len(cliente.algo_orders) == 1
    orden = cliente.algo_orders[0]
    assert orden["stop"] == 100.0            # protected_stop_rr = 0.0 → entry exacto
    assert orden["side"] == "SELL" and orden["position_side"] == "LONG"
    assert orden["client_algo_id"].endswith(f"g{PROTECT3R_STOP_GEN}") or \
        str(PROTECT3R_STOP_GEN) in orden["client_algo_id"]
    libro = _libro(store)[0]
    assert libro["sl"] == 100.0 and libro["sl_move_reason"] == "protect_3r"
    # segundo tick sobre el gatillo: nada nuevo
    ex.on_protect_tick("BTCUSDT", 107.0)
    assert len(cliente.algo_orders) == 1


def test_short_espejado(tmp_path):
    ex, store, cliente, _ = _executor(
        tmp_path, ClienteFalso(), extra_cfg={"exit_protect_3r": True},
        trade_extra={"dir": "short", "sl": 102.0, "tp": 80.0, "qty_open": 0.01})
    ex.on_protect_tick("BTCUSDT", 94.0)  # trigger = 100 - 6 = 94
    assert len(cliente.algo_orders) == 1
    assert cliente.algo_orders[0]["stop"] == 100.0
    assert cliente.algo_orders[0]["side"] == "BUY"
    assert cliente.algo_orders[0]["position_side"] == "SHORT"


def test_sin_confirmacion_conserva_el_stop_original_y_reintenta(tmp_path):
    ex, store, cliente, logs = _executor(
        tmp_path, ClienteFalso(confirmar=False),
        extra_cfg={"exit_protect_3r": True}, trade_extra={"qty_open": 0.01})
    ex.on_protect_tick("BTCUSDT", 106.5)
    assert cliente.cancelados == []          # el viejo NUNCA se cancela sin nuevo
    assert _libro(store)[0]["sl"] == 98.0    # el libro no miente
    assert any("no confirmó" in m for m in logs)
    ex.on_protect_tick("BTCUSDT", 106.5)     # reintenta en el tick siguiente
    assert len(cliente.algo_orders) == 2


def test_dry_solo_deja_constancia(tmp_path):
    ex, store, cliente, logs = _executor(
        tmp_path, ClienteFalso(), extra_cfg={"exit_protect_3r": True},
        trade_extra={"mode": "dry", "qty_open": 0.01})
    ex.on_protect_tick("BTCUSDT", 110.0)
    assert cliente.algo_orders == []
    assert _libro(store)[0]["sl"] == 98.0    # dry no mueve niveles
    assert any("dry" in m and "3R" in m for m in logs)
    ex.on_protect_tick("BTCUSDT", 111.0)     # y no repite el aviso
    assert sum("3R" in m for m in logs) == 1


def test_formula_identica_a_la_spec_congelada():
    spec = json.loads(pathlib.Path(
        "research/hypothesis_lab/specs/v1/HYP-EXIT-003-SHADOW.frozen.json"
    ).read_text(encoding="utf-8"))
    assert float(spec["candidate"]["trigger_rr"]) == PROTECT3R_TRIGGER_RR
    assert float(spec["candidate"]["protected_stop_rr"]) == 0.0
