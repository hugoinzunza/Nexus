"""Tests del payload replay y de la vista research BTA v2.

Correr con:  .venv/bin/python3 -m pytest research/test_bta_visual_replay.py -q
"""
from __future__ import annotations

import json
import os
import sys

WT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if WT not in sys.path:
    sys.path.insert(0, WT)

from research import bta_visual_replay as rp  # noqa: E402

DATA = os.path.join(WT, "research", "bta_btcusdtp_15m_recent.json")
PAYLOAD = os.path.join(WT, "research", "bta_visual_replay_2026-07-05.json")
PAGE = os.path.join(WT, "modules", "trading", "public", "research-bta-v2.html")
LAB = os.path.join(WT, "modules", "trading", "public", "backtest.html")
MODULE = os.path.join(WT, "modules", "trading", "module.py")


def _payload():
    candles = json.load(open(DATA))[-1500:]   # ventana corta: test rápido
    return rp.build_replay(candles)


def test_meta_marca_research_only():
    p = _payload()
    assert p["meta"]["research_only"] is True
    assert "No senal" in p["meta"]["aviso"] and "No bot" in p["meta"]["aviso"]
    assert "historico" in p["meta"]["dataset"]


def test_historias_causales_sin_lookahead():
    """Todos los timestamps de las historias avanzan y nada ocurre antes de crearse."""
    p = _payload()
    for lvl in p["cdc"]:
        ts = [t for _, t in lvl["history"]]
        assert ts == sorted(ts), f"historia CDC desordenada: {lvl['id']}"
        if lvl["broken_t"] is not None:
            assert lvl["broken_t"] >= lvl["created_t"]
        if lvl["reclaimed_t"] is not None:
            assert lvl["reclaimed_t"] >= lvl["broken_t"]
    for z in p["zones"]:
        ts = [t for _, t in z["history"]]
        assert ts == sorted(ts), f"historia de zona desordenada: {z['id']}"
        if z["tap_t"] is not None:
            assert z["tap_t"] >= z["created_t"]
        if z["confirmed_t"] is not None:
            assert z["confirmed_t"] > z["tap_t"], "confirmación debe ser POSTERIOR al toque"
    for r in p["pivots"]:
        if r["swept_t"] is not None:
            assert r["swept_t"] > r["confirm_t"], "barrido antes de confirmar = look-ahead"


def test_payload_acotado_y_serializable():
    p = _payload()
    assert len(p["zones"]) <= rp.MAX_ZONES
    assert len(p["candles"]) <= rp.WINDOW
    js = json.dumps(p)                       # serializable de punta a punta
    assert "research_only" in js


def test_payload_committeado_valido():
    """El JSON que sirve la web debe existir y llevar la marca research_only."""
    assert os.path.isfile(PAYLOAD), "falta el payload; corre research/bta_visual_replay.py"
    d = json.load(open(PAYLOAD))
    assert d["meta"]["research_only"] is True
    assert d["candles"] and d["zones"] and d["cdc"]


def test_pagina_muestra_banner_y_endpoint():
    html = open(PAGE, encoding="utf-8").read()
    assert "Research only" in html
    assert "No se&ntilde;al" in html and "No bot" in html
    assert "/m/trading/api/research_bta_v2" in html
    assert "research_only!==true" in html.replace(" ", ""), \
        "la página debe rechazar payloads sin marca research_only"


def test_lab_tiene_link_discreto_y_module_sirve_subpath():
    lab = open(LAB, encoding="utf-8").read()
    assert "/m/trading/research-bta-v2" in lab
    mod = open(MODULE, encoding="utf-8").read()
    assert "research_bta_v2" in mod and "_BTA_V2_REPLAY_PATH" in mod
