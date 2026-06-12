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
    # Acento visual por módulo (color del icono/halo de su tarjeta).
    _CARD_ACCENTS = {"trading": "violet", "journal": "green"}

    def render_landing(self) -> str:
        cards = []
        for m in self.modules:
            accent = self._CARD_ACCENTS.get(m.slug, "cyan")
            cards.append(f"""
        <a class="card ac-{accent}" href="/m/{m.slug}/">
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
        return (_LANDING_TEMPLATE
                .replace("{{CARDS}}", cards_html)
                .replace("{{N_MODULES}}", str(len(self.modules))))


_LANDING_TEMPLATE = """<!doctype html>
<html lang="es">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
  <meta name="theme-color" content="#08090e">
  <meta name="description" content="Nexux · el hub personal de Hugo">
  <title>Nexux · Hub personal</title>
  <link rel="manifest" href="/manifest.webmanifest">
  <link rel="icon" href="/favicon.ico">
  <link rel="apple-touch-icon" href="/static/icons/apple-touch-icon.png">
  <meta name="apple-mobile-web-app-capable" content="yes">
  <meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
  <meta name="apple-mobile-web-app-title" content="Nexux">
  <style>
    :root { --bg:#08090e; --panel:rgba(22,26,36,0.6); --line:#222838; --text:#e8ebf2;
            --muted:#8b93a7; --accent:#6c5ce7; --accent2:#a29bfe; --cyan:#22d3ee;
            --green:#16c784; --red:#ea3943; }
    * { box-sizing: border-box; }
    body { margin:0; font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
           background:var(--bg); color:var(--text); min-height:100vh; min-height:100dvh;
           -webkit-font-smoothing:antialiased; overflow-x:hidden;
           padding:env(safe-area-inset-top) env(safe-area-inset-right) env(safe-area-inset-bottom) env(safe-area-inset-left); }
    /* Capa 1: orbes de color desenfocados (la "portada"). Capa 2: grilla técnica. */
    body::before { content:""; position:fixed; inset:0; z-index:-2;
      background:
        radial-gradient(700px 420px at 14% -10%, rgba(108,92,231,0.30), transparent 68%),
        radial-gradient(640px 420px at 86% -6%, rgba(34,211,238,0.14), transparent 70%),
        radial-gradient(900px 560px at 50% 112%, rgba(108,92,231,0.12), transparent 70%),
        var(--bg); }
    body::after { content:""; position:fixed; inset:0; z-index:-1; opacity:.45;
      background-image:linear-gradient(rgba(255,255,255,0.04) 1px, transparent 1px),
                       linear-gradient(90deg, rgba(255,255,255,0.04) 1px, transparent 1px);
      background-size:44px 44px;
      -webkit-mask-image:radial-gradient(ellipse at 50% 18%, #000, transparent 75%);
              mask-image:radial-gradient(ellipse at 50% 18%, #000, transparent 75%); }

    /* Barra superior glass */
    .nav { display:flex; align-items:center; justify-content:space-between; gap:14px;
           max-width:1060px; margin:0 auto; padding:18px 24px; }
    .brand { display:inline-flex; align-items:center; gap:9px; text-decoration:none;
             font-weight:800; letter-spacing:.5px; color:var(--text); font-size:16px; }
    .brand .dia { color:var(--accent2); filter:drop-shadow(0 0 10px var(--accent)); }
    .nav .links { display:flex; gap:8px; }
    .nav .links a { color:var(--muted); text-decoration:none; font-size:13px; font-weight:600;
           padding:8px 14px; border-radius:999px; border:1px solid transparent;
           transition:color .15s, border-color .15s, background .15s; }
    .nav .links a:hover { color:var(--text); border-color:var(--line); background:rgba(255,255,255,0.03); }

    /* Hero / portada */
    .hero { max-width:1060px; margin:0 auto; padding:54px 24px 10px; text-align:center; }
    .kicker { display:inline-flex; align-items:center; gap:8px;
              font:600 11.5px/1 ui-monospace,SFMono-Regular,Menlo,monospace; letter-spacing:2.5px;
              text-transform:uppercase; color:var(--accent2);
              padding:8px 16px; border:1px solid rgba(108,92,231,0.4); border-radius:999px;
              background:rgba(108,92,231,0.10); }
    .kicker .pulse { width:7px; height:7px; border-radius:50%; background:var(--green);
                     box-shadow:0 0 0 0 rgba(22,199,132,0.6); animation:pulse 2s infinite; }
    @keyframes pulse { 0%{box-shadow:0 0 0 0 rgba(22,199,132,0.5);} 70%{box-shadow:0 0 0 7px rgba(22,199,132,0);} 100%{box-shadow:0 0 0 0 rgba(22,199,132,0);} }
    h1.logo { font-size:clamp(46px,11vw,84px); font-weight:850; letter-spacing:-2.5px; margin:26px 0 0;
            line-height:1.02;
            background:linear-gradient(100deg,#fff 8%,var(--accent2) 45%,var(--accent) 72%,var(--cyan));
            -webkit-background-clip:text; background-clip:text; color:transparent;
            filter:drop-shadow(0 10px 38px rgba(108,92,231,0.4)); }
    .tagline { color:var(--muted); margin:16px auto 0; font-size:clamp(15px,2.4vw,17.5px);
               max-width:560px; line-height:1.55; }
    .tagline b { color:var(--text); font-weight:600; }
    .cta { display:flex; gap:12px; justify-content:center; flex-wrap:wrap; margin-top:30px; }
    .btn { display:inline-flex; align-items:center; gap:8px; text-decoration:none; font-weight:700;
           font-size:14.5px; padding:13px 26px; border-radius:999px; transition:transform .15s, box-shadow .15s, border-color .15s; }
    .btn.primary { color:#fff; background:linear-gradient(135deg,var(--accent),#5848c9);
           box-shadow:0 12px 34px -12px rgba(108,92,231,0.8); }
    .btn.primary:hover { transform:translateY(-2px); box-shadow:0 16px 40px -12px rgba(108,92,231,0.95); }
    .btn.ghost { color:var(--text); border:1px solid var(--line); background:rgba(22,26,36,0.5);
           backdrop-filter:blur(6px); }
    .btn.ghost:hover { border-color:var(--accent); transform:translateY(-2px); }
    /* Franja de hechos del sistema */
    .facts { display:flex; gap:0; justify-content:center; flex-wrap:wrap; margin:42px auto 0;
             border:1px solid var(--line); border-radius:16px; max-width:640px;
             background:rgba(22,26,36,0.5); backdrop-filter:blur(8px); overflow:hidden; }
    .fact { flex:1 1 0; min-width:150px; padding:16px 18px; text-align:center; }
    .fact + .fact { border-left:1px solid var(--line); }
    .fact .n { font-size:20px; font-weight:800; letter-spacing:-.5px;
               font-variant-numeric:tabular-nums; }
    .fact .n.ok { color:var(--green); }
    .fact .n.vi { color:var(--accent2); }
    .fact .k { color:var(--muted); font-size:11px; text-transform:uppercase; letter-spacing:1.2px; margin-top:4px; }

    /* Tarjetas de módulos */
    .grid { max-width:1060px; margin:46px auto 0; padding:0 24px;
            display:grid; grid-template-columns:repeat(auto-fill,minmax(270px,1fr)); gap:18px; }
    .card { position:relative; display:flex; flex-direction:column; gap:10px; text-decoration:none;
            background:var(--panel); border:1px solid var(--line); border-radius:20px;
            padding:24px; color:var(--text); overflow:hidden;
            backdrop-filter:blur(10px); -webkit-backdrop-filter:blur(10px);
            transition:transform .16s ease, border-color .16s ease, box-shadow .16s ease; }
    .card::before { content:""; position:absolute; inset:0 0 auto 0; height:2px; opacity:0;
            transition:opacity .16s; background:linear-gradient(90deg,var(--accent),var(--cyan)); }
    .card:not(.soon):hover { transform:translateY(-4px); box-shadow:0 18px 46px -18px rgba(0,0,0,0.85); }
    .card:not(.soon):hover::before { opacity:1; }
    .card-head { display:flex; align-items:center; justify-content:space-between; }
    .card-icon { font-size:26px; width:52px; height:52px; display:grid; place-items:center;
            border-radius:14px; border:1px solid var(--line); }
    .ac-violet .card-icon { background:rgba(108,92,231,0.16); box-shadow:0 0 26px -6px rgba(108,92,231,0.55); }
    .ac-green  .card-icon { background:rgba(22,199,132,0.13); box-shadow:0 0 26px -6px rgba(22,199,132,0.45); }
    .ac-cyan   .card-icon { background:rgba(34,211,238,0.12); box-shadow:0 0 26px -6px rgba(34,211,238,0.45); }
    .ac-violet:hover { border-color:var(--accent); }
    .ac-green:hover  { border-color:var(--green); }
    .ac-cyan:hover   { border-color:var(--cyan); }
    .card-arrow { color:var(--accent2); font-size:20px; transition:transform .16s; }
    .card:hover .card-arrow { transform:translateX(4px); }
    .card h2 { margin:6px 0 0; font-size:20px; letter-spacing:-.3px; }
    .card p { margin:0; color:var(--muted); font-size:14px; line-height:1.5; }
    .card-tag { margin-top:auto; padding-top:8px; font:500 11.5px/1 ui-monospace,SFMono-Regular,Menlo,monospace;
            color:var(--muted); opacity:.7; }
    .card.soon { border-style:dashed; opacity:.55; }
    .card.soon .card-icon { background:rgba(255,255,255,0.04); color:var(--muted); }
    .empty { text-align:center; color:var(--muted); }
    footer { text-align:center; color:var(--muted); font-size:12.5px; padding:42px 24px 34px;
             font-family:ui-monospace,SFMono-Regular,Menlo,monospace; opacity:.7; }
    footer code { color:var(--accent2); }
  </style>
</head>
<body>
  <nav class="nav">
    <a class="brand" href="/"><span class="dia">◆</span> NEXUX</a>
    <div class="links">
      <a href="/m/trading/">Trading</a>
      <a href="/m/journal/">Diario</a>
    </div>
  </nav>
  <header class="hero">
    <span class="kicker"><span class="pulse"></span> Sistema en línea</span>
    <h1 class="logo">El mercado,<br>bajo control.</h1>
    <p class="tagline"><b>Nexux</b> es el co-piloto personal de Hugo: estructura SMC en vivo,
      filtros validados por backtest y un diario que mide cada hipótesis con datos reales.</p>
    <div class="cta">
      <a class="btn primary" href="/m/trading/">Abrir Trading →</a>
      <a class="btn ghost" href="/m/journal/">Ver el Diario</a>
    </div>
    <div class="facts">
      <div class="fact"><div class="n vi">{{N_MODULES}}</div><div class="k">módulos activos</div></div>
      <div class="fact"><div class="n ok">24/7</div><div class="k">en vivo · Mac mini</div></div>
      <div class="fact"><div class="n">SMC</div><div class="k">multi-timeframe</div></div>
    </div>
  </header>
  <main class="grid">
    {{CARDS}}
  </main>
  <footer>
    nexux.cl · núcleo modular · <code>/health</code> · solo lectura, nunca opera
  </footer>
  <script src="/static/pwa.js" defer></script>
</body>
</html>"""


def load_config() -> dict:
    config_path = os.path.join(ROOT, "config", "nexus.json")
    with open(config_path, "r", encoding="utf-8") as fh:
        return json.load(fh)
