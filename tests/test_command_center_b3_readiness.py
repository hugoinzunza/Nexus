import json
import subprocess
from pathlib import Path

from modules.command_center.contracts import CONTRACT_V1_FINGERPRINT
from modules.command_center.module_registry import command_center_module_registry


ROOT = Path(__file__).resolve().parents[1]
PUBLIC = ROOT / "modules" / "command_center" / "public"


def _run_readiness_cases() -> dict:
    script_uri = (PUBLIC / "command-center.js").resolve().as_uri()
    node = f"""
      import({json.dumps(script_uri)}).then((module) => {{
        const now = 1_000_000;
        const envelope = (staleAt, expiresAt) => ({{
          severity: "normal",
          stale_at: staleAt,
          expires_at: expiresAt,
          payload: {{ state: {{ freshness: "live" }} }}
        }});
        const command = (connection = "ready", staleAt = now + 30_000,
          expiresAt = now + 60_000) => ({{
          connection,
          snapshotAt: now,
          readModel: {{ "system.session": envelope(staleAt, expiresAt) }}
        }});
        const health = (lastUpdate = now, upstream = true) => ({{
          status: "ready",
          health: {{
            status: "ok",
            modules: [
              {{
                slug: "trading",
                status: upstream ? "ok" : "degradado",
                upstream_ok: upstream,
                last_update_ms: lastUpdate
              }},
              {{
                slug: "command-center",
                event_bus: {{ status: "ready" }},
                module_registry: {{
                  modules: [{{
                    module_id: "media.controller",
                    factory_attached: false,
                    lifecycle: "declared"
                  }}]
                }}
              }}
            ]
          }}
        }});
        const derive = (commandState, healthState = health(), online = true) =>
          module.deriveOperationalReadiness({{
            commandState, healthState, online, now
          }});
        const ready = derive(command());
        const normalRefreshJitter = derive(command(), health(now - 35_000));
        const delayedTrading = derive(command(), health(now - 61_000));
        const staleTrading = derive(command(), health(now - 121_000));
        const awaitingHealth = derive(command(), {{
          status: "loading", health: null
        }});
        const staleSnapshot = derive(command("ready", now - 1, now + 30_000));
        const transientReconnect = derive({{
          ...command("degraded"), connectionDegradedAt: now - 2_000
        }});
        const persistentReconnect = derive({{
          ...command("degraded"), connectionDegradedAt: now - 9_000
        }});
        const disconnected = derive(command("disconnected"));
        const offline = derive(command(), health(), false);
        process.stdout.write(JSON.stringify({{
          ready,
          normalRefreshJitter: normalRefreshJitter.overall,
          delayedTrading: delayedTrading.overall,
          staleTrading: staleTrading.overall,
          awaitingHealth: awaitingHealth.overall,
          staleSnapshot: staleSnapshot.overall,
          transientReconnect: transientReconnect.overall,
          persistentReconnect: persistentReconnect.overall,
          disconnected: disconnected.overall,
          offline: offline.overall
        }}));
      }});
    """
    result = subprocess.run(
        ["node", "--input-type=module", "-e", node],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout)


def test_b3_reemplaza_panel_existente_sin_cambiar_layout_general() -> None:
    page = (PUBLIC / "index.html").read_text(encoding="utf-8")
    css = (PUBLIC / "command-center.css").read_text(encoding="utf-8")

    assert page.count('class="status-panel"') == 0
    assert page.count('id="readiness-list"') == 1
    assert 'id="system-title"' not in page
    assert 'id="primary-value"' not in page
    assert 'class="macro-panel"' not in page
    assert 'class="music-panel"' in page
    assert "grid-template-columns: repeat(5, minmax(90px, 1fr));" in css
    assert 'grid-area: attention' in css
    assert 'grid-area: music' in css
    assert '"attention"' in css
    assert '"positions"' in css


def test_b3_consume_salud_solo_lectura_y_no_inventa_integraciones() -> None:
    script = (PUBLIC / "command-center.js").read_text(encoding="utf-8")

    assert 'const HEALTH_URL = "/health"' in script
    assert "OperationalHealthClient" in script
    assert script.count('method: "POST"') == 1
    assert '"/m/command-center/api/media-command"' in script
    assert '{ id: "agent", name: "Agente macOS", state: "unknown" }' in script
    assert '{ id: "ai", name: "IA", state: "unknown" }' in script
    assert "media?.factory_attached" in script
    assert command_center_module_registry().stats()["attached_factories"] == 0


def test_b3_nucleo_ready_no_oculta_unknown_opcionales() -> None:
    result = _run_readiness_cases()
    ready = result["ready"]
    states = {service["id"]: service["state"] for service in ready["services"]}

    assert ready["overall"] == "ready"
    assert states == {
        "gateway": "ready",
        "event-bus": "ready",
        "snapshot": "ready",
        "internet": "ready",
        "trading": "ready",
        "agent": "unknown",
        "music": "unknown",
        "ai": "unknown",
    }


def test_b3_falla_cerrado_en_senales_esenciales() -> None:
    result = _run_readiness_cases()

    assert result["normalRefreshJitter"] == "ready"
    assert result["delayedTrading"] == "degraded"
    assert result["staleTrading"] == "failed"
    assert result["awaitingHealth"] == "unknown"
    assert result["staleSnapshot"] == "degraded"
    assert result["transientReconnect"] == "ready"
    assert result["persistentReconnect"] == "degraded"
    assert result["disconnected"] == "failed"
    assert result["offline"] == "failed"


def test_b3_preserva_wire_abi_y_vocabulario_acotado() -> None:
    script = (PUBLIC / "command-center.js").read_text(encoding="utf-8")

    assert CONTRACT_V1_FINGERPRINT in script
    for state in ("ready", "degraded", "failed", "unknown"):
        assert f'{state}: "' in script
    for excluded in ("weather", "clima", "feed social"):
        assert excluded not in script.lower()


def test_b3_documenta_semantica_y_gate_perceptual() -> None:
    rfc = (ROOT / "docs" / "RFC_COMMAND_CENTER.md").read_text(encoding="utf-8")
    validation = (ROOT / "docs" / "VALIDATION_LOG.md").read_text(
        encoding="utf-8"
    )

    assert "VAL-0019" in rfc
    assert "30 segundos" in rfc
    assert "120 segundos" in rfc
    assert "VAL-0019" in validation
    assert "PENDIENTE perceptualmente" in validation
    assert "command-center-b3-arzopa-physical.png" in validation
