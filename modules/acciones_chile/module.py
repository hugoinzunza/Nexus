"""Acciones Chile: cartera Renta 4 + fundamentales CMF, fuera de cripto."""
from __future__ import annotations

import hmac
import json
import os
import threading
import time
from datetime import date, datetime, timezone

from core.module_base import NexusModule
from core.paths import persist_dir

from . import auditor
from . import banks
from . import cmf as cmf_client
from . import dataset as dataset_store
from . import fx
from .portfolio import normalize_portfolio
from . import freshness
from .predictor import (
    build_feature_records, feature_join_report, normalize_company, portfolio_event_monitor,
    readiness as predictor_readiness,
)
from .strategy import (
    build_radar, evaluate_decision_evidence, evaluate_observation, evaluate_valuation,
    portfolio_concentration,
)
from .universe import load_universe, snapshot_as_of, universe_status


ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PORTFOLIO_PATH = os.path.join(persist_dir(ROOT), "acciones_chile_portfolio.json")
DATASET_PATH = os.path.join(persist_dir(ROOT), "acciones_chile_dataset.json")
TELEGRAM_PATH = os.path.join(persist_dir(ROOT), "acciones_chile_telegram_events.json")
PACKAGED_UNIVERSE_PATH = os.path.join(ROOT, "config", "acciones_chile_universe_v0.1.json")
LOCAL_UNIVERSE_PATH = os.path.join(persist_dir(ROOT), "acciones_chile_universe.json")
MARKET_STATUS_PATH = os.path.join(persist_dir(ROOT), "acciones_chile_market_data_status.json")
BANKS_PATH = os.path.join(persist_dir(ROOT), "acciones_chile_banks.json")
FX_PATH = os.path.join(persist_dir(ROOT), "acciones_chile_fx.json")
EPS_UNITS_PATH = os.path.join(persist_dir(ROOT), "acciones_chile_eps_units.json")
PACKAGED_EPS_UNITS_PATH = os.path.join(ROOT, "config", "acciones_chile_eps_units_v0.3.json")
MAX_BODY_BYTES = 500_000
MAX_TELEGRAM_BODY_BYTES = 2_000_000


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
            universe = self._universe_status()
            market = self._read_json(MARKET_STATUS_PATH)
            bank_status = banks.availability(BANKS_PATH)
            fx_status = fx.availability(FX_PATH)
            eps_status = fx.eps_unit_availability(EPS_UNITS_PATH, PACKAGED_EPS_UNITS_PATH)
            fuentes = self._fuentes_frescura(dataset, telegram, portfolio,
                                             fx_status, bank_status, market)
            return self._json(200, {
                "module": "acciones_chile",
                "mode": "read_only",
                "separate_from_crypto": True,
                "freshness": {"sources": fuentes, "overall": freshness.overall(fuentes)},
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
                    "historical_observations": len(cmf.get("observations", [])),
                    "generated_at_ms": (dataset or {}).get("generated_at_ms"),
                    "known_gaps": bank_status["blockers"],
                    "metric_coverage": cmf.get("metric_coverage", {}),
                    "cross_section_comparable": cmf.get("cross_section_comparable", False),
                },
                "cmf_banks": bank_status,
                "fx": fx_status,
                "eps_units": eps_status,
                "renta4": {
                    "public_api_documented": False,
                    "manual_export_supported": True,
                    "authenticated_web_snapshot_supported": True,
                    "automatic_background_sync": False,
                    "automatic_sync_blocker": "Renta 4 no publica API; requiere sesión web activa del usuario",
                    "orders": "prohibited",
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
                "universe": universe,
                "market_data": market or {
                    "label_ready": False,
                    "blockers": [
                        "falta importación adquirida o autorizada de precios e IPSA total-return"
                    ],
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
        if subpath == "company-history":
            rut = "".join(ch for ch in str(query.get("rut") or "") if ch.isdigit())[:8]
            if not rut:
                return self._json(400, {"error": "falta rut"})
            dataset = self._read_dataset()
            if not dataset:
                return self._json(503, {"error": "dataset CMF todavía no disponible"})
            history = [item for item in dataset["cmf"].get("observations", [])
                       if item.get("rut") == rut]
            history.sort(key=lambda item: item.get("period", ""))
            if not history:
                return self._json(404, {"error": "sociedad no encontrada"})
            portfolio = self._read_portfolio((user or {}).get("uid"))
            holding = next((item for item in (portfolio or {}).get("holdings", [])
                            if item.get("company_rut") == rut), None)
            total_market = sum(
                self._as_float(item.get("market_value")) or 0
                for item in (portfolio or {}).get("holdings", []))
            holding_market = self._as_float((holding or {}).get("market_value"))
            allocation = holding_market / total_market if holding_market is not None and total_market else None
            reading = evaluate_observation(history[-1], history)
            fx_rate = fx.rate_as_of(self._read_json(FX_PATH), (portfolio or {}).get("as_of")) \
                if (portfolio or {}).get("as_of") else None
            eps_units = (fx.read_eps_unit_dataset(EPS_UNITS_PATH)
                         or fx.read_eps_unit_dataset(PACKAGED_EPS_UNITS_PATH) or {})
            unit_verification = (eps_units.get("entries") or {}).get(rut)
            valuation = evaluate_valuation(
                history, (holding or {}).get("market_price"), fx_rate,
                unit_verification, issuer_rut=rut)
            event_state = portfolio_event_monitor(
                (self._read_telegram() or {}).get("events", []), [history[-1]["company"]])
            company_events = (event_state.get("by_company") or {}).get(
                normalize_company(history[-1]["company"]))
            return self._json(200, {
                "rut": rut, "company": history[-1]["company"], "history": history,
                "reading": reading, "valuation": valuation,
                "events": company_events, "allocation_pct": allocation,
                "decision_evidence": evaluate_decision_evidence(
                    reading, valuation, company_events, allocation),
                "price_history_ready": False,
            })
        if subpath == "radar":
            dataset = self._read_dataset()
            if not dataset:
                return self._json(503, {"error": "dataset CMF todavía no disponible"})
            try:
                limit = max(1, min(100, int(query.get("limit") or 40)))
            except (TypeError, ValueError):
                return self._json(400, {"error": "limit inválido"})
            causal = build_feature_records(dataset, self._read_telegram())
            allowed_ruts = {item["rut"] for item in causal}
            result = build_radar(dataset, limit=limit, allowed_ruts=allowed_ruts)
            result["universe_role"] = "companies_with_causal_cmf_telegram_match"
            result["listing_status"] = "unverified_until_authorized_exchange_universe"
            result["research_only"] = True
            return self._json(200, result)
        if subpath == "portfolio-monitor":
            uid = (user or {}).get("uid")
            if uid is None:
                return self._json(401, {"error": "necesitas iniciar sesión"})
            portfolio = self._read_portfolio(uid)
            if not portfolio:
                return self._json(200, {"connected": False, "holdings": []})
            dataset = self._read_dataset() or {}
            observations = (dataset.get("cmf") or {}).get("observations", [])
            issuers = (dataset.get("cmf") or {}).get("issuers", [])
            by_rut = {item.get("rut"): item for item in issuers}
            telegram = self._read_telegram() or {}
            portfolio_companies = [
                by_rut[holding.get("company_rut")].get("company")
                for holding in portfolio.get("holdings", [])
                if holding.get("company_rut") in by_rut
            ]
            event_monitor = portfolio_event_monitor(
                telegram.get("events", []), portfolio_companies)
            fx_rate = fx.rate_as_of(self._read_json(FX_PATH), portfolio.get("as_of")) \
                if portfolio.get("as_of") else None
            eps_units = (fx.read_eps_unit_dataset(EPS_UNITS_PATH)
                         or fx.read_eps_unit_dataset(PACKAGED_EPS_UNITS_PATH) or {})
            bank_status = banks.availability(BANKS_PATH)
            try:
                universe_data = load_universe(self._universe_path())
                universe_snapshot = snapshot_as_of(
                    universe_data, portfolio.get("as_of") or date.today(),
                    require_complete=False)
                universe_members = universe_snapshot.get("members", [])
                universe_coverage = universe_snapshot.get("coverage")
            except (OSError, ValueError):
                universe_members = []
                universe_coverage = "unavailable"
            monitored = []
            total_initial = 0.0
            total_market = 0.0
            priced_positions = 0
            observed_multiple_positions = 0
            fair_value_positions = 0
            for holding in portfolio.get("holdings", []):
                issuer = by_rut.get(holding.get("company_rut"))
                history = [item for item in observations
                           if issuer and item.get("rut") == issuer.get("rut")]
                initial_value = self._as_float(holding.get("initial_value"))
                market_value = self._as_float(holding.get("market_value"))
                if market_value is not None:
                    priced_positions += 1
                    total_market += market_value
                    if initial_value is not None:
                        total_initial += initial_value
                unit_verification = (eps_units.get("entries") or {}).get(
                    holding.get("company_rut"))
                ticker = str(holding.get("ticker") or "").upper()
                member = next((candidate for candidate in universe_members
                               if candidate.get("ticker") == ticker
                               and candidate.get("rut") == holding.get("company_rut")), None)
                listing_status = ("verified_member_in_snapshot" if member else
                                  "not_verified_by_available_snapshot")
                data_source_gate = None
                if ticker in banks.LISTED_BANKS:
                    data_source_gate = {
                        "status": ("ready" if bank_status.get("feature_ready") else "blocked"),
                        "code": "cmf_banks_accounting_required",
                        "label": "contabilidad bancaria CMF separada pendiente",
                    }
                elif not issuer:
                    data_source_gate = {
                        "status": "blocked", "code": "issuer_not_mapped_to_cmf",
                        "label": "emisor sin mapeo contable CMF verificado",
                    }
                elif not member:
                    data_source_gate = {
                        "status": "blocked", "code": "listing_not_verified",
                        "label": "cotización no verificada en el universo bursátil disponible",
                    }
                valuation = (evaluate_valuation(
                    history, holding.get("market_price"), fx_rate, unit_verification,
                    issuer_rut=issuer.get("rut"))
                    if issuer else None)
                if valuation and valuation.get("pe") is not None:
                    observed_multiple_positions += 1
                if valuation and valuation.get("fair_value") is not None:
                    fair_value_positions += 1
                monitored.append({
                    **holding,
                    "company": issuer.get("company") if issuer else None,
                    "latest_period": issuer.get("latest_available_period") if issuer else None,
                    "analysis": issuer.get("analysis") if issuer else None,
                    "reading": evaluate_observation(issuer, history) if issuer else None,
                    "valuation": valuation,
                    "listing_status": listing_status,
                    "universe_coverage": universe_coverage,
                    "universe_member": member,
                    "data_source_gate": data_source_gate,
                    "events": (event_monitor.get("by_company") or {}).get(
                        normalize_company(issuer.get("company", "")) if issuer else ""),
                    "price_gate": ("renta4_authenticated_snapshot"
                                   if market_value is not None
                                   else "waiting_for_authorized_market_data"),
                })
            for item in monitored:
                value = self._as_float(item.get("market_value"))
                item["allocation_pct"] = value / total_market if value is not None and total_market else None
                item["decision_evidence"] = evaluate_decision_evidence(
                    item.get("reading"), item.get("valuation"), item.get("events"),
                    item.get("allocation_pct"), item.get("data_source_gate"))
            concentration = portfolio_concentration(monitored)
            total_pnl = total_market - total_initial if priced_positions else None
            return self._json(200, {
                "connected": True, "source": portfolio.get("source"),
                "as_of": portfolio.get("as_of"), "holdings": monitored,
                "summary": {
                    "positions": len(monitored), "priced_positions": priced_positions,
                    "observed_multiple_positions": observed_multiple_positions,
                    "fair_value_positions": fair_value_positions,
                    "initial_value": total_initial if priced_positions else None,
                    "market_value": total_market if priced_positions else None,
                    "unrealized_pnl": total_pnl,
                    "return_pct": total_pnl / total_initial if total_pnl is not None and total_initial else None,
                    "available_cash": self._as_float(portfolio.get("available_cash")),
                    "decision_ready": bool(monitored) and fair_value_positions == len(monitored),
                    "latest_market_period": event_monitor.get("latest_market_period"),
                    "current_statement_positions": event_monitor.get("positions_current", 0),
                    "pending_statement_positions": event_monitor.get("positions_pending_in_feed", 0),
                    "recent_notice_positions": event_monitor.get("positions_with_recent_notice", 0),
                    "concentration": concentration,
                },
                "event_monitor_as_of": event_monitor.get("as_of"),
                "event_monitor_disclaimer": event_monitor.get("disclaimer"),
                "fx_rate": fx_rate,
                "orders": "prohibited", "recommendations": "research_only",
            })
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
            universe = self._universe_status()
            market = self._read_json(MARKET_STATUS_PATH) or {}
            price_history_ready = bool(
                market.get("label_ready") and universe.get("survivorship_free_backtest_allowed"))
            state = predictor_readiness(telegram, price_history_ready=price_history_ready)
            dataset = self._read_dataset() or {}
            state["cmf_telegram_join"] = feature_join_report(dataset, telegram)
            state["causal_feature_candidates"] = state["cmf_telegram_join"]["candidate_records"]
            state["fundamental_dataset_feature_use"] = dataset.get("feature_use", "forbidden")
            state["universe"] = universe
            state["market_data"] = market or {"label_ready": False}
            state["cmf_banks"] = banks.availability(BANKS_PATH)
            return self._json(200, state)
        if subpath == "banks-status":
            return self._json(200, banks.availability(BANKS_PATH))
        if subpath == "universe-status":
            return self._json(200, self._universe_status())
        if subpath == "universe":
            try:
                data = load_universe(self._universe_path())
                snapshot = snapshot_as_of(data, date.today(), require_complete=False)
            except (OSError, ValueError) as exc:
                return self._json(503, {"error": str(exc)[:200]})
            return self._json(200, {
                "coverage": snapshot["coverage"],
                "effective_from": snapshot["effective_from"],
                "members": snapshot["members"],
                "sources": data["sources"],
                "research_only": True,
            })
        if subpath == "freshness":
            fuentes = self._fuentes_frescura(
                self._read_dataset(), self._read_telegram(),
                self._read_portfolio((user or {}).get("uid")),
                fx.availability(FX_PATH), banks.availability(BANKS_PATH),
                self._read_json(MARKET_STATUS_PATH))
            return self._json(200, {"sources": fuentes,
                                    "overall": freshness.overall(fuentes),
                                    "modes": freshness.MODES})
        if subpath == "boundaries":
            return self._json(200, {
                "orders": "prohibited", "broker_credentials": "not_stored",
                "predictions": "research_only", "human_approval": "required",
                "claude_authority": "advisory_only",
            })
        return None

    def api_post(self, subpath, body, headers, user=None):
        if subpath == "ingest-telegram-events":
            expected = os.environ.get("NEXUX_CHILE_INGEST_TOKEN", "")
            provided = headers.get("x-nexux-token", "")
            if not expected:
                return self._json(503, {"error": "falta NEXUX_CHILE_INGEST_TOKEN"})
            if not hmac.compare_digest(str(provided), str(expected)):
                return self._json(401, {"error": "token inválido"})
            encoded = json.dumps(body, ensure_ascii=False).encode("utf-8")
            if len(encoded) > MAX_TELEGRAM_BODY_BYTES:
                return self._json(413, {"error": "payload demasiado grande"})
            if (not isinstance(body, dict)
                    or body.get("schema_version") != "acciones-chile-telegram-events-0.1.0"
                    or body.get("source") != "telegram:hechosesencialeschile"
                    or not isinstance(body.get("events"), list)
                    or body.get("event_count") != len(body["events"])):
                return self._json(400, {"error": "export Telegram inválido"})
            allowed_types = {"financial_statement", "essential_notice"}
            required = {"message_id", "available_at", "event_type", "company"}
            if any(not isinstance(event, dict)
                   or not required.issubset(event)
                   or event.get("event_type") not in allowed_types
                   for event in body["events"]):
                return self._json(400, {"error": "evento Telegram inválido"})
            now = datetime.now(timezone.utc)
            for event in body["events"]:
                try:
                    available = datetime.fromisoformat(
                        str(event["available_at"]).replace("Z", "+00:00"))
                except (TypeError, ValueError):
                    return self._json(400, {"error": "available_at Telegram inválido"})
                if available.tzinfo is None or available > now:
                    return self._json(400, {"error": "available_at Telegram fuera de rango"})
            self._write_json_atomic(TELEGRAM_PATH, body, mode=0o600)
            return self._json(200, {"ok": True, "events": len(body["events"])})
        if subpath == "save-portfolio":
            uid = (user or {}).get("uid")
            if uid is None:
                return self._json(401, {"error": "necesitas iniciar sesión"})
            try:
                normalized = normalize_portfolio(body)
            except ValueError as exc:
                return self._json(400, {"error": str(exc)})
            normalized["received_at_ms"] = int(time.time() * 1000)
            self._write_portfolio(int(uid), normalized)
            return self._json(200, {"ok": True, "positions": len(normalized["holdings"])})
        if subpath != "ingest-portfolio":
            return None
        if not self.config.get("portfolio_ingest_enabled", False):
            return self._json(503, {"error": "ingesta de cartera deshabilitada"})
        uid = (user or {}).get("uid")
        if uid is None:
            return self._json(401, {"error": "necesitas iniciar sesión"})
        if len(json.dumps(body, ensure_ascii=False).encode("utf-8")) > MAX_BODY_BYTES:
            return self._json(413, {"error": "payload demasiado grande"})
        try:
            normalized = normalize_portfolio(body)
        except ValueError as exc:
            return self._json(400, {"error": str(exc)})
        normalized["received_at_ms"] = int(time.time() * 1000)
        self._write_portfolio(int(uid), normalized)
        return self._json(200, {"ok": True, "positions": len(normalized["holdings"])})

    def _fuentes_frescura(self, dataset, telegram, portfolio, fx_status, bank_status, market):
        """Una entrada por fuente, con su modo y su antigüedad.

        Los umbrales van con el ritmo real de cada origen: la CMF publica por
        período y no cada minuto, así que exigirle frescura de mercado sería
        marcarla en rojo para siempre.
        """
        cmf = (dataset or {}).get("cmf", {})
        fuentes = (dataset or {}).get("cmf", {}).get("sources", [])
        ultima_cmf = max((item.get("retrieved_at") for item in fuentes
                          if item.get("retrieved_at")), default=None)
        periodos = cmf.get("periods") or []
        fx_cache = self._read_json(FX_PATH) or {}
        fx_latest = (fx_status or {}).get("latest") or {}
        return [
            freshness.describe(
                "CMF · estados financieros IFRS", "official_publication",
                retrieved_at=ultima_cmf,
                observed_at=self._fin_de_periodo(periodos[0]) if periodos else None,
                stale_after_seconds=2 * 86400, available=bool(dataset),
                detail="cierre más reciente descargado: "
                       f"{periodos[0]}" if periodos else "sin descargas todavía"),
            freshness.describe(
                "HechosEsencialesChile · disponibilidad", "official_publication",
                retrieved_at=(telegram or {}).get("exported_at"),
                observed_at=(telegram or {}).get("events", [{}])[0].get("available_at")
                if (telegram or {}).get("events") else None,
                stale_after_seconds=6 * 3600, available=bool(telegram),
                detail="hora del mensaje del bot, no de emisión del documento"),
            freshness.describe(
                "Banco Central · dólar observado", "official_publication",
                retrieved_at=fx_cache.get("retrieved_at"),
                observed_at=fx_latest.get("date"),
                stale_after_seconds=2 * 86400,
                available=bool((fx_status or {}).get("cached")),
                detail=f"{fx_latest.get('clp_per_usd')} CLP/USD"
                       if fx_latest else "sin cache"),
            freshness.describe(
                "Renta 4 · cartera", "snapshot",
                retrieved_at=(portfolio or {}).get("received_at_ms"),
                observed_at=(portfolio or {}).get("as_of"),
                stale_after_seconds=86400, available=bool(portfolio),
                detail="lo capturas tú; no es cotización en vivo"),
            freshness.describe(
                "Bolsa de Santiago · precios", "delayed",
                available=bool((market or {}).get("label_ready")),
                detail="requiere datafeed licenciado; sin contratar todavía"),
            freshness.describe(
                "CMF Bancos", "official_publication",
                available=bool((bank_status or {}).get("cached")),
                detail=(bank_status or {}).get("blockers", ["sin datos"])[0]),
        ]

    @staticmethod
    def _fin_de_periodo(periodo):
        """202606 -> 2026-06-30: la fecha del dato, distinta de su descarga."""
        texto = str(periodo or "")
        if len(texto) != 6 or not texto.isdigit():
            return None
        cierre = {"03": "31", "06": "30", "09": "30", "12": "31"}.get(texto[4:])
        return f"{texto[:4]}-{texto[4:]}-{cierre}" if cierre else None

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

    @staticmethod
    def _read_json(path):
        try:
            with open(path, encoding="utf-8") as handle:
                return json.load(handle)
        except (FileNotFoundError, OSError, ValueError):
            return None

    @staticmethod
    def _as_float(value):
        try:
            return float(value) if value is not None else None
        except (TypeError, ValueError):
            return None

    def _write_json_atomic(self, path: str, data: dict, mode: int | None = None):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        temp = path + ".tmp"
        with self._lock:
            with open(temp, "w", encoding="utf-8") as handle:
                json.dump(data, handle, ensure_ascii=False, separators=(",", ":"))
                handle.flush()
                os.fsync(handle.fileno())
            if mode is not None:
                os.chmod(temp, mode)
            os.replace(temp, path)

    @staticmethod
    def _universe_status():
        try:
            path = (LOCAL_UNIVERSE_PATH if os.path.isfile(LOCAL_UNIVERSE_PATH)
                    else PACKAGED_UNIVERSE_PATH)
            status = universe_status(load_universe(path), date.today())
            status["storage"] = "local_licensed" if path == LOCAL_UNIVERSE_PATH else "packaged_public"
            return status
        except (OSError, ValueError) as exc:
            return {
                "coverage": "unavailable", "member_count": 0,
                "survivorship_free_backtest_allowed": False,
                "blockers": [str(exc)[:200]],
            }

    @staticmethod
    def _universe_path():
        return LOCAL_UNIVERSE_PATH if os.path.isfile(LOCAL_UNIVERSE_PATH) else PACKAGED_UNIVERSE_PATH

    def _refresh_loop(self):
        """Sondeo barato frecuente, descarga cara sólo cuando hay algo nuevo.

        La CMF publica por período, no en flujo continuo: bajar los TXT
        completos cada pocos minutos serían cientos de descargas diarias de un
        archivo que cambia unas pocas veces al año. En cambio se consulta la
        página de listado —una petición— y sólo se descarga cuando aparece un
        cierre que el cache no tiene, o cuando el cache cumplió su edad máxima.
        """
        refresco = max(3600, int(self.config.get("cmf_refresh_interval_seconds", 86400)))
        sondeo = max(600, int(self.config.get("cmf_probe_interval_seconds", 3600)))
        sondeo = min(sondeo, refresco)
        while not self._stop_event.is_set():
            existing = self._read_dataset()
            age = time.time() - ((existing or {}).get("generated_at_ms", 0) / 1000)
            motivo = None
            if not existing:
                motivo = "sin cache"
            elif age >= refresco:
                motivo = "cache cumplió su edad máxima"
            else:
                nuevo = self._periodo_nuevo(existing)
                if nuevo:
                    motivo = f"la CMF publicó {nuevo}"
            if motivo:
                try:
                    dataset_store.refresh_dataset(
                        DATASET_PATH, base_url=self.config.get("cmf_base_url") or dataset_store.DEFAULT_URL)
                    self.context.log(f"acciones_chile: dataset CMF/YouTube actualizado ({motivo})")
                except Exception as exc:  # noqa: BLE001 - conservar cache y reintentar luego
                    self.context.log(f"acciones_chile: actualización falló cerrada: {exc}")
            fx_data = fx.read_fx_dataset(FX_PATH)
            try:
                fx_age = time.time() - datetime.fromisoformat(
                    str((fx_data or {}).get("retrieved_at"))).timestamp()
            except (TypeError, ValueError):
                fx_age = refresco
            if not fx_data or fx_age >= refresco:
                try:
                    public_download = fx.download_public_observed_dollar()
                    fx.write_fx_dataset(FX_PATH, fx.build_public_fx_dataset(public_download))
                    self.context.log("acciones_chile: dólar observado BCCh público actualizado")
                except Exception as exc:  # noqa: BLE001 - conservar cache y reintentar luego
                    self.context.log(f"acciones_chile: dólar BCCh falló cerrado: {exc}")
            self._stop_event.wait(sondeo)

    def _periodo_nuevo(self, dataset):
        """Consulta el listado de la CMF y devuelve el cierre que falte, si hay.

        Falla cerrado a `None`: si el listado no responde se conserva el cache y
        se reintenta en el próximo sondeo, sin descargar nada por las dudas.
        """
        try:
            publicados = cmf_client.available_periods()
        except Exception:  # noqa: BLE001 - una caída del listado no gatilla descargas
            return None
        conocidos = set((dataset.get("cmf") or {}).get("periods") or [])
        candidatos = dataset_store.select_refresh_periods(publicados)
        faltantes = [periodo for periodo in candidatos if periodo not in conocidos]
        return faltantes[0] if faltantes else None

    def health(self):
        return {"slug": self.slug, "status": "ok", "mode": "read_only",
                "portfolio_storage": "per_user",
                "dataset_ready": bool(self._read_dataset()),
                "telegram_events_ready": bool(self._read_telegram())}


def get_module(context):
    return AccionesChileModule(context)
