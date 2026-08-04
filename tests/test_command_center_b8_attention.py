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


def test_b8_reutiliza_superficie_y_no_agrega_controles() -> None:
    page = (PUBLIC / "index.html").read_text(encoding="utf-8")
    script = (PUBLIC / "command-center.js").read_text(encoding="utf-8")
    styles = (PUBLIC / "command-center.css").read_text(encoding="utf-8")

    assert page.count('class="attention-panel"') == 1
    assert 'class="bot-context-panel"' not in page
    panel = page.split('class="attention-panel"', 1)[1].split(
        '<section class="music-panel"', 1
    )[0]
    assert "Atención inmediata" in panel
    assert "solo lectura" in panel
    assert "<button" not in panel
    assert "<a " not in panel
    assert "deriveImmediateAttention" in script
    assert "Macro: sin eventos próximos" in script
    assert 'source.state === "warning"' in script
    assert 'source.state === "critical"' in script
    assert ':has(#attention-state[data-state="normal"]) .attention-list' in styles
    assert ':has(#attention-state[data-state="normal"]) .context-footer' in styles
    assert "totalPnl" not in script.split(
        "export function deriveImmediateAttention", 1
    )[1].split("export class BotContextClient", 1)[0]
