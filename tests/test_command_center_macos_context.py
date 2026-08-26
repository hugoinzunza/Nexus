import json
import os
import shutil
import time
from pathlib import Path

from modules.command_center.macos_context import MacOSContextService


ROOT = Path(__file__).resolve().parents[1]
PUBLIC = ROOT / "modules" / "command_center" / "public"


def test_contexto_macos_proyecta_metricas_locales_sin_procesos(monkeypatch):
    commands = {
        ("/usr/sbin/sysctl", "-n", "hw.memsize"): "16000000000",
        ("/usr/bin/vm_stat",): (
            "Mach Virtual Memory Statistics: (page size of 4096 bytes)\n"
            "Pages active: 1000000.\n"
            "Pages wired down: 500000.\n"
            "Pages occupied by compressor: 500000.\n"
        ),
        ("/usr/bin/memory_pressure", "-Q"): (
            "The system has 16000000000 bytes.\n"
            "System-wide memory free percentage: 37%\n"
        ),
        ("/usr/bin/pmset", "-g", "batt"): "Now drawing from 'AC Power'",
        ("/usr/sbin/sysctl", "-n", "kern.boottime"): (
            f"{{ sec = {int(time.time()) - 86400}, usec = 0 }}"
        ),
    }
    monkeypatch.setattr("platform.system", lambda: "Darwin")
    monkeypatch.setattr("platform.node", lambda: "NexUX-Mac.local")
    monkeypatch.setattr("platform.mac_ver", lambda: ("26.0", (), ""))
    monkeypatch.setattr(os, "getloadavg", lambda: (2.0, 1.0, 0.5))
    monkeypatch.setattr(os, "cpu_count", lambda: 8)
    monkeypatch.setattr(
        shutil,
        "disk_usage",
        lambda _path: shutil._ntuple_diskusage(1000, 400, 600),
    )
    service = MacOSContextService(
        enabled=True,
        clock_ms=lambda: 1234,
        runner=lambda command: commands[tuple(command)],
    )

    result = service.snapshot()

    assert result["state"] == "ready"
    assert result["device"] == "NexUX-Mac"
    assert result["load_percent"] == 25.0
    assert result["memory_percent"] == 51.2
    assert result["memory_pressure"] == "normal"
    assert result["memory_available_percent"] == 37.0
    assert result["disk_percent"] == 40.0
    assert result["power_source"] == "Corriente"
    assert result["uptime_seconds"] >= 86400
    assert result["read_only"] is True
    assert "process" not in json.dumps(result).lower()


def test_contexto_macos_fuera_del_host_local_falla_explicito(monkeypatch):
    monkeypatch.setattr("platform.system", lambda: "Darwin")
    result = MacOSContextService(enabled=False, clock_ms=lambda: 1234).snapshot()

    assert result == {
        "generated_at_ms": 1234,
        "state": "unavailable",
        "detail": "Disponible únicamente en el Command Center local.",
        "read_only": True,
    }


def test_contexto_macos_clasifica_presion_por_capacidad_disponible():
    expected = {
        37: "normal",
        15: "elevated",
        9: "critical",
    }
    for available, state in expected.items():
        service = MacOSContextService(
            enabled=True,
            runner=lambda _command, value=available: (
                f"System-wide memory free percentage: {value}%"
            ),
        )

        assert service._memory_pressure() == (state, float(available))


def test_shell_compacta_macos_y_devuelve_protagonismo_a_trading():
    page = (PUBLIC / "index.html").read_text(encoding="utf-8")
    css = (PUBLIC / "command-center.css").read_text(encoding="utf-8")
    script = (PUBLIC / "command-center.js").read_text(encoding="utf-8")

    assert page.count('class="macos-compact"') == 1
    assert page.count('class="market-column"') == 1
    assert 'id="macos-load"' in page
    assert 'id="macos-memory"' in page
    assert 'id="macos-memory-pressure"' in page
    assert 'id="macos-disk"' in page
    assert 'id="macos-power"' in page
    assert "grid-template-columns: minmax(0, 2.08fr) minmax(560px, 1fr)" in css
    assert ".macos-compact" in css
    assert 'const MACOS_CONTEXT_URL = "/m/command-center/api/macos-context"' in script
    assert "new MacOSContextClient" in script
    assert script.count('method: "POST"') == 1


def test_lanzador_kiosco_no_abre_fixture():
    launcher = (ROOT / "tools" / "open_command_center.command").read_text(
        encoding="utf-8"
    )
    assert "fixture=ready" not in launcher
    assert 'open -na "$APP" --args "$URL"' in launcher
    assert 'HEALTH_URL=' in launcher
    assert 'SERVICE_LABEL="com.hugo.nexux-command-center"' in launcher
    assert 'launchctl bootstrap "$SERVICE_DOMAIN" "$SERVICE_TARGET"' in launcher
    assert 'launchctl kickstart -k "$SERVICE_DOMAIN/$SERVICE_LABEL"' in launcher
    assert 'command-center-local.log' in launcher
    service = (
        ROOT / "deploy" / "com.hugo.nexux-command-center.plist"
    ).read_text(encoding="utf-8")
    assert "<string>8812</string>" in service
    assert "<key>KeepAlive</key>" in service
    assert "<key>NEXUX_COMMAND_CENTER_MEDIA</key>" in service
    native = (
        ROOT / "agents" / "macos" / "CommandCenterShell" / "main.swift"
    ).read_text(encoding="utf-8")
    assert "styleMask: [.borderless]" in native
    assert "screen.frame" in native
    assert ".hideMenuBar" in native
    assert "customUserAgent" in native
    assert 'localizedName.uppercased().contains("ARZOPA")' in native
    assert "NSApplication.didChangeScreenParametersNotification" in native
    assert "moveWindowToArzopaWhenAvailable" in native
    assert "screenRetriesRemaining = 60" in native
    assert "displayID(window.screen) != displayID(screen)" in native
