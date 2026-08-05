import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PUBLIC = ROOT / "modules" / "command_center" / "public"


def _run_node(body: str) -> dict:
    script_uri = (PUBLIC / "command-center.js").resolve().as_uri()
    script = f"""
      import({json.dumps(script_uri)}).then((module) => {{
        {body}
      }});
    """
    result = subprocess.run(
        ["node", "--input-type=module", "-e", script],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout)


def test_timeline_no_convierte_baseline_en_evento_y_deduplica() -> None:
    payload = _run_node(
        """
        let now = 1000;
        const timeline = new module.OperationalTimeline({ now: () => now });
        const initial = timeline.observe({
          marketInsight: { state: "neutral", evidence: "2 suben · 2 bajan" },
          readiness: { overall: "ready" },
          positions: { totalPositions: 1 },
        });
        now = 2000;
        const changed = timeline.observe({
          marketInsight: { state: "negative", evidence: "0 suben · 4 bajan" },
          readiness: { overall: "degraded" },
          positions: { totalPositions: 2 },
        });
        const repeated = timeline.observe({
          marketInsight: { state: "negative", evidence: "0 suben · 4 bajan" },
          readiness: { overall: "degraded" },
          positions: { totalPositions: 2 },
        });
        process.stdout.write(JSON.stringify({ initial, changed, repeated }));
        """
    )

    assert payload["initial"] == []
    assert len(payload["changed"]) == 3
    assert len(payload["repeated"]) == 3
    labels = [event["label"] for event in payload["changed"]]
    assert "Pulso: Mixto → Bajista" in labels
    assert "Sistema: Estable → Degradado" in labels
    assert "Posiciones observadas: 1 → 2" in labels


def test_timeline_acepta_solo_senal_del_bot_causal_y_nueva() -> None:
    payload = _run_node(
        """
        let now = 1000;
        const timeline = new module.OperationalTimeline({ now: () => now });
        timeline.observe({ bot: { latestSignal: {
          pair: "BTC", direction: "long", status: "abierta", occurredAtMs: 500
        } } });
        now = 2000;
        timeline.observe({ bot: { latestSignal: {
          pair: "ETH", direction: "short", status: "abierta", occurredAtMs: 3000
        } } });
        now = 4000;
        const accepted = timeline.observe({ bot: { latestSignal: {
          pair: "SOL", direction: "long", status: "abierta", occurredAtMs: 3500
        } } });
        const repeated = timeline.observe({ bot: { latestSignal: {
          pair: "SOL", direction: "long", status: "abierta", occurredAtMs: 3500
        } } });
        process.stdout.write(JSON.stringify({ accepted, repeated }));
        """
    )

    assert len(payload["accepted"]) == 1
    assert payload["accepted"][0]["label"] == "SOL · LONG"
    assert payload["accepted"][0]["detail"] == "Bot: abierta"
    assert payload["accepted"][0]["occurredAtMs"] == 3500
    assert payload["repeated"] == payload["accepted"]


def test_timeline_es_acotada_y_ordenada_por_ocurrencia() -> None:
    payload = _run_node(
        """
        let now = 1000;
        const timeline = new module.OperationalTimeline({
          now: () => now, maxEntries: 2
        });
        timeline.observe({ positions: { totalPositions: 0 } });
        for (const count of [1, 2, 3]) {
          now += 1000;
          timeline.observe({ positions: { totalPositions: count } });
        }
        process.stdout.write(JSON.stringify(timeline.entries()));
        """
    )

    assert [event["occurredAtMs"] for event in payload] == [4000, 3000]
    assert [event["label"] for event in payload] == [
        "Posiciones observadas: 2 → 3",
        "Posiciones observadas: 1 → 2",
    ]


def test_timeline_reutiliza_atencion_sin_panel_nuevo() -> None:
    page = (PUBLIC / "index.html").read_text(encoding="utf-8")
    script = (PUBLIC / "command-center.js").read_text(encoding="utf-8")
    styles = (PUBLIC / "command-center.css").read_text(encoding="utf-8")

    assert page.count('class="attention-panel"') == 1
    assert "operational-timeline-panel" not in page
    assert 'aria-label="Alertas y actividad operacional"' in page
    assert 'data-timeline-active="false"' in page
    assert "class OperationalTimeline" in script
    assert "Posiciones observadas" in script
    assert '.attention-list[data-timeline-active="false"]' in styles
