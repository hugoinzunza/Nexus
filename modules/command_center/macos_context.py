"""Estado operacional local de macOS para el Command Center."""

from __future__ import annotations

import os
import platform
import re
import shutil
import subprocess
import time
from collections.abc import Callable


class MacOSContextService:
    """Proyecta salud del equipo sin exponer procesos ni datos personales."""

    def __init__(
        self,
        *,
        enabled: bool,
        clock_ms: Callable[[], int] | None = None,
        runner: Callable[[list[str]], str] | None = None,
    ):
        self._enabled = enabled
        self._clock_ms = clock_ms or (lambda: int(time.time() * 1000))
        self._runner = runner or self._run

    @staticmethod
    def _run(command: list[str]) -> str:
        result = subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
            timeout=2,
        )
        return result.stdout.strip()

    @staticmethod
    def _ratio(used: float, total: float) -> float | None:
        if total <= 0:
            return None
        return round(max(0.0, min(100.0, used / total * 100)), 1)

    def _memory_percent(self) -> float | None:
        total = int(self._runner(["/usr/sbin/sysctl", "-n", "hw.memsize"]))
        vm = self._runner(["/usr/bin/vm_stat"])
        page_match = re.search(r"page size of (\d+) bytes", vm)
        if not page_match:
            return None
        page_size = int(page_match.group(1))
        counters = {
            key: int(value)
            for key, value in re.findall(r"^([^:]+):\s+(\d+)\.", vm, re.M)
        }
        used_pages = sum(
            counters.get(key, 0)
            for key in (
                "Pages active",
                "Pages wired down",
                "Pages occupied by compressor",
            )
        )
        return self._ratio(used_pages * page_size, total)

    def _memory_pressure(self) -> tuple[str, float | None]:
        raw = self._runner(["/usr/bin/memory_pressure", "-Q"])
        match = re.search(r"free percentage:\s*(\d+(?:\.\d+)?)%", raw, re.I)
        if not match:
            return "unknown", None
        available = round(max(0.0, min(100.0, float(match.group(1)))), 1)
        if available < 10:
            return "critical", available
        if available < 20:
            return "elevated", available
        return "normal", available

    def _uptime_seconds(self) -> int | None:
        raw = self._runner(["/usr/sbin/sysctl", "-n", "kern.boottime"])
        match = re.search(r"sec\s*=\s*(\d+)", raw)
        return max(0, int(time.time()) - int(match.group(1))) if match else None

    def _power(self) -> tuple[str, float | None]:
        raw = self._runner(["/usr/bin/pmset", "-g", "batt"])
        battery = re.search(r"(\d+)%", raw)
        source = "Batería" if "Battery Power" in raw else "Corriente"
        return source, float(battery.group(1)) if battery else None

    def snapshot(self) -> dict:
        now = self._clock_ms()
        if not self._enabled or platform.system() != "Darwin":
            return {
                "generated_at_ms": now,
                "state": "unavailable",
                "detail": "Disponible únicamente en el Command Center local.",
                "read_only": True,
            }

        try:
            load = os.getloadavg()[0]
            cpu_count = max(1, os.cpu_count() or 1)
            load_percent = round(min(100.0, load / cpu_count * 100), 1)
            memory_percent = self._memory_percent()
            memory_pressure, memory_available_percent = self._memory_pressure()
            disk = shutil.disk_usage("/")
            disk_percent = self._ratio(disk.used, disk.total)
            power_source, battery_percent = self._power()
            uptime_seconds = self._uptime_seconds()
            observed = [
                value
                for value in (load_percent, disk_percent)
                if value is not None
            ]
            state = (
                "degraded"
                if memory_pressure in {"elevated", "critical"}
                or any(value >= 90 for value in observed)
                else "ready"
            )
            return {
                "generated_at_ms": now,
                "state": state,
                "device": platform.node().split(".")[0] or "Mac",
                "os_version": platform.mac_ver()[0] or "macOS",
                "load_percent": load_percent,
                "memory_percent": memory_percent,
                "memory_pressure": memory_pressure,
                "memory_available_percent": memory_available_percent,
                "disk_percent": disk_percent,
                "power_source": power_source,
                "battery_percent": battery_percent,
                "uptime_seconds": uptime_seconds,
                "read_only": True,
            }
        except Exception:
            return {
                "generated_at_ms": now,
                "state": "degraded",
                "detail": "No fue posible completar la lectura local.",
                "read_only": True,
            }
