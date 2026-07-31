from pathlib import Path

from modules.command_center.module_registry import command_center_module_registry


ROOT = Path(__file__).resolve().parents[1]


def test_tidal_discovery_is_documented_without_product_factory() -> None:
    rfc = (ROOT / "docs" / "RFC_COMMAND_CENTER.md").read_text(encoding="utf-8")
    log = (ROOT / "docs" / "VALIDATION_LOG.md").read_text(encoding="utf-8")

    assert "El discovery de TIDAL separa dos integraciones" in rfc
    assert "VAL-0016 — TIDAL Discovery" in log
    assert "PENDIENTE** como integración" in log
    assert command_center_module_registry().stats()["attached_factories"] == 0
