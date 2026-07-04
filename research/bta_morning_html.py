"""Generate a local HTML review page for the BTA TradingView study."""
from __future__ import annotations

import html
import json
import os
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
INV = os.path.join(HERE, "bta_visual_inventory_2026-07-01.json")
BT = os.path.join(HERE, "bta_visual_backtest_results.json")
LIVE_INV = os.path.join(HERE, "bta_live_capture_inventory_2026-07-01.json")
ATLAS = os.path.join(HERE, "bta_historical_navigation_atlas_2026-07-01.json")
OUT = os.path.join(HERE, "bta_morning_review_2026-07-01.html")


def read_json(path):
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def esc(value):
    return html.escape(str(value))


def pills(items, klass="pill"):
    return "".join(f'<span class="{klass}">{esc(item)}</span>' for item in items)


def metric(label, value, sub=""):
    return f"""
    <div class="metric">
      <div class="metric-label">{esc(label)}</div>
      <div class="metric-value">{esc(value)}</div>
      <div class="metric-sub">{esc(sub)}</div>
    </div>
    """


def capture_card(cap):
    conf = cap["confidence"].replace("_", " ")
    labels = pills(cap.get("visible_labels", []), "pill label")
    objects = pills(cap.get("visible_objects", []), "pill object")
    required = pills(cap["nexux_mapping"].get("required_objects", []), "pill required")
    states = pills(cap["nexux_mapping"].get("required_states", []), "pill state")
    file_path = os.path.join(
        "/Users/hugh/crisol/nexux/research/tradingview_bta_screenshots_2026-06-30",
        cap["file"],
    )
    return f"""
    <article class="capture {esc(cap["confidence"])}">
      <a href="{esc(file_path)}"><img src="{esc(file_path)}" alt="{esc(cap["id"])}"></a>
      <div class="capture-body">
        <div class="capture-top">
          <h3>{esc(cap["id"])}</h3>
          <span class="confidence">{esc(conf)}</span>
        </div>
        <p class="role">{esc(cap["visual_role"])}</p>
        <p>{esc(cap["bta_reading"])}</p>
        <div class="group"><strong>Etiquetas</strong><br>{labels or '<span class="muted">sin etiquetas concluyentes</span>'}</div>
        <div class="group"><strong>Objetos visibles</strong><br>{objects}</div>
        <div class="group"><strong>Nexux requerido</strong><br>{required}</div>
        <div class="group"><strong>Estados</strong><br>{states or '<span class="muted">pendiente de clasificar</span>'}</div>
        <p class="gap"><strong>Brecha:</strong> {esc(cap["nexux_mapping"].get("gap", ""))}</p>
        <p class="next"><strong>Siguiente validación:</strong> {esc(cap["next_validation"])}</p>
      </div>
    </article>
    """


def backtest_rows(bt):
    variants = [
        ("POI + liquidez RR>=2", "liq_rr2"),
        ("POI + CDC + liquidez", "cdc_liq"),
        ("Rango + CDC + liquidez", "range_cdc_liq"),
        ("Score visual >= 7", "visual_score7"),
    ]
    rows = []
    for label, key in variants:
        m = bt["variants"][key]["summary"]["trade_metrics"]
        rows.append(f"""
        <tr>
          <td>{esc(label)}</td>
          <td>{m["trades"]}</td>
          <td>{m["win_rate"]}%</td>
          <td>{m["expectancy_R"]}</td>
          <td>{m["profit_factor"]}</td>
          <td>{m["total_R"]}</td>
          <td>{m["max_drawdown_R"]}</td>
        </tr>
        """)
    return "\n".join(rows)


def link_card(title, path, text):
    return f"""
    <a class="link-card" href="{esc(path)}">
      <strong>{esc(title)}</strong>
      <span>{esc(text)}</span>
    </a>
    """


def live_capture_rows(live_inv):
    rows = []
    for cap in live_inv.get("captures", []):
        if cap.get("status") not in {"useful", "duplicate_useful", "partial"}:
            continue
        rows.append(f"""
        <tr>
          <td><a href="{esc(cap['path'])}">{esc(cap['file'])}</a></td>
          <td>{esc(cap['status'])}</td>
          <td>{esc(cap['period'])}</td>
          <td>{esc(cap['visual_role'])}</td>
        </tr>
        """)
    return "\n".join(rows)


def atlas_rows(atlas):
    rows = []
    for year, candidates in atlas.get("top_by_year", {}).items():
        for c in candidates[:4]:
            rows.append(f"""
            <tr>
              <td>{esc(year)}</td>
              <td>{esc(c['time'])}</td>
              <td>{esc(c['dir'])}</td>
              <td>{esc(c['source_tf'])}</td>
              <td>{esc(c['score'])}</td>
              <td>{esc(c['rr_liq'])}</td>
            </tr>
            """)
    return "\n".join(rows)


def main():
    inv = read_json(INV)
    bt = read_json(BT)
    live_inv = read_json(LIVE_INV)
    atlas = read_json(ATLAS)
    captures = inv["captures"]
    conf = Counter(c["confidence"] for c in captures)
    live_counts = Counter(live_inv.get("counts", {}))
    atlas_counts = atlas.get("counts", {})
    required = Counter()
    pending = []
    for cap in captures:
        required.update(cap["nexux_mapping"].get("required_objects", []))
        if cap["confidence"] in {"low", "low_medium", "medium"}:
            pending.append(cap)

    contact_sheet = inv["meta"]["contact_sheet"]
    cards = "\n".join(capture_card(cap) for cap in captures)
    required_rows = "\n".join(
        f"<tr><td>{esc(k)}</td><td>{v}</td></tr>" for k, v in sorted(required.items())
    )
    pending_rows = "\n".join(
        f"<tr><td>{esc(cap['id'])}</td><td>{esc(cap['confidence'])}</td><td>{esc(cap['next_validation'])}</td></tr>"
        for cap in pending
    )
    playbook = os.path.join(HERE, "bta_operational_playbook_2026-07-01.md")
    atlas_md = os.path.join(HERE, "bta_historical_navigation_atlas_2026-07-01.md")
    live_md = os.path.join(HERE, "bta_live_capture_inventory_2026-07-01.md")
    status_md = os.path.join(HERE, "bta_goal_completion_status_2026-07-01.md")

    html_text = f"""<!doctype html>
<html lang="es">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>BTA TradingView vs Nexux - Revisión</title>
  <style>
    :root {{
      --bg: #f4f2ed;
      --ink: #1f2428;
      --muted: #66706d;
      --line: #d8d4ca;
      --panel: #fffdf8;
      --accent: #0f766e;
      --warn: #a16207;
      --bad: #991b1b;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      background: var(--bg);
      color: var(--ink);
      font: 15px/1.45 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }}
    header {{
      padding: 32px 40px 24px;
      border-bottom: 1px solid var(--line);
      background: #ebe8df;
    }}
    h1, h2, h3 {{ margin: 0; line-height: 1.15; }}
    h1 {{ font-size: 34px; }}
    h2 {{ margin: 34px 0 14px; font-size: 22px; }}
    h3 {{ font-size: 17px; }}
    main {{ padding: 0 40px 40px; max-width: 1480px; margin: 0 auto; }}
    .sub {{ color: var(--muted); margin-top: 8px; }}
    .metrics {{
      display: grid;
      grid-template-columns: repeat(4, minmax(160px, 1fr));
      gap: 12px;
      margin-top: 18px;
    }}
    .metric {{
      background: var(--panel);
      border: 1px solid var(--line);
      padding: 14px;
      border-radius: 8px;
    }}
    .metric-label {{ color: var(--muted); font-size: 13px; }}
    .metric-value {{ font-size: 26px; font-weight: 700; margin-top: 2px; }}
    .metric-sub {{ color: var(--muted); font-size: 12px; margin-top: 2px; }}
    .notice {{
      background: #fff7ed;
      border: 1px solid #fed7aa;
      color: #7c2d12;
      padding: 14px 16px;
      border-radius: 8px;
      margin-top: 18px;
    }}
    .sheet {{
      width: 100%;
      max-width: 1180px;
      border: 1px solid var(--line);
      border-radius: 8px;
      display: block;
      background: white;
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      overflow: hidden;
    }}
    th, td {{
      padding: 10px 12px;
      border-bottom: 1px solid var(--line);
      text-align: left;
      vertical-align: top;
    }}
    th {{ background: #ece7dd; font-size: 13px; }}
    tr:last-child td {{ border-bottom: 0; }}
    .captures {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(360px, 1fr));
      gap: 16px;
    }}
    .links {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
      gap: 12px;
    }}
    .link-card {{
      display: block;
      text-decoration: none;
      color: var(--ink);
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 14px;
    }}
    .link-card strong {{ display: block; margin-bottom: 5px; }}
    .link-card span {{ color: var(--muted); font-size: 13px; }}
    .capture {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      overflow: hidden;
    }}
    .capture img {{
      width: 100%;
      aspect-ratio: 960 / 832;
      object-fit: cover;
      border-bottom: 1px solid var(--line);
      background: #111;
      display: block;
    }}
    .capture-body {{ padding: 14px; }}
    .capture-top {{ display: flex; gap: 8px; justify-content: space-between; align-items: start; }}
    .confidence {{
      white-space: nowrap;
      border: 1px solid var(--line);
      border-radius: 999px;
      padding: 3px 8px;
      color: var(--muted);
      font-size: 12px;
    }}
    .role {{ color: var(--accent); font-weight: 650; margin: 7px 0; }}
    .group {{ margin-top: 10px; }}
    .pill {{
      display: inline-block;
      border: 1px solid var(--line);
      border-radius: 999px;
      padding: 3px 8px;
      margin: 4px 4px 0 0;
      background: #f8f6ef;
      font-size: 12px;
    }}
    .required {{ border-color: #99f6e4; background: #ecfdf5; }}
    .state {{ border-color: #bfdbfe; background: #eff6ff; }}
    .label {{ border-color: #fde68a; background: #fffbeb; }}
    .object {{ border-color: #ddd6fe; background: #f5f3ff; }}
    .gap, .next {{ color: var(--muted); }}
    .muted {{ color: var(--muted); }}
    footer {{
      padding: 20px 40px 36px;
      color: var(--muted);
      border-top: 1px solid var(--line);
    }}
    @media (max-width: 760px) {{
      header, main, footer {{ padding-left: 18px; padding-right: 18px; }}
      .metrics {{ grid-template-columns: 1fr 1fr; }}
    }}
  </style>
</head>
<body>
  <header>
    <h1>BTA TradingView vs Nexux</h1>
    <div class="sub">BTCUSDT.P M15 · revisión matinal · estado provisional hasta re-navegar el chart limpio</div>
    <div class="metrics">
      {metric("Capturas inventariadas", len(captures), "9 archivos JPG locales")}
      {metric("Capturas vivas útiles", live_counts.get("useful", 0), "inventario complementario")}
      {metric("POI+CDC+liquidez", "PF 1.99", "272 trades · +0.700R")}
      {metric("Atlas navegación", atlas_counts.get("candidate_count", 0), "candidatos históricos")}
    </div>
    <div class="notice">
      Corrección importante: las capturas antiguas 2025-04-16, 2025-08-01 y 2025-11-05 quedaron visualmente iguales o muy parecidas. Sirven para reconocer la capa zigzag, no como recorrido histórico independiente.
    </div>
  </header>
  <main>
    <section>
      <h2>Lectura ejecutiva</h2>
      <p>La estrategia visible del profe no es “tocar cualquier OB/FVG”. Lo observado apunta a una cadena: rango, premium/discount, POI, CDC, reacción, liquidez objetivo y estado de zona. En datos, el salto fuerte aparece al exigir CDC + liquidez.</p>
    </section>

    <section>
      <h2>Documentos para abrir primero</h2>
      <div class="links">
        {link_card("Playbook operativo", playbook, "Reglas observadas: POI, CDC, liquidez, SwingLeg y estados de zona.")}
        {link_card("Inventario en vivo", live_md, "63 PNG auditados, 7 útiles independientes y descartes documentados.")}
        {link_card("Atlas histórico", atlas_md, "339 candidatos y 88 objetivos mensuales para re-navegar 2024/2025.")}
        {link_card("Estado de completitud", status_md, "Qué está listo y qué falta para cerrar la misión completa.")}
      </div>
    </section>

    <section>
      <h2>Lámina de capturas</h2>
      <a href="{esc(contact_sheet)}"><img class="sheet" src="{esc(contact_sheet)}" alt="Contact sheet BTA"></a>
    </section>

    <section>
      <h2>Backtest de filtros</h2>
      <table>
        <thead><tr><th>Filtro</th><th>Trades</th><th>WR</th><th>ExpR</th><th>PF</th><th>Total R</th><th>DD</th></tr></thead>
        <tbody>{backtest_rows(bt)}</tbody>
      </table>
    </section>

    <section>
      <h2>Re-navegación en vivo</h2>
      <table>
        <thead><tr><th>Archivo</th><th>Estado</th><th>Periodo</th><th>Rol visual</th></tr></thead>
        <tbody>{live_capture_rows(live_inv)}</tbody>
      </table>
    </section>

    <section>
      <h2>Atlas histórico para navegar limpio</h2>
      <p class="muted">Estas fechas son candidatas generadas por Nexux/backtest. Sólo cuentan como evidencia si se confirman luego con captura visual del chart del profe.</p>
      <table>
        <thead><tr><th>Año</th><th>Fecha</th><th>Dirección</th><th>TF</th><th>Score</th><th>RR</th></tr></thead>
        <tbody>{atlas_rows(atlas)}</tbody>
      </table>
    </section>

    <section>
      <h2>Objetos que Nexux necesita</h2>
      <table>
        <thead><tr><th>Objeto</th><th>Apariciones en inventario</th></tr></thead>
        <tbody>{required_rows}</tbody>
      </table>
    </section>

    <section>
      <h2>Capturas y zonas</h2>
      <div class="captures">{cards}</div>
    </section>

    <section>
      <h2>Pendientes para cerrar la misión</h2>
      <table>
        <thead><tr><th>Captura</th><th>Confianza</th><th>Siguiente validación</th></tr></thead>
        <tbody>{pending_rows}</tbody>
      </table>
    </section>
  </main>
  <footer>
    Archivos fuente: bta_visual_inventory_2026-07-01.json, bta_live_capture_inventory_2026-07-01.json, bta_historical_navigation_atlas_2026-07-01.json, bta_visual_backtest_results.json.
  </footer>
</body>
</html>
"""
    with open(OUT, "w", encoding="utf-8") as fh:
        fh.write(html_text)
    print(OUT)


if __name__ == "__main__":
    main()
