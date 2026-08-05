import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PUBLIC = ROOT / "modules" / "command_center" / "public"


def _health(services: list[dict]) -> dict:
    script_uri = (PUBLIC / "command-center.js").resolve().as_uri()
    script = f"""
      import({json.dumps(script_uri)}).then((module) => {{
        const result = module.deriveOperationalHealth({{
          services: {json.dumps(services)}
        }});
        process.stdout.write(JSON.stringify(result));
      }});
    """
    result = subprocess.run(
        ["node", "--input-type=module", "-e", script],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout)


def _services(**overrides: str) -> list[dict]:
    names = {
        "gateway": "Gateway",
        "event-bus": "EventBus",
        "snapshot": "Snapshot",
        "internet": "Internet",
        "trading": "Trading",
    }
    return [
        {
            "id": service_id,
            "name": name,
            "state": overrides.get(service_id, "ready"),
            "evidence": f"evidencia {service_id}",
        }
        for service_id, name in names.items()
    ]


def test_health_estable_exige_todos_los_servicios_esenciales() -> None:
    health = _health(_services())

    assert health["state"] == "stable"
    assert health["label"] == "Estable"
    assert health["reasons"] == []
    assert health["explanation"] == "5 servicios esenciales verificados."


def test_health_usa_precedencia_explicita_y_no_score() -> None:
    degraded = _health(_services(snapshot="degraded"))
    critical = _health(_services(snapshot="degraded", gateway="failed"))
    unknown = _health(_services(trading="unknown"))

    assert degraded["state"] == "degraded"
    assert degraded["reasons"][0]["service"] == "Snapshot"
    assert "evidencia snapshot" in degraded["explanation"]
    assert critical["state"] == "critical"
    assert [reason["service"] for reason in critical["reasons"]] == ["Gateway"]
    assert unknown["state"] == "unknown"
    assert unknown["label"] == "Desconocido"
    for result in (degraded, critical, unknown):
        assert "score" not in result


def test_health_desconocido_si_falta_un_servicio_esencial() -> None:
    health = _health(_services()[:-1])

    assert health["state"] == "unknown"
    assert health["observedCount"] == 4
    assert health["requiredCount"] == 5
    assert health["explanation"] == "4/5 servicios esenciales observados."


def test_explainability_reutiliza_evidencia_visible() -> None:
    script = (PUBLIC / "command-center.js").read_text(encoding="utf-8")

    assert 'overall.title = health.explanation' in script
    assert 'item.title = service.evidence' in script
    assert 'summary.title = attention.explanation' in script
    assert 'insightNode.title = insight.evidence' in script
    assert "Sistema, Binance, Macro y Bot no publican una alerta activa." in script
