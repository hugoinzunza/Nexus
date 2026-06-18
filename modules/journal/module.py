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
from core import store

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
    def api(self, subpath, query, user=None):
        # Diario = datos personales de Binance → SIEMPRE por usuario de la sesión.
        # Sin sesión (auth inerte / uso local) uid=None → usuario por defecto (Hugo).
        uid = (user or {}).get("uid")
        if subpath == "status":
            data = self._read(uid)
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
            data = self._read(uid)
            if not data:
                return self._json(200, {"has_data": False, "waiting": True})
            data = dict(data)
            data["has_data"] = True
            data["age_seconds"] = self._age(data)
            return self._json(200, data)
        if subpath == "setups":
            return self._setups_response()
        if subpath == "exchange-status":
            # store devuelve "unsupported" sin DB (local), "none" si no hay conexión.
            return self._json(200, store.exchange_status(uid if uid is not None else -1))
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
        # Marca cuáles entran en la cuenta SELECTIVA (POI 4h/1D + premium/descuento +
        # R:R≥5) para poder listarlos aparte en el Diario, igual que la cuenta completa.
        for s in ordered:
            s["selective"] = setups_store.is_selective(s)
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
        return store.read_ingest("setups")

    # --- Conexión de exchange (bóveda, Fase B) -------------------------
    def _exchange_post(self, subpath, body, user):
        """Conecta/desconecta el exchange del usuario de la sesión. La llave se
        cifra (sobre) ANTES de tocar disco; el plaintext nunca se loguea ni se
        guarda. La verificación read-only la hace el colector del VPS (Railway no
        alcanza a Binance por geo)."""
        from core import vault
        uid = (user or {}).get("uid")
        if uid is None:
            return self._json(401, {"error": "necesitas iniciar sesión"})
        if subpath == "disconnect-exchange":
            store.delete_exchange_connection(uid)
            return self._json(200, {"ok": True, "status": "none"})
        # connect-exchange
        if not vault.vault_ready():
            return self._json(503, {"error": "la bóveda no está configurada (falta NEXUX_KEK_PUBLIC)"})
        if not isinstance(body, dict):
            return self._json(400, {"error": "payload inválido"})
        api_key = str(body.get("api_key") or "").strip()
        api_secret = str(body.get("api_secret") or "").strip()
        if not api_key or not api_secret:
            return self._json(400, {"error": "faltan la API key y el secret"})
        if len(api_key) < 16 or len(api_secret) < 16:
            return self._json(400, {"error": "la API key o el secret no parecen válidos"})
        try:
            sealed = vault.seal_credentials(api_key, api_secret, vault.public_pem())
        except Exception:  # noqa: BLE001
            return self._json(500, {"error": "no se pudo cifrar la llave"})
        # A partir de aquí solo manejamos ciphertext.
        del api_key, api_secret
        store.save_exchange_connection(uid, sealed)
        self.context.log(f"journal: conexión de exchange guardada y cifrada (user {uid}, pending)")
        return self._json(200, {
            "ok": True, "status": "pending",
            "message": "Llave guardada y cifrada. La verificación de solo-lectura "
                       "se hace en el motor; en un par de minutos verás el estado."})

    # --- POST (ingesta) ------------------------------------------------
    def api_post(self, subpath, body, headers, user=None):
        # Conectar/desconectar exchange: auth por SESIÓN (no por token del colector).
        if subpath in ("connect-exchange", "disconnect-exchange"):
            return self._exchange_post(subpath, body, user)
        # El resto son endpoints del COLECTOR (VPS), autenticados por token.
        if subpath not in ("ingest", "ingest_setups", "connections", "connection-status", "vault-check"):
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
            self.context.log("journal: petición del colector rechazada (token inválido)")
            return self._json(401, {"error": "token inválido"})

        # Diagnóstico de la bóveda: ¿está la clave pública configurada y cuál es su
        # huella? (solo el hash, NUNCA la clave). Sirve para confirmar que la pública de
        # Railway coincide con la privada del VPS antes de que alguien conecte.
        if subpath == "vault-check":
            import hashlib
            from core import vault
            pub = vault.public_pem()
            fp = hashlib.sha256(pub.encode("utf-8")).hexdigest()[:16] if pub else None
            return self._json(200, {"vault_ready": bool(pub), "pub_fp": fp})

        # Bóveda multi-usuario: el colector pide las conexiones y reporta su verificación.
        if subpath == "connections":
            return self._json(200, {"connections": store.list_connections_for_collector()})
        if subpath == "connection-status":
            if not isinstance(body, dict) or body.get("user_id") is None or not body.get("status"):
                return self._json(400, {"error": "se esperaba {user_id, status, detail?}"})
            store.set_exchange_status(int(body["user_id"]), str(body["status"]),
                                      body.get("detail"), body.get("exchange", "binance"))
            return self._json(200, {"ok": True})

        if not isinstance(body, dict):
            return self._json(400, {"error": "payload inválido (se esperaba JSON objeto)"})

        body = dict(body)
        # En multi-usuario el colector marca a quién pertenece el payload; sin user_id
        # → usuario por defecto (colector single-user de Hugo, retrocompatible).
        ingest_uid = body.pop("user_id", None)
        body["_received_at_ms"] = int(time.time() * 1000)
        kind = "setups" if subpath == "ingest_setups" else "journal"
        prev_setups = None
        if subpath == "ingest_setups":
            # Estado anterior (para detectar transiciones y notificar).
            old = store.read_ingest("setups")
            prev_setups = old.get("setups") if isinstance(old, dict) else None
        with self._lock:
            store.write_ingest(kind, body, user_id=ingest_uid)
        self.context.log(f"journal: {subpath} ingerido del colector"
                         + (f" (user {ingest_uid})" if ingest_uid is not None else ""))
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
            # IDENTIDAD ÚNICA por setup: s["key"] NO es única (varios cerrados comparten
            # la misma key de zona, p.ej. DOGE redondea la entrada a 0,09). Sin ts_created
            # el diff confundía un cerrado con el pendiente del mismo key y re-disparaba
            # "cierre" en cada ingest → spam. ts_created hace única cada operación.
            return f"{s.get('key') or s.get('pair')}:{s.get('ts_created')}"

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

    def _read(self, user_id=None):
        return store.read_ingest("journal", user_id=user_id)

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
                "has_data": self._read() is not None,
                "ingest_ready": bool(self._token())}


def get_module(context):
    return JournalModule(context)
