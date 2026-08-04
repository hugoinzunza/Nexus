import json
import re
import subprocess
from pathlib import Path

from core.module_base import ModuleContext
from modules.command_center.contracts import CONTRACT_V1_FINGERPRINT
from modules.command_center.module import CommandCenterModule
from modules.command_center.module_registry import command_center_module_registry
from modules.trading import claude_brief, dashboard
from modules.trading.module import TradingModule


ROOT = Path(__file__).resolve().parents[1]
PUBLIC = ROOT / "modules" / "command_center" / "public"


def _hex_rgb(value: str) -> tuple[float, float, float]:
    value = value.lstrip("#")
    return tuple(int(value[index : index + 2], 16) / 255 for index in (0, 2, 4))


def _luminance(value: str) -> float:
    channels = []
    for channel in _hex_rgb(value):
        channels.append(
            channel / 12.92
            if channel <= 0.04045
            else ((channel + 0.055) / 1.055) ** 2.4
        )
    return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2]


def _contrast(left: str, right: str) -> float:
    first, second = sorted((_luminance(left), _luminance(right)), reverse=True)
    return (first + 0.05) / (second + 0.05)


def _tokens() -> dict[str, str]:
    css = (PUBLIC / "command-center.css").read_text(encoding="utf-8")
    return dict(re.findall(r"--([a-z0-9-]+):\s*(#[0-9a-fA-F]{6});", css))


def test_shell_publica_assets_y_estados_operacionales() -> None:
    page = (PUBLIC / "index.html").read_text(encoding="utf-8")
    script = (PUBLIC / "command-center.js").read_text(encoding="utf-8")

    assert 'src="./command-center.js"' in page
    assert 'href="./command-center.css"' in page
    for state in (
        "loading",
        "ready",
        "degraded",
        "stale",
        "expired",
        "disconnected",
    ):
        assert state in script
    assert "/m/command-center/api/snapshot" in script
    assert "/m/command-center/ws" in script
    assert '"gateway.resync-required"' in script
    assert "mergePatch" in script
    assert "#scheduleFreshnessRefresh" in script
    assert "current.observed_at > incoming.observed_at" in script


def test_experience_layer_usa_lenguaje_operacional_y_footer_en_calma() -> None:
    page = (PUBLIC / "index.html").read_text(encoding="utf-8")
    script = (PUBLIC / "command-center.js").read_text(encoding="utf-8")
    styles = (PUBLIC / "command-center.css").read_text(encoding="utf-8")

    assert "Pulso de mercado" in page
    assert 'class="status-footer" data-state="unknown"' in page
    assert 'ready: "Listo"' in script
    assert 'failed: "Falló"' in script
    assert 'unknown: "Sin datos"' in script
    assert 'document.querySelector(".status-footer").dataset.state' in script
    assert '.status-footer[data-state="ready"] .provider-status' in styles
    assert '.status-footer[data-state="ready"] .readiness-list' in styles


def test_shell_fija_el_abi_y_no_agrega_superficie_de_comandos() -> None:
    script = (PUBLIC / "command-center.js").read_text(encoding="utf-8")

    assert CONTRACT_V1_FINGERPRINT in script
    assert script.count('method: "POST"') == 1
    assert '"/m/command-center/api/media-command"' in script
    assert '"/m/bot/' not in script
    assert '"bot/api/' not in script
    assert "market_order" not in script
    assert command_center_module_registry().stats()["attached_factories"] == 0


def test_b2_agrega_un_contexto_macro_y_salto_honesto_a_tradingview() -> None:
    page = (PUBLIC / "index.html").read_text(encoding="utf-8")
    script = (PUBLIC / "command-center.js").read_text(encoding="utf-8")

    assert 'class="macro-panel"' not in page
    assert 'id="macro-event"' not in page
    assert 'rel="manifest" href="./manifest.webmanifest"' in page
    assert 'id="module-list"' not in page
    assert 'id="full-analysis-link"' in page
    assert "https://www.tradingview.com/chart/?symbol=" in page
    assert 'target="_blank"' in page
    assert 'rel="noopener noreferrer"' in page
    assert (
        'const MACRO_URL = "/m/trading/api/dashboard?translate=0"' in script
    )
    assert "selectNextHighImpact" in script
    assert "formatMacroCountdown" in script
    assert script.count('method: "POST"') == 1
    assert '"/m/command-center/api/media-command"' in script


def test_shell_declara_modo_aplicacion_y_lanzador_sin_barra() -> None:
    page = (PUBLIC / "index.html").read_text(encoding="utf-8")
    manifest = (PUBLIC / "manifest.webmanifest").read_text(encoding="utf-8")
    launcher = (ROOT / "tools" / "open_command_center.command").read_text(
        encoding="utf-8"
    )

    assert 'rel="manifest" href="./manifest.webmanifest"' in page
    assert '"display": "standalone"' in manifest
    assert 'open -na "$APP" --args "$URL"' in launcher
    native = (
        ROOT / "agents" / "macos" / "CommandCenterShell" / "main.swift"
    ).read_text(encoding="utf-8")
    assert "styleMask: [.borderless]" in native
    assert "WKWebView" in native
    assert ".hideMenuBar" in native


def test_b2_seleccion_macro_es_causal_y_no_inventa_impacto() -> None:
    script_uri = (PUBLIC / "command-center.js").resolve().as_uri()
    node = f"""
      import({json.dumps(script_uri)}).then((module) => {{
        const events = [
          {{ title: "pasado", impact: "High", ts: 90 }},
          {{ title: "medio", impact: "Medium", ts: 105 }},
          {{ title: "posterior", impact: "High", ts: 120 }},
          {{ title: "primero", impact: "High", ts: 110 }}
        ];
        const result = {{
          selected: module.selectNextHighImpact(events, 100)?.title,
          minutes: module.formatMacroCountdown(160, 100000),
          hours: module.formatMacroCountdown(3700, 100000)
        }};
        process.stdout.write(JSON.stringify(result));
      }});
    """
    result = subprocess.run(
        ["node", "--input-type=module", "-e", node],
        check=True,
        capture_output=True,
        text=True,
    )

    assert json.loads(result.stdout) == {
        "selected": "primero",
        "minutes": "1 min",
        "hours": "1 h",
    }


def test_dashboard_no_oculta_eventos_futuros_tras_ocho_recientes(
    monkeypatch,
) -> None:
    calls = []

    def calendar(*, max_keep):
        calls.append(max_keep)
        return [{"title": "próximo", "impact": "High", "ts": 200}]

    monkeypatch.setattr(dashboard.news, "week_key_events", calendar)
    monkeypatch.setattr(dashboard, "_global", lambda: {})
    monkeypatch.setattr(dashboard, "_markets", lambda: [])
    monkeypatch.setattr(dashboard, "_fear_greed", lambda: None)
    monkeypatch.setattr(dashboard, "_news_feed", lambda: [])
    monkeypatch.setattr(dashboard.regime, "vix_now", lambda: None)

    result = dashboard.get_dashboard()

    assert calls == [24]
    assert result["calendar"][0]["title"] == "próximo"


def test_lectura_macro_no_activa_traduccion_con_claude(monkeypatch) -> None:
    translations = []
    payload = {
        "generated_at_ms": 100,
        "calendar": [],
        "news": [{"title": "English title", "lang": "en"}],
    }
    monkeypatch.setattr(dashboard, "get_dashboard", lambda: payload.copy())
    monkeypatch.setattr(
        claude_brief,
        "translate_titles",
        lambda titles: translations.append(titles) or {},
    )
    module = object.__new__(TradingModule)

    status, _, _ = module.api("dashboard", {"translate": "0"})
    assert status == 200
    assert translations == []

    module.api("dashboard", {})
    assert translations == [["English title"]]


def test_tokens_cumplen_contraste_minimo_en_superficie_objetivo() -> None:
    tokens = _tokens()

    assert _contrast(tokens["text-1"], tokens["bg"]) >= 7
    assert _contrast(tokens["text-2"], tokens["surface-1"]) >= 4.5
    assert _contrast(tokens["text-3"], tokens["surface-1"]) >= 4.5
    for state in ("info", "success", "warning", "danger", "unknown"):
        assert _contrast(tokens[state], tokens["surface-1"]) >= 4.5


def test_documentacion_registra_hardware_y_tokens_sin_inventar_ergonomia() -> None:
    viewport = (ROOT / "docs" / "VIEWPORT_SPECIFICATION.md").read_text(
        encoding="utf-8"
    )
    foundations = (ROOT / "docs" / "DESIGN_SYSTEM_FOUNDATIONS.md").read_text(
        encoding="utf-8"
    )

    assert "1920 × 1080" in viewport
    assert "60 Hz" in viewport
    assert "Distancia de observación | 80–90 cm" in viewport
    assert "Ángulo de mirada | Pendiente" in viewport
    assert "Superficie objetivo" in foundations
    assert "B2 perceptualmente aprobada" in foundations
    assert "`#111519`" in foundations
    assert "`loading`" in foundations
    assert "`disconnected`" in foundations
    findings = (ROOT / "docs" / "COMMAND_CENTER_B1_FINDINGS.md").read_text(
        encoding="utf-8"
    )
    assert "aprobado técnica y perceptualmente" in findings
    assert "VAL-0017" in (
        ROOT / "docs" / "VALIDATION_LOG.md"
    ).read_text(encoding="utf-8")
    validation = (ROOT / "docs" / "VALIDATION_LOG.md").read_text(
        encoding="utf-8"
    )
    assert "VAL-0017 APROBADO" in validation
    assert "Distancia | 80–90 cm" in validation
    assert "Sprint B2 autorizado" in validation
    assert "VAL-0018" in validation
    assert "PENDIENTE perceptualmente" in validation
    assert "VAL-0018 APROBADO" in validation
    assert "Sprint B3 autorizado" in validation


def test_modulo_declara_superficie_visual_experimental() -> None:
    module = CommandCenterModule(
        ModuleContext(
            "command_center",
            str(ROOT / "modules" / "command_center"),
            json.loads((ROOT / "config" / "nexus.json").read_text())["modules"][
                "command_center"
            ],
            lambda _message: None,
        )
    )

    assert module.public_dir() == str(PUBLIC)
    assert module.health()["surface"] == "visual-experimental"
    assert module.health()["module_registry"]["attached_factories"] == 0
