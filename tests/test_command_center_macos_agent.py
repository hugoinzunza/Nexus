from pathlib import Path

from modules.command_center.module_registry import command_center_module_registry


ROOT = Path(__file__).parents[1]
AGENT = ROOT / "agents" / "macos" / "NexusAgent"
CORE = AGENT / "Sources" / "NexusAgentCore"


def _source_tree():
    return "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted((AGENT / "Sources").rglob("*.swift"))
    )


def test_paquete_swift_es_headless_y_sin_dependencias_externas():
    package = (AGENT / "Package.swift").read_text(encoding="utf-8")
    assert "NexusAgentCore" in package
    assert "nexus-agent-tests" in package
    assert "dependencies: []" not in package
    assert ".package(" not in package
    assert not list((AGENT / "Tests").rglob("*.swift"))


def test_agente_solo_admite_wss_saliente_y_no_expone_shell_remoto():
    transport = (CORE / "AgentTransport.swift").read_text(encoding="utf-8")
    source = _source_tree()
    assert 'endpoint.scheme?.lowercased() == "wss"' in transport
    assert '"Authorization"' in transport
    assert '"Bearer \\(deviceToken)"' in transport
    for forbidden in ("Process(", "NSTask", "/bin/sh", "/bin/zsh"):
        assert forbidden not in source


def test_token_de_dispositivo_se_guarda_en_keychain_local():
    source = (CORE / "DeviceTokenStore.swift").read_text(encoding="utf-8")
    assert "SecItemCopyMatching" in source
    assert "SecItemUpdate" in source
    assert "SecItemAdd" in source
    assert "kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly" in source


def test_protocolo_del_agente_es_separado_del_wire_abi_del_navegador():
    protocol = (CORE / "AgentProtocol.swift").read_text(encoding="utf-8")
    assert 'agentProtocolVersion = "nexux.agent.v1"' in protocol
    assert "event_type" not in protocol
    assert "CONTRACT_V1_FINGERPRINT" not in protocol
    assert "modules.command_center" not in _source_tree()


def test_runtime_impone_allowlist_ack_e_idempotencia():
    source = (CORE / "AgentRuntime.swift").read_text(encoding="utf-8")
    assert "agent.capability-not-allowed" in source
    assert "agent.action-not-allowed" in source
    assert "agent.command-conflict" in source
    assert "cache[command.commandId]" in source
    assert "inFlight[command.commandId]" in source
    assert "AgentAck(" in source


def test_agente_no_activa_factory_productiva():
    registry = command_center_module_registry()
    assert registry.stats()["attached_factories"] == 0
    assert "agent" not in {
        item["module_id"] for item in registry.stats()["modules"]
    }


def test_fase_a5_documenta_spotify_diferido_y_agente_macos():
    rfc = (ROOT / "docs" / "RFC_COMMAND_CENTER.md").read_text(
        encoding="utf-8"
    )
    log = (ROOT / "docs" / "VALIDATION_LOG.md").read_text(
        encoding="utf-8"
    )
    assert "El discovery de Spotify queda diferido" in rfc
    assert "agente macOS" in rfc
    assert "VAL-0012 — Discovery de Spotify Web API" in log
