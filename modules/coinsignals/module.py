"""Web surface for the CoinSignals shadow books. No order endpoints exist."""
from __future__ import annotations

import hmac
import json
import os
import threading
import time

from core.module_base import NexusModule
from core.paths import persist_dir
from .shadow import HISTORY_PATH, ROOT, build_snapshot

STATE_PATH = os.path.join(persist_dir(str(ROOT)), "coinsignals_shadow.json")
MAX_BODY = 4_000_000


class CoinSignalsModule(NexusModule):
    slug = "coinsignals"
    title = "CoinSignals Shadow"
    description = "Tres libros BTC paralelos de CoinSignals, solo observación y sin órdenes."
    icon = "CS"

    def __init__(self, context):
        super().__init__(context)
        self._lock = threading.Lock()

    def start(self):
        if os.path.isfile(STATE_PATH) or not HISTORY_PATH.exists():
            return
        try:
            snapshot = build_snapshot(
                forward_start=self.config.get("forward_start", "2026-07-22T00:00:00+00:00")
            )
            self._write(snapshot)
            self.context.log("coinsignals: snapshot shadow inicial creado")
        except Exception as exc:  # noqa: BLE001
            self.context.log(f"coinsignals: snapshot inicial no disponible ({exc})")

    def api(self, subpath, query, user=None):
        if subpath != "state":
            return None
        data = self._read()
        if not data:
            return self._json(200, {"mode": "shadow", "execution_enabled": False, "waiting": True})
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
            return self._json(400, {"error": "snapshot shadow invalido"})
        if body.get("execution_enabled") is not False or body.get("mode") != "shadow":
            return self._json(400, {"error": "solo se aceptan snapshots sin ejecucion"})
        raw = json.dumps(body, ensure_ascii=False).encode("utf-8")
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
        tmp = STATE_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False)
        os.replace(tmp, STATE_PATH)
        os.chmod(STATE_PATH, 0o600)

    @staticmethod
    def _json(status, data):
        return status, "application/json; charset=utf-8", json.dumps(data, ensure_ascii=False).encode()

    def health(self):
        return {"slug": self.slug, "status": "ok", "mode": "shadow", "execution": False}


def get_module(context):
    return CoinSignalsModule(context)
