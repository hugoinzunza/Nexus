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
from core.paths import persist_dir  # noqa: E402
# Estado que debe sobrevivir deploys (ingestas del colector) → volumen en Railway.
DATA_DIR = persist_dir(ROOT)
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
        # Cuenta SELECTIVA en paralelo: solo zonas POI de 4h/1D (el edge robusto del
        # laboratorio). No anota los setups para no pisar la cuenta completa.
        paper_selectivo = setups_store.paper_account(
            setups, selector=setups_store.is_selective, annotate=False)
        # Más recientes primero; tope para no inflar el payload.
        ordered = sorted(setups, key=lambda s: s.get("ts_created", 0), reverse=True)[:200]
        return self._json(200, {
            "has_data": bool(setups),
            "summary": summary,
            "paper": paper,
            "paper_selectivo": paper_selectivo,
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
        prev_setups = None
        if subpath == "ingest_setups":
            # Capturamos el estado anterior para detectar transiciones y notificar.
            old = None
            if os.path.isfile(dest):
                try:
                    with open(dest, "r", encoding="utf-8") as fh:
                        old = json.load(fh)
                except Exception:  # noqa: BLE001
                    old = None
            prev_setups = (old or {}).get("setups") if isinstance(old, dict) else None
        with self._lock:
            os.makedirs(DATA_DIR, exist_ok=True)
            tmp = dest + ".tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(body, fh, ensure_ascii=False)
            os.replace(tmp, dest)
        self.context.log(f"journal: {subpath} ingerido del colector")
        if subpath == "ingest_setups" and isinstance(body.get("setups"), list):
            # El Mac mini es el tracker autoritativo pero no tiene suscripciones push;
            # las alertas se disparan acá (Railway, donde están las subs) comparando el
            # estado nuevo contra el anterior. Cierres, parciales y activaciones.
            try:
                self._notify_setup_transitions(prev_setups, body["setups"])
            except Exception as exc:  # noqa: BLE001
                self.context.log(f"journal: no se pudo notificar transiciones: {exc}")
        return self._json(200, {"ok": True, "received_at_ms": body["_received_at_ms"]})

    @staticmethod
    def _notify_setup_transitions(prev_setups, new_setups):
        """Compara setups ingeridos (nuevo vs anterior) y manda push por transiciones:
        cierre (ganada/perdida), parcial (TP1/TP2) y activación. Solo notifica si el
        setup ya existía antes (evita spam en el primer ingest)."""
        if not prev_setups:
            return  # baseline: no notificamos en el primer ingest
        try:
            from core import push
        except Exception:  # noqa: BLE001
            return
        if not push.configurado():
            return
        OPEN = ("pendiente", "activo", None)

        def key(s):
            return s.get("key") or f"{s.get('pair')}:{s.get('ts_created')}"

        prevmap = {key(s): s for s in prev_setups}
        for s in new_setups:
            p = prevmap.get(key(s))
            if p is None:
                continue  # nuevo: aún sin estado previo que comparar
            pair = (s.get("pair") or "").replace("_USDT", "").replace("_", "/")
            d = "Long" if s.get("dir") == "long" else "Short"
            st = s.get("status")
            k = key(s)
            # 1) Cierre
            if st in ("ganada", "perdida") and p.get("status") in OPEN:
                r = s.get("result_r")
                if st == "ganada":
                    push.notificar(f"✅ {pair} · ganada", f"{pair} {d} cerró +{r}R con parciales.",
                                   url="/m/trading/", tag=f"setup-{k}-cerrada")
                else:
                    push.notificar(f"❌ {pair} · perdida", f"{pair} {d} cerró {r}R.",
                                   url="/m/trading/", tag=f"setup-{k}-cerrada")
                continue
            # 2) Parcial (TP1/TP2 nuevo)
            if st == "activo" and (s.get("legs_filled") or 0) > (p.get("legs_filled") or 0):
                legs = s.get("legs_filled") or 0
                leg = "TP2" if legs >= 2 else "TP1"
                pct = 50 if legs < 2 else 25
                push.notificar(f"🎯 {pair} · {leg} alcanzado",
                               f"{pair} {d}: toma {pct}% en {leg}. Asegurado +{s.get('realized_r')}R · SL a break-even.",
                               url="/m/trading/", tag=f"setup-{k}-{leg}")
                continue
            # 3) Activación (entrada llenada)
            if st == "activo" and p.get("status") == "pendiente":
                push.notificar(f"{pair} · entrada llenada",
                               f"{pair} {d}: el precio entró a la zona. Trade activo (no es señal).",
                               url="/m/trading/", tag=f"setup-{k}-activo")

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
