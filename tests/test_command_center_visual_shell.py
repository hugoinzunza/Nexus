import json
import re
from pathlib import Path

from core.module_base import ModuleContext
from modules.command_center.contracts import CONTRACT_V1_FINGERPRINT
from modules.command_center.module import CommandCenterModule
from modules.command_center.module_registry import command_center_module_registry


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


def test_shell_fija_el_abi_y_no_agrega_superficie_de_comandos() -> None:
    script = (PUBLIC / "command-center.js").read_text(encoding="utf-8")

    assert CONTRACT_V1_FINGERPRINT in script
    assert "method: \"POST\"" not in script
    assert "api/bot" not in script
    assert "market_order" not in script
    assert command_center_module_registry().stats()["attached_factories"] == 0


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
