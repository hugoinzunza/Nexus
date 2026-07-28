"""Cortacircuitos del precio Binance en el poller de trading."""
from __future__ import annotations

import os
import types

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODULE = os.path.join(ROOT, "modules/trading/module.py")


def _mod():
    import sys
    sys.path.insert(0, ROOT)
    from modules.trading.module import TradingModule as T
    m = T.__new__(T)
    m._px_breaker, m._px_aviso_ts = {}, {}
    m._PX_FALLOS_PARA_ABRIR, m._PX_ESPERA_ABIERTO = 3, 60.0
    m.logs = []
    m.context = types.SimpleNamespace(log=m.logs.append)
    return m


def test_no_se_martilla_un_endpoint_que_siempre_rechaza():
    """En Railway `fapi.binance.com` responde 451 (geo-bloqueo del datacenter). El
    poller pedia el precio de los 5 pares del bot CADA 2 s pasara lo que pasara:
    ~216.000 peticiones diarias a algo que estructuralmente nos rechaza.
    """
    m = _mod()
    intentos = 0
    for _ in range(30):
        if m._binance_px_abierto("BTCUSDT"):
            intentos += 1
            m._binance_px_fallo("BTCUSDT", RuntimeError("HTTP Error 451"))
    assert intentos == 3, f"siguio pidiendo: {intentos} intentos en 30 ciclos"


def test_el_corte_NO_es_permanente():
    """Un bloqueo geografico y un 429 de un minuto se ven igual desde aca. Cerrar para
    siempre convertiria una caida transitoria en degradacion indefinida."""
    m = _mod()
    for _ in range(3):
        m._binance_px_fallo("BTCUSDT", RuntimeError("429"))
    assert m._binance_px_abierto("BTCUSDT") is False
    m._px_breaker["BTCUSDT"]["desde"] -= 61
    assert m._binance_px_abierto("BTCUSDT") is True


def test_en_el_VPS_no_interfiere():
    """Donde las llamadas funcionan, el cortacircuitos no puede llegar a abrirse: el
    contador se resetea en cada exito. Este cambio no puede degradar el gatillo de SL
    en el unico lugar donde hay ejecucion."""
    m = _mod()
    for _ in range(50):
        assert m._binance_px_abierto("BTCUSDT") is True
        m._binance_px_ok("BTCUSDT")
    assert m._px_breaker["BTCUSDT"]["fallos"] == 0


def test_nunca_tuvo_precio_no_es_lo_mismo_que_precio_viejo():
    """El default era `0` -el epoch- asi que un simbolo sin precio reportaba una edad
    de 1.785.200.766 s = 56 anos, y el mensaje decia "precio viejo". No era viejo: no
    existia. Son dos estados distintos y llevan a diagnosticos distintos."""
    src = open(MODULE, encoding="utf-8").read()
    bloque = src.split("visto = self._last_binance_px_ts.get(bsym)")[1][:700]
    assert "get(bsym)" in src.split("visto = ")[1][:60], "volvio un default numerico"
    assert "sin precio Binance todavía" in bloque
    assert "age is None" in bloque
    # y el default 0 no puede volver
    assert "_last_binance_px_ts.get(bsym, 0)" not in src


def test_el_aviso_no_inunda_el_log():
    """A 2 s por ciclo y 5 pares el mensaje salia ~216.000 veces al dia y enterraba
    cualquier otra linea."""
    m = _mod()
    for _ in range(100):
        m._avisar_px("BTCUSDT", "aviso")
    assert len(m.logs) == 1, f"el aviso se repitio {len(m.logs)} veces"
