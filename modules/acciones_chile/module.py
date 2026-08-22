"""Acciones Chile: cartera Renta 4 + fundamentales CMF, fuera de cripto."""
from __future__ import annotations

import hmac
import json
import os
import threading
import time

from core.module_base import NexusModule
from core.paths import persist_dir

from . import auditor
from . import dataset as dataset_store
from .portfolio import normalize_portfolio
from .predictor import feature_join_report, readiness as predictor_readiness


ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PORTFOLIO_PATH = os.path.join(persist_dir(ROOT), "acciones_chile_portfolio.json")
DATASET_PATH = os.path.join(persist_dir(ROOT), "acciones_chile_dataset.json")
TELEGRAM_PATH = os.path.join(persist_dir(ROOT), "acciones_chile_telegram_events.json")
MAX_BODY_BYTES = 500_000


class AccionesChileModule(NexusModule):
    slug = "acciones_chile"
    title = "Acciones Chile"
    description = "Cartera Renta 4 y análisis fundamental CMF, separado de cripto."
    icon = "🇨🇱"

    def __init__(self, context):
        super().__init__(context)
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._refresh_thread = None

    def start(self):
        if not self.config.get("cmf_auto_refresh", False):
            return
        self._refresh_thread = threading.Thread(
            target=self._refresh_loop, name="acciones-chile-refresh", daemon=True)
        self._refresh_thread.start()

    def stop(self):
        self._stop_event.set()
        if self._refresh_thread:
            self._refresh_thread.join(timeout=2)

    @staticmethod
    def _json(status: int, payload: dict):
        return status, "application/json; charset=utf-8", json.dumps(
            payload, ensure_ascii=False, separators=(",", ":")
        ).encode("utf-8")

    def api(self, subpath, query, user=None):
        if subpath == "status":
            uid = (user or {}).get("uid")
            portfolio = self._read_portfolio(uid) if uid is not None else None
            dataset = self._read_dataset()
            cmf = (dataset or {}).get("cmf", {})
            telegram = self._read_telegram()
            return self._json(200, {
                "module": "acciones_chile",
                "mode": "read_only",
                "separate_from_crypto": True,
                "portfolio": {
                    "connected": bool(portfolio),
                    "source": portfolio.get("source") if portfolio else None,
                    "positions": len(portfolio.get("holdings", [])) if portfolio else 0,
                    "as_of": portfolio.get("as_of") if portfolio else None,
                },
                "cmf": {
                    "source": "CMF IFRS TXT oficial",
                    "ready": bool(dataset),
                    "feature_ready": False,
                    "data_status": "partial" if dataset else "waiting",
                    "automatic_fetch": bool(self.config.get("cmf_auto_refresh", False)),
                    "cached": bool(dataset),
                    "periods": cmf.get("periods", []),
                    "issuers": len(cmf.get("issuers", [])),
                    "generated_at_ms": (dataset or {}).get("generated_at_ms"),
                    "known_gaps": ["bancos listados requieren fuente CMF Bancos"],
                    "metric_coverage": cmf.get("metric_coverage", {}),
                    "cross_section_comparable": cmf.get("cross_section_comparable", False),
                },
                "renta4": {
                    "public_api_documented": False,
                    "manual_export_supported": True,
                    "authenticated_web_automation": False,
                },
                "youtube": {
                    "channel": "@inversorchileno",
                    "public_metadata_feed_ready": True,
                    "source_role": "secondary_thesis",
                },
                "telegram": {
                    "source": "@hechosesencialeschile",
                    "connected": bool(telegram),
                    "events": (telegram or {}).get("event_count", 0),
                    "causal_timestamp": "telegram_message_date",
                    "personal_use_only": True,
                },
                "auditor": auditor.availability(self.config),
            })
        if subpath == "portfolio":
            uid = (user or {}).get("uid")
            if uid is None:
                return self._json(401, {"error": "necesitas iniciar sesión"})
            data = self._read_portfolio(uid)
            return self._json(200, data or {"connected": False, "holdings": []})
        if subpath == "issuers":
            dataset = self._read_dataset()
            if not dataset:
                return self._json(503, {"error": "dataset CMF todavía no disponible", "issuers": []})
            search = str(query.get("q") or "").strip().casefold()
            issuers = dataset["cmf"].get("issuers", [])
            include_stale = str(query.get("include_stale") or "") == "1"
            if not include_stale:
                issuers = [item for item in issuers if not item.get("stale", False)]
            if search:
                issuers = [item for item in issuers
                           if search in item["company"].casefold() or search in item["rut"]]
            compact = [{"rut": item["rut"], "company": item["company"],
                        "scope": item["scope"], "currency": item["currency"],
                        "latest_available_period": item.get("latest_available_period"),
                        "months_covered": item.get("months_covered"),
                        "periods_behind": item.get("periods_behind"),
                        "stale": item.get("stale", False)}
                       for item in issuers[:100]]
            return self._json(200, {
                "count": len(issuers), "issuers": compact,
                "cross_section_comparable": len({item.get("months_covered") for item in issuers}) <= 1,
                "warning": "no comparar ventas entre distintos months_covered",
            })
        if subpath == "analysis":
            rut = "".join(ch for ch in str(query.get("rut") or "") if ch.isdigit())[:8]
            if not rut:
                return self._json(400, {"error": "falta rut"})
            dataset = self._read_dataset()
            if not dataset:
                return self._json(503, {"error": "dataset CMF todavía no disponible"})
            issuer = next((item for item in dataset["cmf"].get("issuers", [])
                           if item["rut"] == rut), None)
            if not issuer:
                return self._json(404, {"error": "sociedad no encontrada"})
            issuer = dict(issuer)
            issuer["warnings"] = [
                "dato exploratorio: no habilitado como feature",
                f"cubre {issuer.get('months_covered')} meses del año",
            ]
            return self._json(200, issuer)
        if subpath == "videos":
            dataset = self._read_dataset()
            entries = ((dataset or {}).get("youtube") or {}).get("entries", [])
            return self._json(200, {"count": len(entries), "entries": entries[:30],
                                    "source_role": "secondary_thesis"})
        if subpath == "events":
            if (user or {}).get("uid") is None:
                return self._json(401, {"error": "necesitas iniciar sesión"})
            data = self._read_telegram()
            events = (data or {}).get("events", [])
            event_type = str(query.get("type") or "").strip()
            if event_type:
                events = [event for event in events if event.get("event_type") == event_type]
            return self._json(200, {"count": len(events), "events": events[:200],
                                    "source": "telegram:hechosesencialeschile"})
        if subpath == "predictor-status":
            telegram = self._read_telegram()
            state = predictor_readiness(telegram, price_history_ready=False)
            dataset = self._read_dataset() or {}
            state["cmf_telegram_join"] = feature_join_report(dataset, telegram)
            state["causal_feature_candidates"] = state["cmf_telegram_join"]["candidate_records"]
            state["fundamental_dataset_feature_use"] = dataset.get("feature_use", "forbidden")
            return self._json(200, state)
        if subpath == "boundaries":
            return self._json(200, {
                "orders": "prohibited", "broker_credentials": "not_stored",
                "predictions": "research_only", "human_approval": "required",
                "claude_authority": "advisory_only",
            })
        return None

    def api_post(self, subpath, body, headers, user=None):
        if subpath != "ingest-portfolio":
            return None
        if not self.config.get("portfolio_ingest_enabled", False):
            return self._json(503, {"error": "ingesta de cartera deshabilitada"})
        expected = os.environ.get("NEXUX_CHILE_INGEST_TOKEN", "")
        provided = headers.get("x-nexux-token", "")
        if not expected:
            return self._json(503, {"error": "falta NEXUX_CHILE_INGEST_TOKEN"})
        if not hmac.compare_digest(str(provided), str(expected)):
            return self._json(401, {"error": "token inválido"})
        if len(json.dumps(body, ensure_ascii=False).encode("utf-8")) > MAX_BODY_BYTES:
            return self._json(413, {"error": "payload demasiado grande"})
        try:
            if not isinstance(body, dict) or body.get("user_id") is None:
                return self._json(400, {"error": "falta user_id"})
            user_id = int(body["user_id"])
            normalized = normalize_portfolio(body)
        except ValueError as exc:
            return self._json(400, {"error": str(exc)})
        normalized["received_at_ms"] = int(time.time() * 1000)
        self._write_portfolio(user_id, normalized)
        return self._json(200, {"ok": True, "positions": len(normalized["holdings"])})

    def _read_portfolio(self, uid):
        if uid is None:
            return None
        with self._lock:
            try:
                with open(PORTFOLIO_PATH, encoding="utf-8") as handle:
                    store = json.load(handle)
                return (store.get("portfolios") or {}).get(str(int(uid)))
            except (FileNotFoundError, OSError, ValueError):
                return None

    def _write_portfolio(self, uid: int, data: dict):
        os.makedirs(os.path.dirname(PORTFOLIO_PATH), exist_ok=True)
        temp = PORTFOLIO_PATH + ".tmp"
        with self._lock:
            try:
                with open(PORTFOLIO_PATH, encoding="utf-8") as handle:
                    store = json.load(handle)
            except (FileNotFoundError, OSError, ValueError):
                store = {"schema_version": "acciones-chile-portfolios-0.1.0", "portfolios": {}}
            store.setdefault("portfolios", {})[str(int(uid))] = data
            with open(temp, "w", encoding="utf-8") as handle:
                json.dump(store, handle, ensure_ascii=False, separators=(",", ":"))
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp, PORTFOLIO_PATH)

    def _read_dataset(self):
        with self._lock:
            return dataset_store.read_dataset(DATASET_PATH)

    @staticmethod
    def _read_telegram():
        try:
            with open(TELEGRAM_PATH, encoding="utf-8") as handle:
                data = json.load(handle)
            if data.get("schema_version") != "acciones-chile-telegram-events-0.1.0":
                return None
            return data
        except (FileNotFoundError, OSError, ValueError, AttributeError):
            return None

    def _refresh_loop(self):
        interval = max(3600, int(self.config.get("cmf_refresh_interval_seconds", 86400)))
        while not self._stop_event.is_set():
            existing = self._read_dataset()
            age = time.time() - ((existing or {}).get("generated_at_ms", 0) / 1000)
            if not existing or age >= interval:
                try:
                    dataset_store.refresh_dataset(
                        DATASET_PATH, base_url=self.config.get("cmf_base_url") or dataset_store.DEFAULT_URL)
                    self.context.log("acciones_chile: dataset CMF/YouTube actualizado")
                except Exception as exc:  # noqa: BLE001 - conservar cache y reintentar luego
                    self.context.log(f"acciones_chile: actualización falló cerrada: {exc}")
            self._stop_event.wait(interval)

    def health(self):
        return {"slug": self.slug, "status": "ok", "mode": "read_only",
                "portfolio_storage": "per_user",
                "dataset_ready": bool(self._read_dataset()),
                "telegram_events_ready": bool(self._read_telegram())}


def get_module(context):
    return AccionesChileModule(context)
