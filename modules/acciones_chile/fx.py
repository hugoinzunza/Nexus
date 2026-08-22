"""Dólar observado oficial BCCh para valoración read-only.

La API requiere un token personal. El token sólo viaja al host allowlisted y
nunca se persiste en URLs, cache, errores ni snapshots de auditoría.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation


API_HOST = "si3.bcentral.cl"
API_PATH = "/SieteRestWS/SieteRestWS.ashx"
SERIES_ID = "F073.TCO.PRE.Z.D"
TOKEN_ENV = "BCCH_API_TOKEN"
SCHEMA_VERSION = "acciones-chile-fx-0.1.0"
EPS_UNIT_SCHEMA_VERSION = "acciones-chile-eps-units-0.1.0"
MAX_DOWNLOAD_BYTES = 1_000_000


@dataclass(frozen=True)
class FxDownload:
    payload: bytes
    effective_url_redacted: str
    retrieved_at: str
    http_status: int
    content_length: int | None
    bytes_received: int


def _validated_url(first_date: str | date, last_date: str | date,
                   token: str) -> tuple[str, str]:
    try:
        start = date.fromisoformat(str(first_date))
        end = date.fromisoformat(str(last_date))
    except ValueError as exc:
        raise ValueError("fecha BCCh inválida") from exc
    if end < start or (end - start).days > 400:
        raise ValueError("rango BCCh inválido")
    if not isinstance(token, str) or not token.strip():
        raise ValueError(f"falta {TOKEN_ENV}")
    public_query = {
        "function": "GetSeries", "timeseries": SERIES_ID,
        "firstdate": start.isoformat(), "lastdate": end.isoformat(),
    }
    private_query = {"token": token.strip(), **public_query}
    url = urllib.parse.urlunparse(("https", API_HOST, API_PATH, "",
                                   urllib.parse.urlencode(private_query), ""))
    redacted = urllib.parse.urlunparse(("https", API_HOST, API_PATH, "",
                                        urllib.parse.urlencode(public_query), ""))
    return url, redacted


def download_observed_dollar(first_date: str | date, last_date: str | date,
                             token: str, timeout: float = 30.0) -> FxDownload:
    url, redacted = _validated_url(first_date, last_date, token)
    request = urllib.request.Request(url, headers={"User-Agent": "NexUX-AccionesChile/0.1"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 - allowlist
            final = urllib.parse.urlparse(response.geturl())
            if (final.scheme, final.hostname, final.path) != ("https", API_HOST, API_PATH):
                raise ValueError("BCCh redirigió fuera del endpoint autorizado")
            declared = response.headers.get("Content-Length")
            content_length = int(declared) if declared and declared.isdigit() else None
            body = response.read(MAX_DOWNLOAD_BYTES + 1)
            status = int(getattr(response, "status", 200))
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, OSError):
        raise ValueError("consulta BCCh falló") from None
    if len(body) > MAX_DOWNLOAD_BYTES:
        raise ValueError("respuesta BCCh excede el límite permitido")
    if content_length is not None and len(body) != content_length:
        raise ValueError("respuesta BCCh truncada según Content-Length")
    return FxDownload(
        payload=body, effective_url_redacted=redacted,
        retrieved_at=datetime.now(timezone.utc).isoformat(), http_status=status,
        content_length=content_length, bytes_received=len(body),
    )


def parse_observed_dollar(payload: bytes | str) -> list[dict]:
    try:
        document = json.loads(payload.decode("utf-8-sig") if isinstance(payload, bytes) else payload)
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError) as exc:
        raise ValueError("respuesta BCCh no es JSON válido") from exc
    if not isinstance(document, dict) or document.get("Codigo") != 0:
        raise ValueError("BCCh no respondió Success")
    series = document.get("Series") or {}
    if series.get("seriesId") != SERIES_ID or not isinstance(series.get("Obs"), list):
        raise ValueError("BCCh entregó una serie inesperada")
    rows, seen = [], set()
    for index, item in enumerate(series["Obs"], start=1):
        if not isinstance(item, dict):
            raise ValueError(f"observación BCCh {index} inválida")
        if item.get("statusCode") != "OK":
            continue
        try:
            observed = datetime.strptime(str(item["indexDateString"]), "%d-%m-%Y").date()
            value = Decimal(str(item["value"]))
        except (KeyError, ValueError, InvalidOperation) as exc:
            raise ValueError(f"observación BCCh {index} inválida") from exc
        if observed in seen or not value.is_finite() or not Decimal("100") <= value <= Decimal("5000"):
            raise ValueError(f"observación BCCh {index} fuera de contrato")
        seen.add(observed)
        rows.append({"date": observed.isoformat(), "clp_per_usd": format(value, "f")})
    rows.sort(key=lambda item: item["date"])
    if not rows:
        raise ValueError("BCCh no entregó observaciones válidas")
    return rows


def build_fx_dataset(download: FxDownload) -> dict:
    observations = parse_observed_dollar(download.payload)
    return {
        "schema_version": SCHEMA_VERSION,
        "source": "Banco Central de Chile BDE API",
        "series_id": SERIES_ID, "unit": "CLP_PER_USD",
        "retrieved_at": download.retrieved_at,
        "observations": observations, "latest": observations[-1],
        "provenance": {
            "url": download.effective_url_redacted, "http_status": download.http_status,
            "content_length": download.content_length,
            "bytes_received": download.bytes_received,
            "sha256": hashlib.sha256(download.payload).hexdigest(),
        },
    }


def validate_fx_dataset(data: dict) -> dict:
    if not isinstance(data, dict) or data.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("schema de dólar observado no soportado")
    if (data.get("source"), data.get("series_id"), data.get("unit")) != (
            "Banco Central de Chile BDE API", SERIES_ID, "CLP_PER_USD"):
        raise ValueError("identidad de serie BCCh inválida")
    try:
        datetime.fromisoformat(str(data.get("retrieved_at")))
    except ValueError as exc:
        raise ValueError("fecha de recuperación BCCh inválida") from exc
    observations = data.get("observations")
    if not isinstance(observations, list) or not observations:
        raise ValueError("cache BCCh sin observaciones")
    validated, seen = [], set()
    for item in observations:
        if not isinstance(item, dict) or set(item) != {"date", "clp_per_usd"}:
            raise ValueError("observación de cache BCCh inválida")
        try:
            observed = date.fromisoformat(str(item["date"]))
            value = Decimal(str(item["clp_per_usd"]))
        except (ValueError, InvalidOperation) as exc:
            raise ValueError("observación de cache BCCh inválida") from exc
        if observed in seen or not value.is_finite() or not Decimal("100") <= value <= Decimal("5000"):
            raise ValueError("observación de cache BCCh fuera de contrato")
        seen.add(observed)
        validated.append(observed)
    if validated != sorted(validated) or data.get("latest") != observations[-1]:
        raise ValueError("orden o último valor de cache BCCh inválido")
    provenance = data.get("provenance")
    if not isinstance(provenance, dict):
        raise ValueError("procedencia BCCh inválida")
    parsed_url = urllib.parse.urlparse(str(provenance.get("url") or ""))
    query = urllib.parse.parse_qs(parsed_url.query, strict_parsing=True)
    expected_query_keys = {"function", "timeseries", "firstdate", "lastdate"}
    if ((parsed_url.scheme, parsed_url.hostname, parsed_url.path) !=
            ("https", API_HOST, API_PATH) or set(query) != expected_query_keys or
            query.get("function") != ["GetSeries"] or query.get("timeseries") != [SERIES_ID] or
            "token" in parsed_url.query.lower()):
        raise ValueError("URL pública BCCh inválida")
    if provenance.get("http_status") != 200:
        raise ValueError("estado HTTP BCCh inválido")
    if not isinstance(provenance.get("bytes_received"), int) or not (
            0 < provenance["bytes_received"] <= MAX_DOWNLOAD_BYTES):
        raise ValueError("tamaño de respuesta BCCh inválido")
    declared = provenance.get("content_length")
    if declared is not None and declared != provenance["bytes_received"]:
        raise ValueError("Content-Length BCCh inconsistente")
    if not re.fullmatch(r"[0-9a-f]{64}", str(provenance.get("sha256") or "")):
        raise ValueError("hash de respuesta BCCh inválido")
    return data


def rate_as_of(data: dict | None, as_of: str | date) -> dict | None:
    try:
        valid = validate_fx_dataset(data)
        target = date.fromisoformat(str(as_of))
    except (ValueError, TypeError):
        return None
    eligible = [item for item in valid["observations"]
                if date.fromisoformat(item["date"]) <= target]
    return eligible[-1] if eligible else None


def read_fx_dataset(path: str) -> dict | None:
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
        return validate_fx_dataset(data)
    except (FileNotFoundError, OSError, ValueError, AttributeError):
        return None


def write_fx_dataset(path: str, data: dict) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    temp = path + ".tmp"
    with open(temp, "w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, separators=(",", ":"))
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temp, path)


def availability(path: str | None = None) -> dict:
    data = read_fx_dataset(path) if path else None
    key_present = bool(os.environ.get(TOKEN_ENV))
    blockers = []
    if not key_present:
        blockers.append(f"falta {TOKEN_ENV}")
    if not data:
        blockers.append("falta cache dólar observado BCCh")
    return {
        "source": "Banco Central de Chile BDE API", "series_id": SERIES_ID,
        "key_present": key_present, "cached": bool(data),
        "latest": (data or {}).get("latest"),
        "fx_ready": bool(data), "blockers": blockers,
        "credential_persisted": False,
    }


def validate_eps_unit_dataset(data: dict) -> dict:
    if not isinstance(data, dict) or data.get("schema_version") != EPS_UNIT_SCHEMA_VERSION:
        raise ValueError("schema de unidades EPS no soportado")
    entries = data.get("entries")
    if not isinstance(entries, dict):
        raise ValueError("unidades EPS sin entries")
    for rut, record in entries.items():
        if not re.fullmatch(r"\d{7,8}", str(rut)) or not isinstance(record, dict):
            raise ValueError("registro de unidad EPS inválido")
        if record.get("status") != "verified":
            raise ValueError(f"unidad EPS de {rut} no verificada")
        if record.get("unit") not in {"CLP_PER_SHARE", "USD_PER_SHARE"}:
            raise ValueError(f"unidad EPS de {rut} no soportada")
        if record.get("verification_method") not in {
                "audited_annual_report_note", "issuer_disclosure"}:
            raise ValueError(f"método de unidad EPS de {rut} insuficiente")
        if not str(record.get("source_reference") or "").startswith("https://"):
            raise ValueError(f"fuente de unidad EPS de {rut} inválida")
        if not re.fullmatch(r"[0-9a-f]{64}", str(record.get("source_sha256") or "")):
            raise ValueError(f"hash de unidad EPS de {rut} inválido")
        try:
            date.fromisoformat(str(record.get("verified_as_of")))
        except ValueError as exc:
            raise ValueError(f"fecha de unidad EPS de {rut} inválida") from exc
    return data


def read_eps_unit_dataset(path: str) -> dict | None:
    try:
        with open(path, encoding="utf-8") as handle:
            return validate_eps_unit_dataset(json.load(handle))
    except (FileNotFoundError, OSError, ValueError, AttributeError):
        return None
