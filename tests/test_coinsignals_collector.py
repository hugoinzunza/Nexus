"""Cadencia y cache del colector CoinSignals."""
from __future__ import annotations

import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TIMER = os.path.join(ROOT, "deploy/nexus-coinsignals.timer")
COL = os.path.join(ROOT, "modules/coinsignals/collector.py")


def test_la_cadencia_no_puede_volver_a_60_segundos():
    """MEDIDO el 2026-07-27: el canal publica 0,34 mensajes/hora y las senales BTC
    operables salen a 0,7 POR SEMANA. Cada corrida baja los ULTIMOS 500 mensajes, o sea
    61 dias de cobertura al ritmo actual, y la peor rafaga en 30 min desde 2019 fue 44.

    A 60 s eran 1.440 conexiones diarias a Telegram, cada una con un escaneo completo
    de los 117 dialogos, para observar algo que ocurre cada 10 dias.
    """
    t = open(TIMER, encoding="utf-8").read()
    assert "OnUnitActiveSec=180" in t
    assert "OnUnitActiveSec=60" not in t


def test_el_canal_se_cachea_y_el_cache_se_puede_invalidar():
    """El id del canal no cambia nunca; buscarlo por nombre recorria los 117 dialogos
    en cada corrida. Y si el titulo cambia, el cache tiene que descartarse solo."""
    src = open(COL, encoding="utf-8").read()
    assert "_canal_cacheado" in src and "_guardar_canal" in src
    assert "client.get_entity" in src
    # sigue existiendo el camino de escaneo como respaldo
    assert "iter_dialogs" in src, "sin respaldo, un cache malo deja el colector muerto"


def test_el_cache_no_puede_romper_la_corrida():
    """Un fallo al leer o escribir el cache no puede tumbar la recoleccion: el colector
    ya perdio ciclos una vez por un guard mio que fallaba cerrado."""
    src = open(COL, encoding="utf-8").read()
    leer = src.split("def _canal_cacheado")[1].split("\ndef ")[0]
    escribir = src.split("def _guardar_canal")[1].split("\ndef ")[0]
    assert "return None" in leer and "except" in leer
    assert "except OSError" in escribir and "pass" in escribir


def test_la_latencia_de_lectura_no_afecta_el_libro():
    """`replay_swing` resuelve cada senal contra las velas POSTERIORES a su propio
    timestamp de Telegram, no contra el momento en que la leemos. Por eso bajar la
    cadencia no cambia ninguna fila registrada — y por eso el argumento de "podemos
    perder una entrada" no aplica al libro, aunque si aplique a verla a tiempo.
    """
    swing = open(os.path.join(ROOT, "research/coinsignals_btc_swing.py"),
                 encoding="utf-8").read()
    bloque = swing.split("def replay_swing(")[1][:1200]
    assert "next_bar(signal.date_ms)" in bloque, \
        "el replay dejo de anclarse al timestamp de la senal"
