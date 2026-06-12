"""El hub de Nexux: ciclo de vida de los módulos y estado del sistema.

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
        log("⚡ Arrancando Nexux…")
        modules_root = os.path.join(ROOT, "modules")
        self.modules = load_modules(modules_root, self.config, log)
        self.modules_by_slug = {m.slug: m for m in self.modules}

        for module in self.modules:
            try:
                module.start()
            except Exception as exc:  # noqa: BLE001
                log(f"⚠️  el módulo '{module.slug}' falló al arrancar: {exc}")

        log("─" * 52)
        log(f"🌐 Nexux listo · {len(self.modules)} módulo(s) cargado(s)")
        for m in self.modules:
            log(f"   {m.icon}  {m.title:<16} → /m/{m.slug}/")
        log("─" * 52)

    def shutdown(self) -> None:
        for module in self.modules:
            try:
                module.stop()
            except Exception:  # noqa: BLE001
                pass
        log("Nexux detenido. ¡Hasta la próxima!")

    # ------------------------------------------------------------------
    def health(self) -> dict:
        uptime = (datetime.now() - self.started_at).total_seconds()
        return {
            "name": "Nexux",
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
          <div class="card-head">
            <span class="card-icon">{m.icon}</span>
            <span class="card-arrow">→</span>
          </div>
          <h2>{m.title}</h2>
          <p>{m.description}</p>
          <span class="card-tag">/m/{m.slug}</span>
        </a>""")
        # Placeholder "próximamente" para dejar ver que la arquitectura suma módulos.
        cards.append("""
        <div class="card soon">
          <div class="card-head"><span class="card-icon">＋</span></div>
          <h2>Próximamente</h2>
          <p>Núcleo modular: nuevos módulos se enchufan sin tocar el resto.</p>
          <span class="card-tag">modules/</span>
        </div>""")
        cards_html = "\n".join(cards) if cards else "<p class='empty'>No hay módulos cargados.</p>"
        return _LANDING_TEMPLATE.replace("{{CARDS}}", cards_html)


_LANDING_TEMPLATE = """<!doctype html>
<html lang="es">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
  <meta name="theme-color" content="#0f1117">
  <meta name="description" content="Nexux · el hub personal de Hugo">
  <title>Nexux · Hub personal</title>
  <link rel="manifest" href="/manifest.webmanifest">
  <link rel="icon" href="/favicon.ico">
  <link rel="apple-touch-icon" href="/static/icons/apple-touch-icon.png">
  <meta name="apple-mobile-web-app-capable" content="yes">
  <meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
  <meta name="apple-mobile-web-app-title" content="Nexux">
  <style>
    :root { --bg:#0a0c11; --panel:rgba(22,26,36,0.66); --line:#222838; --text:#e8ebf2;
            --muted:#8b93a7; --accent:#6c5ce7; --accent2:#a29bfe; --cyan:#22d3ee; --green:#16c784; }
    * { box-sizing: border-box; }
    body { margin:0; font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
           background:var(--bg); color:var(--text); min-height:100vh; min-height:100dvh;
           -webkit-font-smoothing:antialiased; overflow-x:hidden;
           padding:env(safe-area-inset-top) env(safe-area-inset-right) env(safe-area-inset-bottom) env(safe-area-inset-left); }
    /* Glow ambiental + grilla técnica sutil de fondo */
    body::before { content:""; position:fixed; inset:0; z-index:-2;
      background:
        radial-gradient(820px 460px at 50% -8%, rgba(108,92,231,0.22), transparent 70%),
        radial-gradient(680px 420px at 88% 4%, rgba(34,211,238,0.10), transparent 72%),
        var(--bg); }
    body::after { content:""; position:fixed; inset:0; z-index:-1; opacity:.5;
      background-image:linear-gradient(rgba(255,255,255,0.035) 1px, transparent 1px),
                       linear-gradient(90deg, rgba(255,255,255,0.035) 1px, transparent 1px);
      background-size:42px 42px;
      -webkit-mask-image:radial-gradient(circle at 50% 22%, #000, transparent 78%);
              mask-image:radial-gradient(circle at 50% 22%, #000, transparent 78%); }
    header { padding:64px 24px 8px; text-align:center; }
    .kicker { font:600 12px/1 ui-monospace,SFMono-Regular,Menlo,monospace; letter-spacing:3px;
              text-transform:uppercase; color:var(--accent2); opacity:.85; }
    .logo { font-size:clamp(40px,11vw,66px); font-weight:850; letter-spacing:-2px; margin-top:14px;
            background:linear-gradient(95deg,#fff 6%,var(--accent2) 42%,var(--accent) 70%,var(--cyan));
            -webkit-background-clip:text; background-clip:text; color:transparent;
            filter:drop-shadow(0 6px 30px rgba(108,92,231,0.35)); }
    .logo .dia { -webkit-text-fill-color:var(--accent2); filter:drop-shadow(0 0 14px var(--accent)); }
    .tagline { color:var(--muted); margin-top:10px; font-size:15px; }
    .status { display:inline-flex; align-items:center; gap:8px; margin-top:18px;
              padding:7px 14px; border:1px solid var(--line); border-radius:999px;
              background:rgba(22,26,36,0.6); font-size:12.5px; color:var(--muted); }
    .status .pulse { width:8px; height:8px; border-radius:50%; background:var(--green);
                     box-shadow:0 0 0 0 rgba(22,199,132,0.6); animation:pulse 2s infinite; }
    @keyframes pulse { 0%{box-shadow:0 0 0 0 rgba(22,199,132,0.5);} 70%{box-shadow:0 0 0 7px rgba(22,199,132,0);} 100%{box-shadow:0 0 0 0 rgba(22,199,132,0);} }
    .grid { max-width:900px; margin:38px auto 0; padding:0 24px;
            display:grid; grid-template-columns:repeat(auto-fill,minmax(250px,1fr)); gap:18px; }
    .card { position:relative; display:flex; flex-direction:column; gap:10px; text-decoration:none;
            background:var(--panel); border:1px solid var(--line); border-radius:18px;
            padding:22px; color:var(--text); overflow:hidden; backdrop-filter:blur(8px);
            transition:transform .16s ease, border-color .16s ease, box-shadow .16s ease; }
    .card::before { content:""; position:absolute; inset:0 0 auto 0; height:2px;
            background:linear-gradient(90deg,var(--accent),var(--cyan)); opacity:0; transition:opacity .16s; }
    .card:not(.soon):hover { transform:translateY(-4px); border-color:var(--accent);
            box-shadow:0 14px 40px -16px rgba(108,92,231,0.55); }
    .card:not(.soon):hover::before { opacity:1; }
    .card-head { display:flex; align-items:center; justify-content:space-between; }
    .card-icon { font-size:26px; width:48px; height:48px; display:grid; place-items:center;
            border-radius:12px; background:rgba(108,92,231,0.14); border:1px solid var(--line); }
    .card-arrow { color:var(--accent2); font-size:20px; transition:transform .16s; }
    .card:hover .card-arrow { transform:translateX(4px); }
    .card h2 { margin:4px 0 0; font-size:19px; letter-spacing:-.3px; }
    .card p { margin:0; color:var(--muted); font-size:14px; line-height:1.45; }
    .card-tag { margin-top:auto; padding-top:6px; font:500 11.5px/1 ui-monospace,SFMono-Regular,Menlo,monospace;
            color:var(--muted); opacity:.7; }
    .card.soon { border-style:dashed; opacity:.62; }
    .card.soon .card-icon { background:rgba(255,255,255,0.04); color:var(--muted); }
    .empty { text-align:center; color:var(--muted); }
    footer { text-align:center; color:var(--muted); font-size:12.5px; padding:34px 24px;
             font-family:ui-monospace,SFMono-Regular,Menlo,monospace; opacity:.7; }
    footer code { color:var(--accent2); }
  </style>
</head>
<body>
  <header>
    <div class="kicker">Hub personal</div>
    <div class="logo"><span class="dia">◆</span> NEXUX</div>
    <div class="tagline">Co-piloto de trading y análisis · corriendo en el Mac mini</div>
    <div class="status"><span class="pulse"></span> sistema en línea</div>
  </header>
  <main class="grid">
    {{CARDS}}
  </main>
  <footer>
    nexux.cl · núcleo modular · <code>/health</code>
  </footer>
  <script src="/static/pwa.js" defer></script>
</body>
</html>"""


def load_config() -> dict:
    config_path = os.path.join(ROOT, "config", "nexus.json")
    with open(config_path, "r", encoding="utf-8") as fh:
        return json.load(fh)
