"""Punto de entrada de Nexus.

Carga la configuración, descubre y arranca los módulos, levanta el servidor
HTTP y muestra la página de inicio (el "hub") que lista todos los módulos.

Se ejecuta con:  python3 -m core.hub   (o usando el script ./nexus)
"""

from __future__ import annotations

import json
import os
import signal
import sys
import time
from datetime import datetime

# Aseguramos que la raíz del proyecto esté en sys.path para poder importar
# `core` y `modules` sin importar desde dónde se ejecute.
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from core.module_loader import load_modules
from core.server import NexusHTTPServer, NexusRequestHandler


def log(message: str) -> None:
    stamp = datetime.now().strftime("%H:%M:%S")
    print(f"[{stamp}] {message}", flush=True)


class Hub:
    def __init__(self, config: dict):
        self.config = config
        self.host = config.get("host", "127.0.0.1")
        self.port = int(config.get("port", 8800))
        self.modules = []
        self.modules_by_slug = {}
        self.started_at = datetime.now()

    # ------------------------------------------------------------------
    def boot(self) -> None:
        log("⚡ Arrancando Nexus…")
        modules_root = os.path.join(ROOT, "modules")
        self.modules = load_modules(modules_root, self.config, log)
        self.modules_by_slug = {m.slug: m for m in self.modules}

        for module in self.modules:
            try:
                module.start()
            except Exception as exc:  # noqa: BLE001
                log(f"⚠️  el módulo '{module.slug}' falló al arrancar: {exc}")

    def shutdown(self) -> None:
        for module in self.modules:
            try:
                module.stop()
            except Exception:  # noqa: BLE001
                pass

    # ------------------------------------------------------------------
    def serve_forever(self) -> None:
        httpd = NexusHTTPServer((self.host, self.port), NexusRequestHandler, self)

        def handle_signal(signum, frame):  # noqa: ARG001
            log("apagando Nexus…")
            self.shutdown()
            httpd.shutdown()

        signal.signal(signal.SIGINT, handle_signal)
        signal.signal(signal.SIGTERM, handle_signal)

        url = f"http://{self.host}:{self.port}/"
        log("─" * 52)
        log(f"🌐 Nexus disponible en:  {url}")
        for m in self.modules:
            log(f"   {m.icon}  {m.title:<16} → {url}m/{m.slug}/")
        log("─" * 52)
        log("Presioná Ctrl+C para detener.")
        try:
            httpd.serve_forever()
        finally:
            httpd.server_close()
            log("Nexus detenido. ¡Hasta la próxima!")

    # ------------------------------------------------------------------
    def health(self) -> dict:
        uptime = (datetime.now() - self.started_at).total_seconds()
        return {
            "name": "Nexus",
            "status": "ok",
            "uptime_seconds": round(uptime, 1),
            "modules": [m.health() for m in self.modules],
        }

    # --- Página de inicio del hub -------------------------------------
    def render_landing(self) -> str:
        cards = []
        for m in self.modules:
            cards.append(f"""
            <a class="card" href="/m/{m.slug}/">
              <div class="card-icon">{m.icon}</div>
              <div class="card-body">
                <h2>{m.title}</h2>
                <p>{m.description}</p>
              </div>
              <div class="card-go">Abrir →</div>
            </a>""")
        cards_html = "\n".join(cards) if cards else "<p class='empty'>No hay módulos cargados.</p>"
        return _LANDING_TEMPLATE.replace("{{CARDS}}", cards_html)


_LANDING_TEMPLATE = """<!doctype html>
<html lang="es">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Nexus · Hub personal</title>
  <style>
    :root { --bg:#0f1117; --panel:#171a23; --line:#262b38; --text:#e6e9f0;
            --muted:#8b93a7; --accent:#6c5ce7; --accent2:#a29bfe; }
    * { box-sizing: border-box; }
    body { margin:0; font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
           background:var(--bg); color:var(--text); min-height:100vh; }
    header { padding:48px 24px 16px; text-align:center; }
    .logo { font-size:42px; font-weight:800; letter-spacing:-1px;
            background:linear-gradient(90deg,var(--accent2),var(--accent));
            -webkit-background-clip:text; background-clip:text; color:transparent; }
    .tagline { color:var(--muted); margin-top:6px; font-size:15px; }
    .grid { max-width:880px; margin:32px auto; padding:0 24px;
            display:grid; grid-template-columns:repeat(auto-fill,minmax(240px,1fr)); gap:18px; }
    .card { display:flex; flex-direction:column; gap:10px; text-decoration:none;
            background:var(--panel); border:1px solid var(--line); border-radius:16px;
            padding:22px; color:var(--text); transition:transform .12s, border-color .12s; }
    .card:hover { transform:translateY(-3px); border-color:var(--accent); }
    .card-icon { font-size:34px; }
    .card-body h2 { margin:0 0 4px; font-size:19px; }
    .card-body p { margin:0; color:var(--muted); font-size:14px; line-height:1.4; }
    .card-go { margin-top:auto; color:var(--accent2); font-size:14px; font-weight:600; }
    .empty { text-align:center; color:var(--muted); }
    footer { text-align:center; color:var(--muted); font-size:13px; padding:24px; }
    footer code { color:var(--accent2); }
  </style>
</head>
<body>
  <header>
    <div class="logo">◆ Nexus</div>
    <div class="tagline">Hub personal de Hugo · corriendo en el Mac mini</div>
  </header>
  <main class="grid">
    {{CARDS}}
  </main>
  <footer>
    Núcleo modular · agregá módulos en <code>modules/</code> · API de salud en <code>/health</code>
  </footer>
</body>
</html>"""


def load_config() -> dict:
    config_path = os.path.join(ROOT, "config", "nexus.json")
    with open(config_path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def main() -> None:
    config = load_config()
    hub = Hub(config)
    hub.boot()
    hub.serve_forever()


if __name__ == "__main__":
    main()
