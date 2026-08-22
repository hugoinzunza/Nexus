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
    assert '"Bearer \\(credential.token)"' in transport
    assert '"X-Nexux-Device-ID"' in transport
    assert "credential.deviceId" in transport
    for forbidden in ("Process(", "NSTask", "/bin/sh", "/bin/zsh"):
        assert forbidden not in source


def test_token_de_dispositivo_se_guarda_en_keychain_local():
    source = (CORE / "DeviceTokenStore.swift").read_text(encoding="utf-8")
    assert "SecItemCopyMatching" in source
    assert "SecItemUpdate" in source
    assert "SecItemAdd" in source
    assert "kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly" in source
    assert "DeviceCredential" in source
    assert "expiresAtMs" in source


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


def test_pairing_es_contractual_y_liga_respuesta_a_la_solicitud():
    source = (CORE / "AgentPairing.swift").read_text(encoding="utf-8")
    assert 'agentPairingProtocolVersion = "nexux.agent-pairing.v1"' in source
    assert "requestId == request.requestId" in source
    assert "deviceId == request.deviceId" in source
    assert "nonce == request.nonce" in source
    assert "pairingCode" in source
    assert "alreadyInProgress" in source
    assert "withThrowingTaskGroup" in source
    assert "URLSession" not in source
    assert "http://" not in source
    assert "https://" not in source


def test_observabilidad_del_pairing_no_expone_credenciales():
    source = (CORE / "AgentPairing.swift").read_text(encoding="utf-8")
    credential_source = (CORE / "DeviceTokenStore.swift").read_text(
        encoding="utf-8"
    )
    stats = source[
        source.index("public struct AgentPairingStats") :
        source.index("public actor AgentPairingCoordinator")
    ]
    assert "token" not in stats.lower()
    assert "pairingCode" not in stats
    assert "pairingCode: <redacted>" in source
    assert "deviceToken: <redacted>" in source
    assert "token: <redacted>" in credential_source


def test_agente_no_activa_factory_productiva():
    registry = command_center_module_registry()
    assert registry.stats()["attached_factories"] == 0
    assert "agent" not in {
        item["module_id"] for item in registry.stats()["modules"]
    }


def test_puente_multimedia_es_local_dirigido_y_sin_coordenadas():
    source = (CORE / "DesktopMediaAccessibility.swift").read_text(
        encoding="utf-8"
    )
    assert '"AXManualAccessibility"' in source
    assert "AXUIElementPerformAction" in source
    assert "kAXPressAction" in source
    assert "postToPid(pid)" in source
    assert "CGEventPost(" not in source
    assert "mouseEventSource" not in source
    assert "api.qobuz" not in source.lower()
    assert "api.tidal" not in source.lower()


def test_tidal_usa_el_control_global_y_revalida_playback():
    source = (CORE / "DesktopMediaAccessibility.swift").read_text(
        encoding="utf-8"
    )
    assert "tidalGlobalPlaybackButton" in source
    assert 'muchos botones "Reproducir"' in source
    assert "knownPlayback: observed" in source


def test_puente_multimedia_publica_tiempos_exactos_cuando_son_observables():
    source = (CORE / "DesktopMediaAccessibility.swift").read_text(
        encoding="utf-8"
    )
    assert 'case positionSeconds = "position_seconds"' in source
    assert 'case durationSeconds = "duration_seconds"' in source
    assert "playbackTiming(player)" in source
    assert "parseTimecode" in source


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
