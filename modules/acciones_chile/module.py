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
from .portfolio import normalize_portfolio


ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PORTFOLIO_PATH = os.path.join(persist_dir(ROOT), "acciones_chile_portfolio.json")
MAX_BODY_BYTES = 500_000


class AccionesChileModule(NexusModule):
    slug = "acciones_chile"
    title = "Acciones Chile"
    description = "Cartera Renta 4 y análisis fundamental CMF, separado de cripto."
    icon = "🇨🇱"

    def __init__(self, context):
        super().__init__(context)
        self._lock = threading.Lock()

    @staticmethod
    def _json(status: int, payload: dict):
        return status, "application/json; charset=utf-8", json.dumps(
            payload, ensure_ascii=False, separators=(",", ":")
        ).encode("utf-8")

    def api(self, subpath, query, user=None):
        if subpath == "status":
            portfolio = self._read_portfolio()
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
                    "ready": True,
                    "automatic_fetch": False,
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
                "auditor": auditor.availability(self.config),
            })
        if subpath == "portfolio":
            data = self._read_portfolio()
            return self._json(200, data or {"connected": False, "holdings": []})
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
            normalized = normalize_portfolio(body)
        except ValueError as exc:
            return self._json(400, {"error": str(exc)})
        normalized["received_at_ms"] = int(time.time() * 1000)
        self._write_portfolio(normalized)
        return self._json(200, {"ok": True, "positions": len(normalized["holdings"])})

    def _read_portfolio(self):
        with self._lock:
            try:
                with open(PORTFOLIO_PATH, encoding="utf-8") as handle:
                    return json.load(handle)
            except (FileNotFoundError, OSError, ValueError):
                return None

    def _write_portfolio(self, data: dict):
        os.makedirs(os.path.dirname(PORTFOLIO_PATH), exist_ok=True)
        temp = PORTFOLIO_PATH + ".tmp"
        with self._lock:
            with open(temp, "w", encoding="utf-8") as handle:
                json.dump(data, handle, ensure_ascii=False, indent=2)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp, PORTFOLIO_PATH)

    def health(self):
        return {"slug": self.slug, "status": "ok", "mode": "read_only",
                "portfolio_connected": bool(self._read_portfolio())}


def get_module(context):
    return AccionesChileModule(context)
