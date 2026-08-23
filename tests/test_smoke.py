"""Smoke tests: que la app y sus piezas IMPORTEN y que el cifrado de la bóveda
funcione. Sin red, sin DB, sin servicios externos.

Corre en CI en el Python del VPS (3.14) y el de Railway → caza incompatibilidades
de versión como la de hoy (SQLAlchemy 2.0.36 rompía al importar en Python 3.14 y
tumbó el motor). Un simple `import core.app` lo habría detectado.
"""
import base64
import importlib
from pathlib import Path

import pytest


def test_import_core_app():
    """Importa toda la app (corre Hub(load_config()) a nivel de módulo). Caza
    errores de import / incompatibilidades de dependencias."""
    importlib.import_module("core.app")


def test_favicon_es_ico_compatible():
    from fastapi.testclient import TestClient
    from core import app

    response = TestClient(app.app).get("/favicon.ico")
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/x-icon"
    assert response.content.startswith(b"\x00\x00\x01\x00")


def test_todas_las_vistas_html_declaran_favicon_nexux():
    root = Path(__file__).resolve().parents[1]
    pages = [
        *sorted((root / "core").glob("*.html")),
        *sorted((root / "docs" / "diseno").glob("*.html")),
        *sorted((root / "modules").glob("*/public/*.html")),
        *sorted((root / "research").glob("*.html")),
    ]
    assert pages
    for page in pages:
        html = page.read_text(encoding="utf-8")
        assert 'href="/static/icons/nexux-favicon-v5.ico"' in html, page


@pytest.mark.parametrize("mod", [
    "core.db", "core.auth", "core.store", "core.vault", "core.push",
    "modules.journal.module", "modules.journal.collector",
    "modules.journal.binance_client", "modules.journal.stats",
    "modules.trading.module", "modules.trading.news", "modules.trading.dashboard",
    "modules.trading.setups_store",
    "modules.coinsignals.module", "modules.coinsignals.shadow",
    "modules.coinsignals.collector",
])
def test_import_module(mod):
    importlib.import_module(mod)


def test_vault_roundtrip():
    """Cifra credenciales con la pública y descífralas con la privada (envelope)."""
    from core import vault
    priv, pub = vault.generate_keypair()
    blob = vault.seal_credentials("APIKEY_abcdef123456", "SECRET_xyz9876543210", pub)
    assert "APIKEY_abcdef" not in str(blob), "fuga de plaintext en el sobre"
    k, s = vault.unseal_credentials(blob, priv)
    assert (k, s) == ("APIKEY_abcdef123456", "SECRET_xyz9876543210")


def test_vault_tamper_detected():
    """Un sobre alterado debe ser rechazado (AES-GCM autentica)."""
    from core import vault
    priv, pub = vault.generate_keypair()
    blob = vault.seal_credentials("a" * 20, "b" * 20, pub)
    raw = bytearray(base64.b64decode(blob["ct"]))
    raw[0] ^= 1
    blob["ct"] = base64.b64encode(bytes(raw)).decode()
    with pytest.raises(Exception):
        vault.unseal_credentials(blob, priv)


def test_vault_public_cannot_decrypt():
    """La clave pública NO puede descifrar (defensa en profundidad: Railway no descifra)."""
    from core import vault
    _, pub = vault.generate_keypair()
    blob = vault.seal_credentials("a" * 20, "b" * 20, pub)
    with pytest.raises(Exception):
        vault.unseal(blob, pub)


def test_bot_panel_muestra_fase1_dry_run():
    """El panel del bot debe mostrar el seguimiento de Fase 1 sin venderlo como permiso live."""
    root = Path(__file__).resolve().parents[1]
    html = (root / "modules/bot/public/index.html").read_text(encoding="utf-8")
    js = (root / "modules/bot/public/app.js").read_text(encoding="utf-8")
    assert 'id="phase1"' in html
    assert "Fase 1 V2 dry-run" in html
    assert "phase1_v2_2026-07-18" in js
    assert "cruce causal de la entrada central" in js
    assert "20 trades dry o 3 semanas" in js
    assert "no autoriza live" in js


def test_hub_expone_todo_el_workspace():
    """La portada conserva el Home comercial aprobado y su identidad NexUX."""
    root = Path(__file__).resolve().parents[1]
    html = (root / "docs/diseno/home-clean.html").read_text(encoding="utf-8")
    assert "Menos pantallas" in html
    assert "hero-brand" in html
    assert 'class="iso"' in html
    assert 'href="/login"' in html
    assert html.count('href="/login"') == 1
    assert 'href="#producto"' in html
    assert 'href="#seguridad"' in html
    assert 'rel="icon"' in html
    assert 'target="_blank" rel="noopener noreferrer"' in html
    assert "safeHttpUrl(n.url)" in html


def test_feed_de_noticias_conserva_solo_enlaces_web(monkeypatch):
    from modules.trading import dashboard

    rss = """<?xml version="1.0"?>
    <rss><channel>
      <item><title>Noticia segura</title><link>https://example.com/article</link></item>
      <item><title>Noticia sin enlace seguro</title><link>javascript:alert(1)</link></item>
    </channel></rss>"""
    monkeypatch.setattr(dashboard, "_FEEDS", [("https://feed.test/rss", "Test", "es")])
    monkeypatch.setattr(dashboard, "_fetch_text", lambda url: rss)
    monkeypatch.setattr(dashboard.time, "time", lambda: 1000)
    dashboard._CACHE.pop("_news_feed", None)

    rows = dashboard._news_feed()

    assert rows[0]["url"] == "https://example.com/article"
    assert rows[1]["url"] is None


def test_modulos_montan_navegacion_global():
    """Las vistas principales comparten el mismo mapa de navegación."""
    root = Path(__file__).resolve().parents[1]
    pages = [
        "modules/trading/public/index.html",
        "modules/journal/public/index.html",
        "modules/bot/public/index.html",
        "modules/coinsignals/public/index.html",
        "modules/coinglass/public/index.html",
        "modules/trading/public/backtest.html",
        "modules/trading/public/research-bta-v2.html",
        "modules/trading/public/research-diario-v1.html",
        "modules/acciones_chile/public/index.html",
    ]
    for page in pages:
        html = (root / page).read_text(encoding="utf-8")
        assert "/static/nexux-shell.css" in html, page
        assert "/static/nexux-shell.js" in html, page
        assert 'href="/static/icons/nexux-favicon-v5.ico"' in html, page

    shell = (root / "static/nexux-shell.js").read_text(encoding="utf-8")
    assert '{ href: "/inicio", text: "Inicio"' in shell
    # El menú debe ofrecer los dos mundos, no sólo el cripto.
    assert '{ href: "/m/acciones_chile/", text: "Cartera y CMF"' in shell
    assert 'label: "Acciones Chile"' in shell
    assert 'class="nx-shell-mark"' in shell
    assert "M28 28 L72 72" in shell
    assert '{ href: "/account", text: "Mi cuenta"' in shell
    assert '{ href: "/m/trading/research-diario-v1", text: "Diario V1"' in shell
    assert 'favicon.href = "/static/icons/nexux-favicon-v5.ico"' in shell
    assert 'user.role !== "admin"' in shell


def test_archivo_diario_v1_separa_paper_de_bot():
    root = Path(__file__).resolve().parents[1]
    html = (root / "modules/trading/public/research-diario-v1.html").read_text(
        encoding="utf-8")
    assert "Diario V1 archivado" in html
    assert "$118.490" in html
    assert "275" in html
    assert "60,7%" in html
    assert "Bot Fase 1 V1" in html
    assert "37,5%" in html
    assert "-0,305R" in html
    assert "Dos operaciones V1 residuales" in html
