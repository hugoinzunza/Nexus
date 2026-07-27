"""Prueba real de Chrome para el encuadre de Acción del precio.

Los tests estáticos no detectan que una API del gráfico exista pero responda null.
Este archivo levanta NexUX, abre la vista y observa el mismo DOM que ve el usuario.
"""
from __future__ import annotations

import os
import re
import socket
import subprocess
import sys
import time
import urllib.request

import pytest
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.select import Select
from selenium.webdriver.support.ui import WebDriverWait


def _puerto_libre() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@pytest.fixture(scope="module")
def servidor_nexux():
    puerto = _puerto_libre()
    raiz = os.path.dirname(os.path.dirname(__file__))
    proceso = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "core.app:app",
         "--host", "127.0.0.1", "--port", str(puerto)],
        cwd=raiz,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.STDOUT,
    )
    url = f"http://127.0.0.1:{puerto}"
    try:
        for _ in range(100):
            if proceso.poll() is not None:
                raise AssertionError("NexUX terminó antes de iniciar la prueba de navegador")
            try:
                with urllib.request.urlopen(f"{url}/health", timeout=0.5) as respuesta:
                    if respuesta.status == 200:
                        break
            except Exception:
                time.sleep(0.1)
        else:
            raise AssertionError("NexUX no respondió /health para la prueba de navegador")
        yield url
    finally:
        proceso.terminate()
        try:
            proceso.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proceso.kill()
            proceso.wait(timeout=5)


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
