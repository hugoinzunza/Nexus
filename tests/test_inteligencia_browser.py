"""Prueba real de Chrome para el encuadre de Acción del precio.

Los tests estáticos no detectan que una API del gráfico exista pero responda null.
Este archivo levanta NexUX, abre la vista y observa el mismo DOM que ve el usuario.
"""
from __future__ import annotations

import os
import re
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

import pytest
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.select import Select
from selenium.webdriver.support.ui import WebDriverWait


ROOT = os.path.dirname(os.path.dirname(__file__))
PUBLIC = os.path.join(ROOT, "modules", "inteligencia", "public")


def _fixture_estado():
    estructura = {
        "piv": 5, "tendencia": "lateral", "retraso_velas": 5, "motivo": "fixture",
        "n_highs": 0, "n_lows": 0, "n_fractales_highs": 0, "n_fractales_lows": 0,
        "highs": [], "lows": [], "fractales_highs": [], "fractales_lows": [],
    }
    return {
        "symbol": "BTCUSDT", "pares": ["BTCUSDT"], "precio": 65_000.0,
        "anio": 2026, "apertura_anual": None, "apertura_semanal": None,
        "desde_apertura_anual_pct": None, "rejilla": [], "rejilla_placebo": {},
        "rejillas_historicas": [], "refugios_promovidos": [],
        "catalogo_formulas": {}, "nota_refugios": "fixture",
        "vacio_arriba": {}, "vacio_abajo": {},
        "estructura_1h": estructura, "estructura_1D": estructura,
    }


def _fixture_velas():
    inicio = 1_750_000_000_000
    velas = []
    for i in range(500):
        base = 64_000 + i * 2 + ((i % 20) - 10) * 12
        velas.append({
            "t": inicio + i * 3_600_000, "o": base - 8, "h": base + 45,
            "l": base - 45, "c": base + 8, "v": 1,
        })
    return {
        "velas": velas, "estructura": _fixture_estado()["estructura_1h"],
        "fases": [], "stream_vivo": None, "fuente": "browser_fixture",
        "fuente_meta": {},
    }


def _fixture_mapa():
    capa = lambda estado: {
        "total": 0, "arriba": [], "abajo": [], "evidence_status": estado,
    }
    return {
        "symbol": "BTCUSDT", "precio": 65_000.0, "selected_tf": "4h",
        "perfil": {
            "label": "medio", "panorama": ["1d"], "principal": "4h",
            "sincronismo": "1h",
        },
        "alineacion": {
            "estado": "contexto_superior_mixto_o_indefinido",
            "direccion_contexto": None, "tendencias": {},
        },
        "vacio_horizonte": {"evaluado": False, "motivo": "fixture"},
        "mapa": None, "mapas_temporales": {},
        "referencias_cercanas": {
            "arriba": [], "abajo": [], "total_arriba": 0, "total_abajo": 0,
        },
        "capas_referencias": {
            "estructura": capa("observado_descriptivo_no_predictivo"),
            "calculados": capa("calculado_no_predictivo"),
            "rejilla": capa("calculado_refutado_como_predictor"),
            "liquidez": capa("no_implementado"),
        },
        "nota": "fixture causal de navegador",
    }


@pytest.fixture(scope="module")
def servidor_nexux():
    rutas = {
        "/m/inteligencia/": (os.path.join(PUBLIC, "index.html"), "text/html"),
        "/m/inteligencia/app.js": (os.path.join(PUBLIC, "app.js"), "text/javascript"),
        "/m/inteligencia/styles.css": (os.path.join(PUBLIC, "styles.css"), "text/css"),
        "/static/vendor/lightweight-charts.standalone.production.js": (
            os.path.join(ROOT, "static", "vendor",
                         "lightweight-charts.standalone.production.js"),
            "text/javascript",
        ),
        "/static/nexux-shell.js": (
            os.path.join(ROOT, "static", "nexux-shell.js"), "text/javascript",
        ),
        "/static/nexux-shell.css": (
            os.path.join(ROOT, "static", "nexux-shell.css"), "text/css",
        ),
    }

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            ruta = urlparse(self.path).path
            if ruta in rutas:
                archivo, mime = rutas[ruta]
                with open(archivo, "rb") as fh:
                    cuerpo = fh.read()
                self.send_response(200)
                self.send_header("Content-Type", mime)
            else:
                payload = (
                    _fixture_velas() if ruta.endswith("/api/velas")
                    else _fixture_mapa() if ruta.endswith("/api/mapa")
                    else _fixture_estado() if ruta.endswith("/api/state")
                    else {"ok": True}
                )
                cuerpo = json.dumps(payload).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(cuerpo)))
            self.end_headers()
            self.wfile.write(cuerpo)

        def log_message(self, _format, *_args):
            return

    servidor = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    hilo = threading.Thread(target=servidor.serve_forever, daemon=True)
    hilo.start()
    url = f"http://127.0.0.1:{servidor.server_address[1]}"
    try:
        yield url
    finally:
        servidor.shutdown()
        servidor.server_close()
        hilo.join(timeout=5)


@pytest.fixture(scope="module")
def chrome():
    opciones = webdriver.ChromeOptions()
    opciones.add_argument("--headless=new")
    opciones.add_argument("--no-sandbox")
    opciones.add_argument("--disable-dev-shm-usage")
    opciones.add_argument("--disable-gpu")
    opciones.add_argument("--window-size=1280,900")
    navegador = webdriver.Chrome(options=opciones)
    try:
        yield navegador
    finally:
        navegador.quit()


def _encuadre(driver, tf: str) -> tuple[int, str]:
    def cargado(_driver):
        nodo = _driver.find_element(By.ID, "g-sub")
        texto = nodo.text
        match = re.search(r"(\d+) velas visibles", texto)
        return (int(match.group(1)), nodo.get_attribute("data-viewport-status")) if match else False

    resultado = WebDriverWait(driver, 15).until(cargado)
    n, estado = resultado
    assert tf in driver.find_element(By.ID, "g-sub").text
    assert 40 <= n <= 150, f"encuadre roto en {tf}: {n} velas; estado={estado}"
    assert estado, "el gráfico cargó sin declarar el estado del viewport"
    return n, estado


def test_viewport_real_carga_recarga_y_cambia_tf(servidor_nexux, chrome):
    chrome.get(f"{servidor_nexux}/m/inteligencia/")
    _encuadre(chrome, "4h")

    chrome.refresh()
    _encuadre(chrome, "4h")

    Select(chrome.find_element(By.ID, "tf")).select_by_value("1h")
    WebDriverWait(chrome, 15).until(
        lambda driver: "BTCUSDT 1h" in driver.find_element(By.ID, "g-sub").text
    )
    _encuadre(chrome, "1h")

    # Reproduce explícitamente el estado observado por Claude: la API existe, pero
    # devuelve null. El respaldo debe ser visible y jamás volver a las 500 velas.
    chrome.execute_script("""
      const escala = state.chart.timeScale();
      escala.getVisibleLogicalRange = () => null;
      state.awaitingInitialViewport = true;
      pintarNiveles();
    """)
    _, estado = _encuadre(chrome, "1h")
    assert estado == "null_ultimo_valido"

    chrome.execute_script("""
      state.lastValidLogicalRange = null;
      pintarNiveles();
    """)
    n, estado = _encuadre(chrome, "1h")
    assert n == 80
    assert estado == "null_respaldo_80"
    assert "encuadre de respaldo: null respaldo 80" in chrome.find_element(
        By.ID, "g-sub"
    ).text
