"""Puente local read-only hacia los snapshots que solo puede leer el VPS."""

from __future__ import annotations

import base64
import json
import os
import re
import subprocess
import threading
import time
from typing import Callable


_TARGET_RE = re.compile(r"^[A-Za-z0-9_.-]+@[A-Za-z0-9_.:-]+$")
_REMOTE_SCRIPT = """
import json
import urllib.request

from modules.journal.collector import (
    _futures_balance,
    _open_positions,
    load_env_file,
)

load_env_file()
bot = None
try:
    with urllib.request.urlopen(
        "http://127.0.0.1:8800/m/bot/api/state", timeout=4
    ) as response:
        bot = json.load(response)
except Exception:
    pass

print(json.dumps({
    "journal": {
        "has_data": True,
        "age_seconds": 0,
        "futures": {
            "ok": True,
            "open_positions": _open_positions(),
            "balance": _futures_balance(),
        },
    },
    "bot": bot,
}))
"""


class VpsPositionsBridge:
    """Consulta por SSH sin copiar llaves ni aceptar datos del navegador."""

    def __init__(
        self,
        *,
        enabled: bool,
        target: str | None = None,
        clock: Callable[[], float] | None = None,
        runner: Callable[..., subprocess.CompletedProcess] | None = None,
        ttl_seconds: float = 15,
    ):
        configured_target = target or os.environ.get(
            "NEXUX_COMMAND_CENTER_VPS_SSH",
            "hugo@49.13.85.184",
        )
        self.enabled = enabled and bool(_TARGET_RE.fullmatch(configured_target))
        self._target = configured_target
        self._clock = clock or time.monotonic
        self._runner = runner or subprocess.run
        self._ttl_seconds = ttl_seconds
        self._lock = threading.Lock()
        self._cached_at = 0.0
        self._cached: dict | None = None

    def read(self) -> dict | None:
        if not self.enabled:
            return None
        now = self._clock()
        with self._lock:
            if self._cached is not None and now - self._cached_at < self._ttl_seconds:
                return self._cached
            payload = self._fetch()
            if payload is not None:
                self._cached = payload
                self._cached_at = now
            return payload or self._cached

    def _fetch(self) -> dict | None:
        encoded = base64.b64encode(_REMOTE_SCRIPT.encode("utf-8")).decode("ascii")
        remote = (
            "cd ~/Nexus && .venv/bin/python -c "
            f'"import base64;exec(base64.b64decode(\'{encoded}\'))"'
        )
        try:
            result = self._runner(
                [
                    "ssh",
                    "-o",
                    "BatchMode=yes",
                    "-o",
                    "ConnectTimeout=5",
                    self._target,
                    remote,
                ],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            return None
        if result.returncode != 0:
            return None
        for line in reversed(result.stdout.splitlines()):
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict) and isinstance(payload.get("journal"), dict):
                return payload
        return None
