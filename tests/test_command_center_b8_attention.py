import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PUBLIC = ROOT / "modules" / "command_center" / "public"


def test_b8_prioriza_solo_alertas_operacionales_verificables() -> None:
    script_uri = (PUBLIC / "command-center.js").resolve().as_uri()
    node = f"""
      import({json.dumps(script_uri)}).then((module) => {{
        const now = 1800000000000;
        const ready = {{ overall: "ready", services: [] }};
        const positions = {{ accounts: [
          {{ id: "principal", state: "ready" }},
          {{ id: "bot", state: "ready" }}
        ] }};
        const bot = {{ state: "ready", severity: "normal" }};
        const macro = {{ status: "empty", event: null }};
        const normal = module.deriveImmediateAttention({{
          readiness: ready, positions, bot, macro, now
        }});
        const macroAlert = module.deriveImmediateAttention({{
          readiness: ready, positions, bot,
          macro: {{ status: "ready", event: {{
            title: "FOMC", ts: now / 1000 + 10 * 60
          }} }},
          now
        }});
        const failed = module.deriveImmediateAttention({{
          readiness: {{ overall: "failed", services: [] }},
          positions: {{ accounts: [
            {{ id: "principal", state: "stale" }},
            {{ id: "bot", state: "ready" }}
          ] }},
          bot: {{ state: "degraded", severity: "warning" }},
          macro,
          now
        }});
        process.stdout.write(JSON.stringify({{ normal, macroAlert, failed }}));
      }});
    """
    result = subprocess.run(
        ["node", "--input-type=module", "-e", node],
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(result.stdout)

    assert payload["normal"]["state"] == "normal"
    assert payload["normal"]["count"] == 0
    assert payload["normal"]["detail"] == "Macro: sin eventos próximos"
    assert [item["label"] for item in payload["normal"]["items"]] == [
        "Sistema", "Binance", "Macro", "Bot"
    ]
    assert payload["normal"]["items"][0]["state"] == "normal"
    assert payload["macroAlert"]["state"] == "critical"
    assert payload["macroAlert"]["summary"] == "FOMC · 10 min."
    assert payload["failed"]["state"] == "critical"
    assert payload["failed"]["count"] == 3
    assert payload["failed"]["detail"] == "Sistema · 3 alertas"


def test_calendario_reutiliza_superficie_de_atencion_sin_agregar_panel() -> None:
    page = (PUBLIC / "index.html").read_text(encoding="utf-8")
    script = (PUBLIC / "command-center.js").read_text(encoding="utf-8")
    styles = (PUBLIC / "command-center.css").read_text(encoding="utf-8")

    assert page.count('class="attention-panel"') == 1
    assert "data-calendar-panel" in page
    assert 'class="bot-context-panel"' not in page
    panel = page.split('class="attention-panel"', 1)[1].split(
        '<section class="music-panel"', 1
    )[0]
    assert "Calendario" in panel
    assert "solo lectura" in panel
    assert panel.count("<button") == 3
    assert 'id="calendar-previous"' in panel
    assert 'id="calendar-today"' in panel
    assert 'id="calendar-next"' in panel
    assert "<a " not in panel
    assert "deriveImmediateAttention" in script
    assert "Macro: sin eventos próximos" in script
    assert 'source.state === "warning"' in script
    assert 'source.state === "critical"' in script
    assert '.calendar-alert[data-state="normal"]' in styles
    assert '.app-shell[data-attention-mode="elevated"] .context-rail' in styles
    assert "-webkit-line-clamp: 2" in styles
    assert ".calendar-grid" in styles
    selection_styles = styles.split("#calendar-selection", 1)[1].split("}", 1)[0]
    assert "font-size: 20px" in selection_styles
    assert "white-space: normal" in selection_styles
    footer_styles = styles.rsplit(".calendar-footer {", 1)[1].split("}", 1)[0]
    assert "min-height: 52px" in footer_styles
    assert "totalPnl" not in script.split(
        "export function deriveImmediateAttention", 1
    )[1].split("export class BotContextClient", 1)[0]


def test_calendario_distingue_actividad_personal_y_macro() -> None:
    page = (PUBLIC / "index.html").read_text(encoding="utf-8")
    script = (PUBLIC / "command-center.js").read_text(encoding="utf-8")
    styles = (PUBLIC / "command-center.css").read_text(encoding="utf-8")
    native = (
        ROOT / "agents" / "macos" / "CommandCenterShell" / "main.swift"
    ).read_text(encoding="utf-8")
    plist = (
        ROOT / "agents" / "macos" / "CommandCenterShell" / "Info.plist"
    ).read_text(encoding="utf-8")

    assert 'id="calendar-grid"' in page
    assert 'className: "personal"' in script
    assert 'className: "macro"' in script
    assert 'type: "calendarMonth"' in script
    assert 'type: "openCalendar"' in script
    assert "if (this.native)" in script
    assert "this.request(false)" in script
    assert "this.selectedDateKey = this.todayKey" in script
    assert "this.selectedDateKey = cell.key" in script
    assert "selectedPersonal = personalByDay.get(this.selectedDateKey)" in script
    assert "const selectedLabels = [...new Map(" in script
    assert "formatCalendarEventTime(event)" in script
    assert 'row.className = "calendar-event-summary"' in script
    assert '"Sin eventos para hoy"' in script
    assert '.calendar-day[data-selected="true"] span' in styles
    assert ".calendar-dots .personal { background: var(--info); }" in styles
    assert ".calendar-dots .macro { background: var(--warning); }" in styles
    assert "import EventKit" in native
    assert "requestFullAccessToEvents" in native
    assert 'tell application "Calendar"' in native
    assert "view calendar at targetDate" in native
    assert 'contains("TCL")' in native
    assert "NSCalendarsFullAccessUsageDescription" in plist


def test_calendario_genera_seis_semanas_desde_lunes() -> None:
    script_uri = (PUBLIC / "command-center.js").resolve().as_uri()
    node = f"""
      import({json.dumps(script_uri)}).then((module) => {{
        const cells = module.calendarMonthCells(2026, 7);
        process.stdout.write(JSON.stringify({{
          length: cells.length,
          first: cells[0],
          august1: cells.find((cell) => cell.key === "2026-08-01"),
          label: module.formatCalendarMonth(2026, 7),
          dateKey: module.localCalendarDateKey(new Date(2026, 7, 15, 23, 59))
        }}));
      }});
    """
    result = subprocess.run(
        ["node", "--input-type=module", "-e", node],
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(result.stdout)
    assert payload["length"] == 42
    assert payload["first"]["key"] == "2026-07-27"
    assert payload["august1"]["currentMonth"] is True
    assert payload["label"] == "Agosto 2026"
    assert payload["dateKey"] == "2026-08-15"


def test_calendario_muestra_todo_el_dia_y_hora_real() -> None:
    script_uri = (PUBLIC / "command-center.js").resolve().as_uri()
    node = f"""
      import({json.dumps(script_uri)}).then((module) => {{
        const timed = {{
          title: "Hora con Doctor Ibarra",
          start_ms: new Date(2026, 7, 20, 16, 30).getTime(),
          all_day: false
        }};
        const allDay = {{
          title: "Asunción de la Virgen",
          start_ms: new Date(2026, 7, 15).getTime(),
          all_day: true
        }};
        process.stdout.write(JSON.stringify({{
          timed: module.formatCalendarEventLabel(timed),
          allDay: module.formatCalendarEventLabel(allDay)
        }}));
      }});
    """
    result = subprocess.run(
        ["node", "--input-type=module", "-e", node],
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(result.stdout)
    assert payload["timed"] == "16:30 · Hora con Doctor Ibarra"
    assert payload["allDay"] == "Todo el día · Asunción de la Virgen"


def test_calendario_sincroniza_el_dia_y_mes_al_cruzar_medianoche() -> None:
    script = (PUBLIC / "command-center.js").read_text(encoding="utf-8")
    assert "this.todayKey = localCalendarDateKey(now)" in script
    assert "setInterval(() => this.syncCalendarDay(), 30_000)" in script
    assert "if (nextKey === this.todayKey) return" in script
    assert "this.year = now.getFullYear()" in script
    assert "this.month = now.getMonth()" in script
    assert "this.personalEvents = []" in script
    assert "this.request()" in script


def test_temporalidad_y_contador_pertenecen_al_command_center() -> None:
    page = (PUBLIC / "index.html").read_text(encoding="utf-8")
    script = (PUBLIC / "command-center.js").read_text(encoding="utf-8")
    adapter = (PUBLIC / "tradingview-spike.js").read_text(encoding="utf-8")
    for interval in ("1m", "3m", "5m", "15m", "30m", "45m", "1h", "2h", "3h", "4h", "1D", "1W"):
        assert f'<option value="{interval}"' in page
    assert 'id="chart-interval-select"' in page
    assert 'id="candle-countdown"' in page
    assert "formatCandleCountdown" in script
    assert "interval: selectedChartInterval" in script
    assert "hide_top_toolbar: true" in adapter


def test_contador_de_vela_respeta_la_temporalidad_seleccionada() -> None:
    script_uri = (PUBLIC / "command-center.js").resolve().as_uri()
    node = f"""
      import({json.dumps(script_uri)}).then((module) => {{
        process.stdout.write(JSON.stringify({{
          minute: module.formatCandleCountdown("1m", 30_000),
          halfHour: module.formatCandleCountdown("30m", 1_000),
          hour: module.formatCandleCountdown("1h", 30 * 60 * 1000),
          fourHours: module.formatCandleCountdown("4h", 30 * 60 * 1000),
          week: module.formatCandleCountdown("1W", Date.UTC(2026, 7, 15, 12)),
          invalid: module.formatCandleCountdown("8h", 0),
        }}));
      }});
    """
    result = subprocess.run(
        ["node", "--input-type=module", "-e", node],
        check=True,
        capture_output=True,
        text=True,
    )
    assert json.loads(result.stdout) == {
        "minute": "00:30",
        "halfHour": "29:59",
        "hour": "30:00",
        "fourHours": "03:30:00",
        "week": "1d 12:00:00",
        "invalid": "--:--",
    }
