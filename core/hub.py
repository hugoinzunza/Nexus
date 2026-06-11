"""El hub de Nexus: ciclo de vida de los módulos y estado del sistema.

Antes esta clase también levantaba un servidor HTTP propio (http.server). Ahora
el servidor es FastAPI + uvicorn (ver `core/app.py`); el hub se ocupa solo de:

  - cargar la configuración,
  - descubrir, arrancar y detener los módulos,
  - exponer el estado de salud,
  - renderizar la página de inicio (el "landing" con las tarjetas).

El núcleo sigue siendo chico y estable; la funcionalidad vive en `modules/`.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime

# Aseguramos que la raíz del proyecto esté en sys.path para poder importar
# `core` y `modules` sin importar desde dónde se ejecute uvicorn.
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from core.module_loader import load_modules


def log(message: str) -> None:
    stamp = datetime.now().strftime("%H:%M:%S")
    print(f"[{stamp}] {message}", flush=True)


class Hub:
    def __init__(self, config: dict):
        self.config = config
        self.port = int(os.environ.get("PORT", config.get("port", 8800)))
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

        log("─" * 52)
        log(f"🌐 Nexus listo · {len(self.modules)} módulo(s) cargado(s)")
        for m in self.modules:
            log(f"   {m.icon}  {m.title:<16} → /m/{m.slug}/")
        log("─" * 52)

    def shutdown(self) -> None:
        for module in self.modules:
            try:
                module.stop()
            except Exception:  # noqa: BLE001
                pass
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
  <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
  <meta name="theme-color" content="#0f1117">
  <meta name="description" content="Nexus · el hub personal de Hugo">
  <title>Nexus · Hub personal</title>
  <link rel="manifest" href="/manifest.webmanifest">
  <link rel="icon" href="/favicon.ico">
  <link rel="apple-touch-icon" href="/static/icons/apple-touch-icon.png">
  <meta name="apple-mobile-web-app-capable" content="yes">
  <meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
  <meta name="apple-mobile-web-app-title" content="Nexus">
  <style>
    :root { --bg:#0f1117; --panel:#171a23; --line:#262b38; --text:#e6e9f0;
            --muted:#8b93a7; --accent:#6c5ce7; --accent2:#a29bfe; }
    * { box-sizing: border-box; }
    body { margin:0; font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
           background:var(--bg); color:var(--text); min-height:100vh; min-height:100dvh;
           padding:constant(safe-area-inset-top) constant(safe-area-inset-right) constant(safe-area-inset-bottom) constant(safe-area-inset-left);
           padding:env(safe-area-inset-top) env(safe-area-inset-right) env(safe-area-inset-bottom) env(safe-area-inset-left); }
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
    Núcleo modular · agrega módulos en <code>modules/</code> · API de salud en <code>/health</code>
  </footer>
  <script src="/static/pwa.js" defer></script>
</body>
</html>"""


def load_config() -> dict:
    config_path = os.path.join(ROOT, "config", "nexus.json")
    with open(config_path, "r", encoding="utf-8") as fh:
        return json.load(fh)
