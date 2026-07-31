"""Adaptador headless y capability-limited para TIDAL Desktop."""

from __future__ import annotations

from .operations import OperationContext
from .qobuz_adapter import (
    OsaScriptQobuzPort,
    QobuzAdapter,
    QobuzPortError,
)

OSASCRIPT = "/usr/bin/osascript"
OPEN = "/usr/bin/open"
TIDAL_APP = "TIDAL"


class OsaScriptTidalPort(OsaScriptQobuzPort):
    """Puerto local limitado a proceso, versión y apertura de TIDAL."""

    provider_name = "TIDAL"
    code_prefix = "tidal"

    async def is_running(self, context: OperationContext) -> bool:
        output = await self._run(
            (
                OSASCRIPT,
                "-l",
                "AppleScript",
                "-e",
                'application "TIDAL" is running',
            ),
            context,
        )
        normalized = output.strip().lower()
        if normalized not in {"true", "false"}:
            raise QobuzPortError(
                "tidal.invalid-running-state",
                "TIDAL devolvio un estado de ejecucion invalido",
                retryable=True,
            )
        return normalized == "true"

    async def probe_app(self, context: OperationContext) -> str:
        output = await self._run(
            (
                OSASCRIPT,
                "-l",
                "AppleScript",
                "-e",
                'tell application "TIDAL" to get version',
            ),
            context,
        )
        version = output.strip()
        if not version or len(version) > 64 or any(
            character.isspace() for character in version
        ):
            raise QobuzPortError(
                "tidal.invalid-version",
                "TIDAL devolvio una version invalida",
                retryable=True,
            )
        return version

    async def open_app(self, context: OperationContext) -> None:
        await self._run((OPEN, "-gj", "-a", TIDAL_APP), context)


class TidalAdapter(QobuzAdapter):
    """MediaController real limitado a salud y apertura de TIDAL."""

    controller_id = "tidal"
    provider_name = "TIDAL"
    code_prefix = "tidal"

    def __init__(self, port=None, **kwargs):
        super().__init__(port or OsaScriptTidalPort(), **kwargs)
