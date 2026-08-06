"""Hypothesis Lab: evidencia historica y observadores forward, solo lectura."""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

from core.module_base import NexusModule


ROOT = Path(__file__).resolve().parents[2]
REPORTS = ROOT / "research" / "hypothesis_lab" / "reports"


# Cuánto puede pasar un observador sin registrar NADA nuevo antes de declararlo detenido.
# No es un umbral científico y no toca ningún protocolo: es plomería.
#
# Existe porque el 2026-08-06 una auditoría encontró dos cohortes en cero mientras este
# módulo reportaba "ok": la frescura medía que el ARCHIVO se reescribía, no que llegaran
# DATOS. Un observador que reescribe puntualmente un JSON vacío se veía igual de sano que
# uno capturando evidencia.
#
# Calibrado con los huecos reales entre llegadas de la cohorte HYP-EXIT-003 (n=28):
# mediana 1,4 h · p90 12,2 h · máximo observado 17,4 h. 24 h deja margen sobre el máximo
# natural sin volver a tolerar un apagón de días. Es el detector LENTO; el rápido es la
# salud de la fuente, que abajo se mide en minutos.
MAX_SILENCE_SECONDS = 24 * 3600
# Latido del servicio que publica la fuente canónica. No mide contenido —mide que el
# proceso siga leyendo sus orígenes—, y por eso puede ser estrecho: es lo que habría
# detectado el apagón del 2026-08-03 en quince minutos en vez de en dos días y medio.
SOURCE_MAX_AGE_SECONDS = 900
_PROGRESS_RELATIVE = ("hypothesis_lab", "telemetry", "observer_progress.json")


def _newest_ms(values: Any) -> int | None:
    """El timestamp más nuevo de una colección, ignorando lo que no sea numérico."""
    numbers = [int(item) for item in values if isinstance(item, (int, float))]
    return max(numbers) if numbers else None


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _latest(pattern: str) -> dict[str, Any]:
    matches = sorted(REPORTS.glob(pattern))
    return _read_json(matches[-1]) if matches else {}


def _number(value: Any) -> float | None:
    return float(value) if isinstance(value, (int, float)) else None


class HypothesisLabModule(NexusModule):
    slug = "hypothesis-lab"
    title = "Laboratorio de hipotesis"
    description = "Evidencia causal, cohortes forward y protocolos de decision."
    icon = "HL"

    def __init__(self, context):
        super().__init__(context)
        configured = str(self.config.get("runtime_data_root") or "").strip()
        env_root = os.environ.get("NEXUX_RESEARCH_RUNTIME_ROOT", "").strip()
        self.runtime_root = Path(configured or env_root or (ROOT / "data"))

    def public_dir(self):
        return str(Path(__file__).with_name("public"))

    @staticmethod
    def _freshness(path: Path, expected_seconds: int) -> dict[str, Any]:
        payload = _read_json(path)
        generated = payload.get("meta", {}).get("generated_at_ms")
        if not isinstance(generated, (int, float)):
            return {
                "status": "missing", "generated_at_ms": None,
                "age_seconds": None, "path_exists": path.exists(),
            }
        age = max(0.0, time.time() - generated / 1000)
        if payload.get("meta", {}).get("errors") or payload.get("meta", {}).get("load_errors"):
            status = "degraded"
        else:
            status = "fresh" if age <= expected_seconds else "stale"
        return {
            "status": status,
            "generated_at_ms": int(generated),
            "age_seconds": round(age, 1),
            "path_exists": True,
        }

    # --- movimiento real de registros -----------------------------------
    #
    # La frescura del archivo dice que el proceso está VIVO. No dice que esté CAPTURANDO.
    # Para eso se miran dos señales independientes:
    #
    #   1. Intrínseca: la fecha del registro más nuevo dentro del propio payload. Es
    #      stateless y es correcta desde el primer arranque, sin historia previa.
    #   2. Persistida: cuándo cambió por última vez el conteo de registros. Atrapa el caso
    #      en que hay registros con fecha reciente pero la cohorte dejó de crecer.
    #
    # Se toma la más reciente de las dos: si cualquiera de las dos se movió, hubo captura.

    def _progress_path(self) -> Path:
        return self.runtime_root.joinpath(*_PROGRESS_RELATIVE)

    def _read_progress(self) -> dict[str, Any]:
        entries = _read_json(self._progress_path()).get("observers")
        return entries if isinstance(entries, dict) else {}

    def _write_progress(self, entries: dict[str, Any]) -> None:
        """Telemetría de plomería: si no se puede escribir, no pasa nada. Nunca puede
        tumbar el estado del laboratorio."""
        path = self._progress_path()
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_suffix(path.suffix + f".{os.getpid()}.tmp")
            temporary.write_text(
                json.dumps({"observers": entries}, ensure_ascii=False,
                           indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            os.replace(temporary, path)
        except OSError:
            pass

    def _canonical_health(self) -> dict[str, Any]:
        """Salud de la fuente canónica de setups.

        Se mira el artefacto CON METADATOS, no la lista plana: la plana solo se reescribe
        cuando cambia su contenido (a propósito), así que su antigüedad no dice nada sobre
        si el servicio sigue vivo. El artefacto con metadatos se reescribe en cada pasada
        y además declara si cada origen se pudo leer."""
        payload = _read_json(
            self.runtime_root / "hypothesis_lab" / "canonical" / "setups_canonical.json"
        )
        meta = payload.get("meta", {})
        generated = meta.get("generated_at_ms")
        if not isinstance(generated, (int, float)):
            return {"status": "missing", "age_seconds": None, "sources": [], "missing_sources": []}
        sources = meta.get("sources", []) or []
        missing = [item.get("path") for item in sources if not item.get("present")]
        age = max(0.0, time.time() - generated / 1000)
        if missing:
            status = "degraded"
        elif age > SOURCE_MAX_AGE_SECONDS:
            status = "stale"
        else:
            status = "fresh"
        return {
            "status": status,
            "age_seconds": round(age, 1),
            "generated_at_ms": int(generated),
            "total_setups": meta.get("total"),
            "newest_ts_activated": meta.get("newest_ts_activated"),
            "sources": [
                {"path": item.get("path"), "present": item.get("present"),
                 "read": item.get("read"), "error": item.get("error")}
                for item in sources
            ],
            "missing_sources": missing,
        }

    def _apply_movement(self, observers: dict[str, Any]) -> dict[str, Any]:
        """Corrige el estado de cada observador según si de verdad entraron registros."""
        now_ms = int(time.time() * 1000)
        stored = self._read_progress()
        updated: dict[str, Any] = {}

        for name, observer in observers.items():
            count = observer.get("records")
            count = int(count) if isinstance(count, (int, float)) else 0
            previous = stored.get(name) if isinstance(stored.get(name), dict) else {}

            # Señal intrínseca: el registro más nuevo del payload, o el inicio de cohorte
            # cuando todavía no hay ninguno (una cohorte recién abierta no está detenida).
            intrinsic = observer.pop("_newest_record_ms", None)
            intrinsic = int(intrinsic) if isinstance(intrinsic, (int, float)) else None

            # Ledger de conteo: solo se mueve la marca cuando el conteo cambia de verdad.
            # La primera vez que se ve un observador NO hay historia, así que se siembra
            # con la señal intrínseca y no con "ahora": sembrar con ahora inventaría un
            # movimiento que nunca ocurrió y volvería a esconder una cohorte detenida.
            if previous.get("records") == count and isinstance(previous.get("count_changed_ms"), (int, float)):
                count_changed_ms = int(previous["count_changed_ms"])
            elif previous:
                count_changed_ms = now_ms
            else:
                count_changed_ms = intrinsic or now_ms
            updated[name] = {
                "records": count,
                "count_changed_ms": count_changed_ms,
                "first_seen_ms": int(previous.get("first_seen_ms") or now_ms),
            }

            # Basta con que CUALQUIERA de las dos señales se haya movido: un mercado quieto
            # puede dejar el registro más nuevo atrás sin que la cañería esté rota.
            reference = _newest_ms([intrinsic, count_changed_ms])
            silence = max(0.0, (now_ms - reference) / 1000) if reference else None

            source = observer.pop("_source", None) or {}
            limit = observer.pop("_max_silence_seconds", None) or MAX_SILENCE_SECONDS

            observer["last_record_ms"] = intrinsic
            observer["silence_seconds"] = round(silence, 1) if silence is not None else None
            observer["max_silence_seconds"] = limit
            observer["source_status"] = source.get("status")
            observer["source_age_seconds"] = source.get("age_seconds")
            observer["capturing"] = bool(silence is not None and silence <= limit)

            # Un estado ya degradado o ausente manda: no se pisa con esto.
            if observer["status"] in ("missing", "degraded"):
                continue
            if source.get("status") in ("missing", "stale", "degraded"):
                observer["status"] = "stalled"
                observer["stalled_reason"] = f"source_{source['status']}"
            elif silence is None or silence > limit:
                observer["status"] = "stalled"
                observer["stalled_reason"] = "no_new_records"

        self._write_progress(updated)
        return observers

    def _state(self) -> dict[str, Any]:
        exit_1 = _latest("HYP-EXIT-001-*.summary.json")
        exit_2 = _latest("HYP-EXIT-002-*.summary.json")
        cost_1 = _latest("HYP-COST-001-*.summary.json")
        cost_2 = _latest("HYP-COST-002-*.summary.json")
        shadow_path = self.runtime_root / "hypothesis_lab" / "shadow" / "protect_3r_runner_original.json"
        telemetry_path = self.runtime_root / "hypothesis_lab" / "telemetry" / "execution_costs.json"
        canonical_path = self.runtime_root / "hypothesis_lab" / "canonical" / "setups.json"
        shadow = _read_json(shadow_path)
        telemetry = _read_json(telemetry_path)

        # Fecha del registro más nuevo de cada cohorte. Cuando todavía no hay ninguno, se
        # usa el inicio de la cohorte: recién abierta no es lo mismo que detenida.
        canonical = self._canonical_health()
        shadow_newest = _newest_ms(
            [row.get("entry_at_ms") for row in shadow.get("records", [])]
        ) or shadow.get("meta", {}).get("cohort_start_ms")
        telemetry_newest = _newest_ms(
            [row.get("opened_at_ms") for row in telemetry.get("records", [])]
        ) or telemetry.get("meta", {}).get("cohort_start_ms")

        base = exit_1.get("aggregate_metrics", {}).get("base:original", {})
        protected = exit_2.get("paired_comparisons", {}).get("protect_3r_runner_original", {})
        cost_base = cost_1.get("aggregate_metrics", {}).get("base:1", {})
        cost_holm = cost_2.get("holm_primary_family") or []
        shadow_meta = shadow.get("meta", {})
        shadow_decision = shadow.get("decision", {})
        telemetry_meta = telemetry.get("meta", {})
        telemetry_decision = telemetry.get("decision", {})

        return {
            "research_only": True,
            "execution_enabled": False,
            "notice": "Research only · No señal · No bot",
            "generated_at_ms": int(time.time() * 1000),
            "observers": self._apply_movement({
                "shadow_exit": {
                    **self._freshness(shadow_path, 180),
                    "hypothesis_id": "HYP-EXIT-003-SHADOW",
                    "records": shadow_meta.get("n_records", 0),
                    "paired_closed": shadow_meta.get("n_paired_closed", 0),
                    "reached_3r": shadow_meta.get("n_reached_3r", 0),
                    "decision": shadow_decision.get("status", "not_available"),
                    "errors": shadow_meta.get("errors", []),
                    "_newest_record_ms": shadow_newest,
                    "_source": canonical,
                },
                "cost_telemetry": {
                    **self._freshness(telemetry_path, 180),
                    "hypothesis_id": "HYP-COST-003-TELEMETRY",
                    "records": telemetry_meta.get("n_records", 0),
                    "decision": telemetry_decision.get("status", "not_available"),
                    "load_errors": telemetry_meta.get("load_errors", []),
                    "coverage": telemetry_decision.get("primary_live_counts", {}),
                    "_newest_record_ms": telemetry_newest,
                    # No lee setups sino los libros del bot: su fuente es otra y su
                    # ausencia ya viaja en load_errors.
                    "_source": None,
                },
            }),
            "studies": [
                {
                    "id": "HYP-EXIT-001", "family": "Salidas", "state": "closed",
                    "title": "Geometria pareada de TP/RR",
                    "verdict": "Los parciales 2R/3R reducen expectativa; 5R no supera al original.",
                    "n": base.get("n_used"), "avg_r": _number(base.get("avg_net_r")),
                    "profit_factor": _number(base.get("profit_factor_net")),
                    "promotion": False,
                },
                {
                    "id": "HYP-EXIT-002", "family": "Salidas", "state": "candidate",
                    "title": "Proteccion del runner al alcanzar 3R",
                    "verdict": "Unico candidato; el IC95 aun incluye cero.",
                    "n": protected.get("n_paired"),
                    "delta_avg_r": _number(protected.get("mean_difference_net_r")),
                    "ci95": protected.get("ci95"), "promotion": False,
                },
                {
                    "id": "HYP-EXIT-003-SHADOW", "family": "Salidas", "state": "collecting",
                    "title": "Cohorte forward protect_3r_runner_original",
                    "verdict": "Observacion paralela; no modifica operaciones.",
                    "n": shadow_meta.get("n_records", 0),
                    "paired_closed": shadow_meta.get("n_paired_closed", 0),
                    "reached_3r": shadow_meta.get("n_reached_3r", 0),
                    "promotion": False,
                },
                {
                    "id": "HYP-COST-001", "family": "Costos", "state": "closed",
                    "title": "Stops estrechos bajo friccion declarada",
                    "verdict": "Exploratorio; no autoriza recalibrar costos ni estrategia.",
                    "n": cost_base.get("n"), "avg_r": _number(cost_base.get("avg_net_r")),
                    "profit_factor": _number(cost_base.get("profit_factor_net")),
                    "promotion": False,
                },
                {
                    "id": "HYP-COST-002", "family": "Costos", "state": "closed",
                    "title": "Viabilidad operacional de stops estrechos",
                    "verdict": "Ninguna comparacion primaria sobrevive Holm.",
                    "n": cost_2.get("selected_setups"),
                    "holm_rejections": sum(1 for row in cost_holm if row.get("reject_null")),
                    "promotion": False,
                },
                {
                    "id": "HYP-COST-003-TELEMETRY", "family": "Costos", "state": "collecting",
                    "title": "Telemetria forward de ejecucion",
                    "verdict": "Espera operaciones live elegibles; Testnet es diagnostico y no satisface el minimo.",
                    "n": telemetry_meta.get("n_records", 0), "promotion": False,
                },
            ],
            "protocol": shadow.get("decision_protocol", {}),
            # Fuentes reales, no las de un repo que quedó atrás. Los setups entran por la
            # canónica del laboratorio; los libros del bot se leen del repo desde el que
            # corre este servidor, que es por definición la instancia viva.
            "sources": {
                "canonical_setups": canonical,
                "main_ledger": self._file_meta(ROOT / "data" / "bot_trades.json"),
                "testnet_ledger": self._file_meta(ROOT / "data" / "testnet" / "bot_trades.json"),
            },
        }

    @staticmethod
    def _file_meta(path: Path, fresh_seconds: int = 86_400) -> dict[str, Any]:
        try:
            stat = path.stat()
        except OSError:
            return {"status": "missing", "updated_at_ms": None, "age_seconds": None}
        age = max(0.0, time.time() - stat.st_mtime)
        return {
            "status": "fresh" if age <= fresh_seconds else "stale",
            "updated_at_ms": int(stat.st_mtime * 1000),
            "age_seconds": round(age, 1), "bytes": stat.st_size,
        }

    def api(self, subpath, query, user=None):
        if subpath != "state":
            return None
        payload = json.dumps(self._state(), ensure_ascii=False).encode("utf-8")
        return 200, "application/json; charset=utf-8", payload

    def health(self):
        """Sano solo si TODOS los observadores están capturando.

        Antes bastaba con que los tres archivos de salida fueran recientes, y por eso el
        módulo reportó "ok" durante días con dos cohortes en cero. Ahora un observador que
        no recibe registros nuevos sale `stalled` aunque reescriba su JSON cada minuto, y
        eso arrastra el health del módulo entero."""
        state = self._state()
        observers = state["observers"]
        statuses = {name: item["status"] for name, item in observers.items()}
        stalled = sorted(name for name, value in statuses.items() if value == "stalled")
        degraded = sorted(
            name for name, value in statuses.items() if value in ("degraded", "missing", "stale")
        )
        return {
            "slug": self.slug,
            "status": "ok" if set(statuses.values()) == {"fresh"} else "degraded",
            "mode": "research", "execution": False,
            "observers": statuses,
            "stalled": stalled,
            "degraded_observers": degraded,
            "capturing": sorted(name for name, item in observers.items() if item.get("capturing")),
        }


def get_module(context):
    return HypothesisLabModule(context)
