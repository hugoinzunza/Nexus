"""Módulo NexUX BOT — libro + espejo en vivo de la operación REAL en Binance.

La web corre en Railway, que NO toca Binance. El VPS (único con llaves) EMPUJA un
snapshot (balance, posiciones, órdenes, libro) por POST /m/bot/api/ingest, y en la
respuesta recibe los comandos que dejó la web (parar / reanudar / cerrar posición).

Endpoints:
  GET  /m/bot/api/state     estado para el panel (snapshot del VPS, o libro local).
  POST /m/bot/api/ingest    el VPS empuja su snapshot (auth por token); devuelve comandos.
  POST /m/bot/api/command   la web encola un comando (auth por sesión admin).

El cerebro sigue siendo el Diario (paper); este módulo es la operación real, aparte.
"""
from __future__ import annotations

import hmac
import json
import os
import threading
import time

from core.module_base import NexusModule

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:
    from core.paths import persist_dir
    DATA_DIR = persist_dir(ROOT)
except Exception:  # noqa: BLE001
    DATA_DIR = os.path.join(ROOT, "data")
STATE_PATH = os.path.join(DATA_DIR, "bot_state.json")        # snapshot ingerido del VPS
COMMANDS_PATH = os.path.join(DATA_DIR, "bot_commands.json")  # cola de comandos web→VPS
MAX_BODY = 2_000_000


class BotModule(NexusModule):
    slug = "bot"
    title = "NexUX BOT"
    description = "Operación real del bot espejo en Binance Futuros: balance, posiciones, P&L y control."
    icon = "🤖"

    def __init__(self, context):
        super().__init__(context)
        self._lock = threading.Lock()

    # --- GET -----------------------------------------------------------
    def api(self, subpath, query, user=None):
        if subpath == "state":
            # El estado incluye balance/posiciones reales → exige sesión cuando la
            # auth está activa (Railway). En local/VPS (auth inerte) pasa.
            from core import auth
            if auth.enabled() and not user:
                return self._json(401, {"error": "no autorizado", "login": "/login"})
            return self._state_response()
        return None

    def _state_response(self):
        ing = self._read_state()
        if ing and ing.get("ts"):
            data = dict(ing)
            data["source"] = "vps"
            data["age_seconds"] = round((time.time() * 1000 - ing.get("_received_at_ms", ing["ts"])) / 1000, 0)
            return self._json(200, data)
        # Fallback local (VPS/dev sin ingesta): solo el libro, sin cuenta en vivo.
        from .bot_store import BotStore
        from .executor import load_config, _trade_creds
        s = BotStore()
        cfg = load_config()
        key, _sec = _trade_creds()
        return self._json(200, {
            "source": "local", "account": {}, "positions": [], "open_orders": [],
            "summary": s.summary(),
            "trades": sorted(s.all(), key=lambda t: t.get("opened_at", 0), reverse=True),
            "live": bool(cfg.get("live")), "active": bool(cfg.get("enabled")) and bool(key),
            "kill": os.path.exists(os.path.join(ROOT, "data", "bot_kill")),
        })

    # --- POST ----------------------------------------------------------
    def api_post(self, subpath, body, headers, user=None):
        if subpath == "ingest":
            token = self._token()
            if not token:
                return self._json(503, {"error": "ingesta no configurada (falta NEXUS_INGEST_TOKEN)"})
            provided = headers.get("x-nexus-token", "")
            if not hmac.compare_digest(str(provided), str(token)):
                return self._json(401, {"error": "token inválido"})
            if not isinstance(body, dict):
                return self._json(400, {"error": "payload inválido"})
            body = dict(body)
            body["_received_at_ms"] = int(time.time() * 1000)
            with self._lock:
                self._write_json(STATE_PATH, body)
                cmds = self._read_json(COMMANDS_PATH, [])
                if cmds:
                    self._write_json(COMMANDS_PATH, [])
            return self._json(200, {"ok": True, "commands": cmds})

        if subpath == "command":
            from core import auth
            if auth.enabled() and not (user and auth.is_admin(user)):
                return self._json(401, {"error": "no autorizado"})
            if not isinstance(body, dict) or not body.get("action"):
                return self._json(400, {"error": "se esperaba {action, symbol?}"})
            if body["action"] not in ("kill", "resume", "close"):
                return self._json(400, {"error": "acción inválida"})
            cmd = {"action": body["action"], "symbol": body.get("symbol"), "ts": int(time.time())}
            with self._lock:
                cmds = self._read_json(COMMANDS_PATH, [])
                cmds.append(cmd)
                self._write_json(COMMANDS_PATH, cmds)
            return self._json(200, {"ok": True, "queued": cmd})
        return None

    # --- helpers -------------------------------------------------------
    def _read_state(self):
        return self._read_json(STATE_PATH, None)

    @staticmethod
    def _read_json(path, default):
        try:
            with open(path, encoding="utf-8") as fh:
                return json.load(fh)
        except (FileNotFoundError, json.JSONDecodeError):
            return default

    @staticmethod
    def _write_json(path, obj):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(obj, fh, ensure_ascii=False)
        os.replace(tmp, path)

    @staticmethod
    def _token():
        return os.environ.get("NEXUS_INGEST_TOKEN", "").strip()

    def _json(self, status, obj):
        return (status, "application/json; charset=utf-8",
                json.dumps(obj, ensure_ascii=False).encode("utf-8"))

    def health(self):
        return {"slug": self.slug, "status": "ok"}


def get_module(context):
    return BotModule(context)
