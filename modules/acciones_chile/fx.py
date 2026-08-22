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
from html.parser import HTMLParser


API_HOST = "si3.bcentral.cl"
API_PATH = "/SieteRestWS/SieteRestWS.ashx"
PUBLIC_PATH = "/Siete/ES/Siete/Cuadro/CAP_TIPO_CAMBIO/MN_TIPO_CAMBIO4/DOLAR_OBS_ADO"
SERIES_ID = "F073.TCO.PRE.Z.D"
TOKEN_ENV = "BCCH_API_TOKEN"
SCHEMA_VERSION = "acciones-chile-fx-0.1.0"
EPS_UNIT_SCHEMA_VERSION = "acciones-chile-eps-units-0.2.0"
MAX_DOWNLOAD_BYTES = 1_000_000
PUBLIC_URL = urllib.parse.urlunparse((
    "https", API_HOST, PUBLIC_PATH, "", urllib.parse.urlencode({"idSerie": SERIES_ID}), ""))


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


class _ObservationTableParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.in_table = False
        self.in_cell = False
        self.table_count = 0
        self.cell_parts: list[str] = []
        self.row: list[str] = []
        self.rows: list[list[str]] = []

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if tag == "table" and attributes.get("id") == "listaObsHtmlAll":
            self.in_table = True
            self.table_count += 1
        elif self.in_table and tag == "td":
            self.in_cell = True
            self.cell_parts = []

    def handle_data(self, data):
        if self.in_cell:
            self.cell_parts.append(data)

    def handle_endtag(self, tag):
        if self.in_table and tag == "td" and self.in_cell:
            self.row.append("".join(self.cell_parts).strip())
            self.in_cell = False
        elif self.in_table and tag == "tr":
            if self.row:
                self.rows.append(self.row)
            self.row = []
        elif self.in_table and tag == "table":
            self.in_table = False


def parse_public_observed_dollar(payload: bytes | str) -> list[dict]:
    try:
        text = payload.decode("utf-8-sig") if isinstance(payload, bytes) else str(payload)
    except UnicodeDecodeError as exc:
        raise ValueError("tabla pública BCCh no es UTF-8 válido") from exc
    parser = _ObservationTableParser()
    parser.feed(text)
    if parser.table_count != 1 or not parser.rows:
        raise ValueError("tabla pública BCCh no encontrada o ambigua")
    months = {name: index for index, name in enumerate(
        ("Ene", "Feb", "Mar", "Abr", "May", "Jun", "Jul", "Ago", "Sep", "Oct", "Nov", "Dic"), 1)}
    rows, seen = [], set()
    for index, cells in enumerate(parser.rows, 1):
        if len(cells) != 2:
            raise ValueError(f"fila pública BCCh {index} inválida")
        try:
            day_text, month_text, year_text = cells[0].split(".")
            observed = date(int(year_text), months[month_text], int(day_text))
            value = Decimal(cells[1].replace(".", "").replace(",", "."))
        except (ValueError, KeyError, InvalidOperation) as exc:
            raise ValueError(f"fila pública BCCh {index} inválida") from exc
        if not value.is_finite() or value > Decimal("5000"):
            raise ValueError(f"fila pública BCCh {index} fuera de contrato")
        if observed > date.today():
            continue
        # La tabla pública incluye toda la historia desde 1982. El contrato de
        # valoración moderno conserva sólo observaciones >= 100 CLP/USD.
        if value < Decimal("100"):
            continue
        if observed in seen:
            raise ValueError(f"fila pública BCCh {index} duplicada")
        seen.add(observed)
        rows.append({"date": observed.isoformat(), "clp_per_usd": format(value, "f")})
    rows.sort(key=lambda item: item["date"])
    return rows


def download_public_observed_dollar(timeout: float = 30.0) -> FxDownload:
    request = urllib.request.Request(PUBLIC_URL, headers={"User-Agent": "NexUX-AccionesChile/0.1"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 - allowlist
            final = urllib.parse.urlparse(response.geturl())
            endpoint = (final.scheme, final.hostname, final.path)
            query = (urllib.parse.parse_qs(final.query, strict_parsing=True)
                     if endpoint == ("https", API_HOST, PUBLIC_PATH) else {})
            if (endpoint != ("https", API_HOST, PUBLIC_PATH)
                    or query != {"idSerie": [SERIES_ID]}):
                raise ValueError("BCCh público redirigió fuera del endpoint autorizado")
            declared = response.headers.get("Content-Length")
            content_length = int(declared) if declared and declared.isdigit() else None
            body = response.read(MAX_DOWNLOAD_BYTES + 1)
            status = int(getattr(response, "status", 200))
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, OSError):
        raise ValueError("consulta pública BCCh falló") from None
    if len(body) > MAX_DOWNLOAD_BYTES:
        raise ValueError("tabla pública BCCh excede el límite permitido")
    if content_length is not None and len(body) != content_length:
        raise ValueError("tabla pública BCCh truncada según Content-Length")
    return FxDownload(
        payload=body, effective_url_redacted=PUBLIC_URL,
        retrieved_at=datetime.now(timezone.utc).isoformat(), http_status=status,
        content_length=content_length, bytes_received=len(body),
    )


def build_fx_dataset(download: FxDownload) -> dict:
    observations = parse_observed_dollar(download.payload)
    return _build_fx_dataset(download, observations, "authenticated_api")


def build_public_fx_dataset(download: FxDownload) -> dict:
    observations = parse_public_observed_dollar(download.payload)
    return _build_fx_dataset(download, observations, "public_bde_html")


def _build_fx_dataset(download: FxDownload, observations: list[dict],
                      ingestion_method: str) -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "source": "Banco Central de Chile BDE",
        "ingestion_method": ingestion_method,
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
            "Banco Central de Chile BDE", SERIES_ID, "CLP_PER_USD"):
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
    method = data.get("ingestion_method")
    api_query = ({"function", "timeseries", "firstdate", "lastdate"} == set(query)
                 and query.get("function") == ["GetSeries"]
                 and query.get("timeseries") == [SERIES_ID])
    public_query = query == {"idSerie": [SERIES_ID]}
    endpoint_valid = (
        method == "authenticated_api" and parsed_url.path == API_PATH and api_query or
        method == "public_bde_html" and parsed_url.path == PUBLIC_PATH and public_query
    )
    if ((parsed_url.scheme, parsed_url.hostname) != ("https", API_HOST) or not endpoint_valid or
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
    if not data:
        blockers.append("falta cache dólar observado BCCh")
    return {
        "source": "Banco Central de Chile BDE", "series_id": SERIES_ID,
        "key_present": key_present, "cached": bool(data),
        "public_fallback_available": True,
        "ingestion_method": (data or {}).get("ingestion_method"),
        "latest": (data or {}).get("latest"),
        "fx_ready": bool(data), "blockers": blockers,
        "credential_persisted": False,
    }


def validate_eps_unit_record(rut: str, record: dict) -> dict:
    if not re.fullmatch(r"\d{7,8}", str(rut)) or not isinstance(record, dict):
        raise ValueError("registro de unidad EPS inválido")
    if record.get("status") != "verified":
        raise ValueError(f"unidad EPS de {rut} no verificada")
    if record.get("metric") != "basic_eps" or not re.fullmatch(
            r"\d{6}", str(record.get("period") or "")):
        raise ValueError(f"período o métrica EPS de {rut} inválido")
    if record.get("unit") not in {"CLP_PER_SHARE", "USD_PER_SHARE"}:
        raise ValueError(f"unidad EPS de {rut} no soportada")
    if record.get("verification_method") not in {
            "audited_annual_report_note", "issuer_disclosure"}:
        raise ValueError(f"método de unidad EPS de {rut} insuficiente")
    if not str(record.get("source_reference") or "").startswith("https://"):
        raise ValueError(f"fuente de unidad EPS de {rut} inválida")
    if not re.fullmatch(r"[0-9a-f]{64}", str(record.get("source_sha256") or "")):
        raise ValueError(f"hash de unidad EPS de {rut} inválido")
    if not isinstance(record.get("source_page"), int) or record["source_page"] < 1:
        raise ValueError(f"página de unidad EPS de {rut} inválida")
    try:
        verified = date.fromisoformat(str(record.get("verified_as_of")))
        cmf_value = Decimal(str(record.get("cmf_value")))
        reported_value = Decimal(str(record.get("reported_value")))
        multiplier = Decimal(str(record.get("cmf_value_multiplier")))
    except (ValueError, InvalidOperation) as exc:
        raise ValueError(f"evidencia numérica EPS de {rut} inválida") from exc
    if (verified > date.today() or not all(value.is_finite() for value in (
            cmf_value, reported_value, multiplier)) or reported_value <= 0 or multiplier <= 0):
        raise ValueError(f"evidencia numérica EPS de {rut} fuera de contrato")
    tolerance = max(Decimal("0.00000001"), abs(reported_value) * Decimal("0.00002"))
    if abs(cmf_value * multiplier - reported_value) > tolerance:
        raise ValueError(f"escala EPS de {rut} no reconcilia CMF con documento")
    return record


def validate_eps_unit_dataset(data: dict) -> dict:
    if not isinstance(data, dict) or data.get("schema_version") != EPS_UNIT_SCHEMA_VERSION:
        raise ValueError("schema de unidades EPS no soportado")
    entries = data.get("entries")
    if not isinstance(entries, dict):
        raise ValueError("unidades EPS sin entries")
    for rut, record in entries.items():
        validate_eps_unit_record(str(rut), record)
    return data


def read_eps_unit_dataset(path: str) -> dict | None:
    try:
        with open(path, encoding="utf-8") as handle:
            return validate_eps_unit_dataset(json.load(handle))
    except (FileNotFoundError, OSError, ValueError, AttributeError):
        return None


def eps_unit_availability(*paths: str) -> dict:
    data = next((item for path in paths if (item := read_eps_unit_dataset(path))), None)
    entries = (data or {}).get("entries", {})
    return {
        "schema_version": (data or {}).get("schema_version"),
        "ready": False,
        "mechanism_ready": bool(entries),
        "coverage_scope": "verified_entries_only_not_universe_complete",
        "universe_complete": False,
        "verified_entries": len(entries),
        "verified_ruts": sorted(entries),
        "scale_verified_ruts": sorted(
            rut for rut, item in entries.items() if item.get("cmf_value_multiplier") is not None),
        "blockers": (["cobertura de unidad/escala EPS incompleta para el universo"]
                     if entries else ["falta evidencia auditada de unidad y escala EPS"]),
    }
