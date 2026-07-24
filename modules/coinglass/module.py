"""Read-only CoinGlass research dashboard and authenticated ingest."""
from __future__ import annotations

import hmac
import json
import os
import threading
import time

from core.module_base import NexusModule
from core.paths import persist_dir

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
STATE_PATH = os.path.join(persist_dir(ROOT), "coinglass_dashboard.json")
MAX_BODY = 8_000_000


class CoinGlassModule(NexusModule):
    slug = "coinglass"
    title = "CoinGlass"
    description = "Microestructura BTC: liquidaciones, order book y presión experimental."
    icon = "CG"

    def __init__(self, context):
        super().__init__(context)
        self._lock = threading.Lock()

    def api(self, subpath, query, user=None):
        if subpath != "state":
            return None
        data = self._read()
        if not data:
            return self._json(200, {
                "mode": "research",
                "execution_enabled": False,
                "waiting": True,
            })
        data["age_seconds"] = round(time.time() - os.path.getmtime(STATE_PATH), 0)
        return self._json(200, data)

    def api_post(self, subpath, body, headers, user=None):
        if subpath != "ingest":
            return None
        token = os.environ.get("NEXUS_INGEST_TOKEN", "").strip()
        if not token:
            return self._json(503, {"error": "ingesta no configurada"})
        if not hmac.compare_digest(headers.get("x-nexus-token", ""), token):
            return self._json(401, {"error": "token invalido"})
        if not isinstance(body, dict) or body.get("research_only") is not True:
            return self._json(400, {"error": "snapshot CoinGlass invalido"})
        if body.get("execution_enabled") is not False or body.get("mode") != "research":
            return self._json(400, {"error": "solo se aceptan datos research sin ejecucion"})
        raw = json.dumps(body, ensure_ascii=False).encode()
        if len(raw) > MAX_BODY:
            return self._json(413, {"error": "snapshot demasiado grande"})
        with self._lock:
            self._write(body)
        return self._json(200, {"ok": True})

    @staticmethod
    def _read():
        try:
            with open(STATE_PATH, encoding="utf-8") as fh:
                return json.load(fh)
        except (FileNotFoundError, json.JSONDecodeError):
            return None

    @staticmethod
    def _write(data):
        os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
        temp = STATE_PATH + ".tmp"
        with open(temp, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False)
        os.chmod(temp, 0o600)
        os.replace(temp, STATE_PATH)

    @staticmethod
    def _json(status, data):
        return status, "application/json; charset=utf-8", json.dumps(data).encode()

    def health(self):
        data = self._read()
        return {
            "slug": self.slug,
            "status": "ok",
            "mode": "research",
            "has_data": bool(data),
            "execution": False,
        }


def get_module(context):
    return CoinGlassModule(context)
