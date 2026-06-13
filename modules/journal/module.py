"""Módulo Diario (journal) — lado web (Railway).

Arquitectura híbrida: Binance bloquea a Railway por geo (HTTP 451), así que la
LECTURA de Binance la hace un colector en el Mac mini (ver collector.py) y envía
el resultado acá por POST. Este módulo NO llama a Binance: solo recibe, guarda y
sirve el último JSON ingerido.

Endpoints:
  GET  /m/journal/api/status   estado: ¿hay datos?, antigüedad del último envío.
  GET  /m/journal/api/stats    el último JSON del diario (con su antigüedad).
  POST /m/journal/api/ingest   recibe el JSON del colector (autenticado por token).

Seguridad de la ingesta: cabecera X-Nexus-Token == env var NEXUS_INGEST_TOKEN
(comparación de tiempo constante). Si el token no está configurado en el server,
la ingesta queda deshabilitada (503). Railway NO necesita claves de Binance.
"""
from __future__ import annotations

import hmac
import json
import os
import threading
import time

from core.module_base import NexusModule

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA_DIR = os.path.join(ROOT, "data")
INGEST_PATH = os.path.join(DATA_DIR, "journal_ingest.json")
# Forward-test de setups ingerido del Mac mini (Binance, continuo): en Railway el
# setups.json local es efímero y usa precios de Crypto.com, así que el colector
# manda el del Mac mini y acá se prefiere.
SETUPS_INGEST_PATH = os.path.join(DATA_DIR, "setups_ingest.json")
MAX_BODY = 4_000_000  # 4 MB: tope defensivo del payload de ingesta


class JournalModule(NexusModule):
    slug = "journal"
    title = "Diario"
    description = "Estadísticas de tu trading en Binance (solo lectura): PnL, win rate, horarios."
    icon = "📒"

    def __init__(self, context):
        super().__init__(context)
        self._lock = threading.Lock()

    # --- GET -----------------------------------------------------------
    def api(self, subpath, query):
        if subpath == "status":
            data = self._read()
            if not data:
                return self._json(200, {"has_data": False, "waiting": True,
                                        "ingest_ready": bool(self._token())})
            return self._json(200, {
                "has_data": True, "waiting": False,
                "received_at_ms": data.get("_received_at_ms"),
                "generated_at_ms": data.get("generated_at_ms"),
                "age_seconds": self._age(data),
                "lookback_days": data.get("lookback_days"),
            })
        if subpath == "stats":
            data = self._read()
            if not data:
                return self._json(200, {"has_data": False, "waiting": True})
            data = dict(data)
            data["has_data"] = True
            data["age_seconds"] = self._age(data)
            return self._json(200, data)
        if subpath == "setups":
            return self._setups_response()
        return None

    # --- Setups SMC (forward-test) -------------------------------------
    def _setups_response(self):
        """Tabla de setups que registró el indicador SMC en vivo, con su resumen.
        Lee el store fresco del disco (lo escribe el módulo de trading)."""
        try:
            from modules.trading import setups_store
        except Exception:  # noqa: BLE001
            return self._json(200, {"has_data": False, "setups": [], "summary": None})
        # Preferir el forward-test ingerido del Mac mini (Binance, continuo) sobre el
        # local de Railway (efímero, Crypto.com). Caer al local si no hay ingesta.
        source, age, health = "local", None, None
        setups = setups_store.load_all()
        ing = self._read_setups_ingest()
        if ing and isinstance(ing.get("setups"), list):
            setups = ing["setups"]
            source = "macmini"
            age = self._age(ing)
            health = ing.get("macmini")
        summary = setups_store.summarize(setups)
        paper = setups_store.paper_account(setups)
        # Más recientes primero; tope para no inflar el payload.
        ordered = sorted(setups, key=lambda s: s.get("ts_created", 0), reverse=True)[:200]
        return self._json(200, {
            "has_data": bool(setups),
            "summary": summary,
            "paper": paper,
            "setups": ordered,
            "source": source,
            "age_seconds": age,
            "health": health,
        })

    def _read_setups_ingest(self):
        if not os.path.isfile(SETUPS_INGEST_PATH):
            return None
        try:
            with open(SETUPS_INGEST_PATH, "r", encoding="utf-8") as fh:
                return json.load(fh)
        except Exception:  # noqa: BLE001
            return None

    # --- POST (ingesta) ------------------------------------------------
    def api_post(self, subpath, body, headers):
        if subpath not in ("ingest", "ingest_setups"):
            return None
        token = self._token()
        if not token:
            return self._json(503, {"error": "ingesta no configurada (falta NEXUS_INGEST_TOKEN)"})
        provided = headers.get("x-nexus-token", "")
        if not provided:
            auth = headers.get("authorization", "")
            if auth.lower().startswith("bearer "):
                provided = auth[7:]
        if not hmac.compare_digest(str(provided), str(token)):
            self.context.log("journal: ingesta rechazada (token inválido)")
            return self._json(401, {"error": "token inválido"})
        if not isinstance(body, dict):
            return self._json(400, {"error": "payload inválido (se esperaba JSON objeto)"})

        body = dict(body)
        body["_received_at_ms"] = int(time.time() * 1000)
        dest = SETUPS_INGEST_PATH if subpath == "ingest_setups" else INGEST_PATH
        with self._lock:
            os.makedirs(DATA_DIR, exist_ok=True)
            tmp = dest + ".tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(body, fh, ensure_ascii=False)
            os.replace(tmp, dest)
        self.context.log(f"journal: {subpath} ingerido del colector")
        return self._json(200, {"ok": True, "received_at_ms": body["_received_at_ms"]})

    # --- Helpers -------------------------------------------------------
    @staticmethod
    def _token():
        return os.environ.get("NEXUS_INGEST_TOKEN", "").strip()

    def _read(self):
        if not os.path.isfile(INGEST_PATH):
            return None
        try:
            with open(INGEST_PATH, "r", encoding="utf-8") as fh:
                return json.load(fh)
        except Exception:  # noqa: BLE001
            return None

    @staticmethod
    def _age(data):
        rec = data.get("_received_at_ms")
        if not rec:
            return None
        return round((time.time() * 1000 - rec) / 1000, 0)

    def _json(self, status, obj):
        return (status, "application/json; charset=utf-8",
                json.dumps(obj, ensure_ascii=False).encode("utf-8"))

    def health(self):
        return {"slug": self.slug, "status": "ok",
                "has_data": os.path.isfile(INGEST_PATH),
                "ingest_ready": bool(self._token())}


def get_module(context):
    return JournalModule(context)
