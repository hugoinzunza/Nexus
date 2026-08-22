"""Adaptador read-only para Estados de Resultados de CMF Bancos.

La API usa una credencial dedicada y un esquema contable distinto al TXT IFRS
de sociedades. Este módulo mantiene ambas fuentes separadas y nunca persiste la
API key en URLs de procedencia ni mensajes de error.
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
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation


API_HOST = "api.cmfchile.cl"
API_ROOT = "/api-sbifv3/recursos_api"
RESULTS_PATH = API_ROOT + "/resultados"
MAX_DOWNLOAD_BYTES = 20_000_000
SCHEMA_VERSION = "acciones-chile-banks-0.1.0"
API_KEY_ENV = "CMF_BANKS_API_KEY"

# Código SBIF/CMF confirmado en el catálogo oficial de instituciones.
LISTED_BANKS = {
    "CHILE": {"institution_code": "001", "name": "BANCO DE CHILE"},
    "BCI": {"institution_code": "016", "name": "BANCO DE CREDITO E INVERSIONES"},
    "BSANTANDER": {"institution_code": "037", "name": "BANCO SANTANDER CHILE"},
    "ITAUCL": {"institution_code": "039", "name": "BANCO ITAU CHILE"},
}

# Única métrica habilitada hasta validar el catálogo contable vigente completo.
VERIFIED_METRICS = {
    "interest_income": {
        "account_code": "4100000",
        "description": "INGRESOS POR INTERESES Y REAJUSTES",
    },
}


@dataclass(frozen=True)
class BankResultRow:
    account_code: str
    account_description: str
    institution_code: str
    institution_name: str
    year: int
    month: int
    total: Decimal


@dataclass(frozen=True)
class BankDownload:
    year: int
    institution_code: str
    payload: bytes
    effective_url_redacted: str
    retrieved_at: str
    http_status: int
    content_length: int | None
    bytes_received: int


def availability(path: str | None = None) -> dict:
    cached = False
    observations = 0
    periods: list[str] = []
    if path:
        data = read_bank_dataset(path)
        cached = bool(data)
        observations = len((data or {}).get("observations", []))
        periods = (data or {}).get("periods", [])
    key_present = bool(os.environ.get(API_KEY_ENV))
    blockers = []
    if not key_present:
        blockers.append(f"falta {API_KEY_ENV}")
    if not cached:
        blockers.append("falta cache local CMF Bancos")
    blockers.append("catálogo completo de métricas bancarias y join causal pendientes")
    return {
        "source": "CMF Bancos API v3",
        "configured_tickers": sorted(LISTED_BANKS),
        "key_present": key_present,
        "cached": cached,
        "observations": observations,
        "periods": periods,
        "feature_ready": False,
        "metric_schema_status": "partial_verified" if observations else "unverified_no_data",
        "verified_metrics": sorted(VERIFIED_METRICS) if observations else [],
        "configured_metric_candidates": sorted(VERIFIED_METRICS),
        "blockers": blockers,
    }


def _validated_url(year: int, institution_code: str, api_key: str) -> tuple[str, str]:
    try:
        year = int(year)
    except (TypeError, ValueError) as exc:
        raise ValueError("año CMF Bancos inválido") from exc
    current_year = datetime.now(timezone.utc).year
    if year < 2009 or year > current_year:
        raise ValueError("año CMF Bancos fuera de rango")
    code = str(institution_code)
    if not re.fullmatch(r"\d{3}", code):
        raise ValueError("código de institución CMF inválido")
    allowed = {item["institution_code"] for item in LISTED_BANKS.values()}
    if code not in allowed:
        raise ValueError("institución CMF no allowlisted")
    if not isinstance(api_key, str) or not api_key.strip():
        raise ValueError(f"falta {API_KEY_ENV}")
    path = f"{RESULTS_PATH}/{year}/instituciones/{code}"
    query = urllib.parse.urlencode({"apikey": api_key.strip(), "formato": "json"})
    url = urllib.parse.urlunparse(("https", API_HOST, path, "", query, ""))
    redacted = urllib.parse.urlunparse(("https", API_HOST, path, "", "formato=json", ""))
    return url, redacted


def download_results(year: int, institution_code: str, api_key: str,
                     timeout: float = 30.0) -> BankDownload:
    """Descarga un año completo y falla cerrado ante redirects o exceso de tamaño."""
    url, redacted = _validated_url(year, institution_code, api_key)
    request = urllib.request.Request(url, headers={"User-Agent": "NexUX-AccionesChile/0.1"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 - allowlist
            final = urllib.parse.urlparse(response.geturl())
            expected = urllib.parse.urlparse(url)
            if (final.scheme, final.hostname, final.path) != ("https", API_HOST, expected.path):
                raise ValueError("CMF Bancos redirigió fuera del endpoint autorizado")
            declared = response.headers.get("Content-Length")
            content_length = int(declared) if declared and declared.isdigit() else None
            status = int(getattr(response, "status", 200))
            body = response.read(MAX_DOWNLOAD_BYTES + 1)
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, OSError):
        # HTTPError incluye la URL completa; suprimir causa evita filtrar apikey.
        raise ValueError("consulta CMF Bancos falló") from None
    if len(body) > MAX_DOWNLOAD_BYTES:
        raise ValueError("respuesta CMF Bancos excede el límite permitido")
    if content_length is not None and len(body) != content_length:
        raise ValueError("respuesta CMF Bancos truncada según Content-Length")
    return BankDownload(
        year=int(year), institution_code=str(institution_code), payload=body,
        effective_url_redacted=redacted,
        retrieved_at=datetime.now(timezone.utc).isoformat(), http_status=status,
        content_length=content_length, bytes_received=len(body),
    )


def _result_items(document: object) -> list[dict]:
    if not isinstance(document, dict):
        raise ValueError("JSON CMF Bancos debe ser un objeto")
    root = document.get("ReportesBancarios", document)
    if not isinstance(root, dict):
        raise ValueError("raíz ReportesBancarios inválida")
    group = root.get("CodigosEstadosDeResultado")
    if not isinstance(group, dict):
        raise ValueError("falta CodigosEstadosDeResultado")
    items = group.get("CodigoEERRIFI")
    if isinstance(items, dict):
        items = [items]
    if not isinstance(items, list) or not items:
        raise ValueError("falta lista CodigoEERRIFI")
    if not all(isinstance(item, dict) for item in items):
        raise ValueError("fila CodigoEERRIFI inválida")
    return items


def _decimal(value: object, row_number: int) -> Decimal:
    if value is None or value == "":
        raise ValueError(f"fila CMF Bancos {row_number}: MonedaTotal vacío")
    normalized = str(value).strip()
    if "," in normalized:
        normalized = normalized.replace(".", "").replace(",", ".")
    try:
        return Decimal(normalized)
    except InvalidOperation as exc:
        raise ValueError(f"fila CMF Bancos {row_number}: MonedaTotal inválido") from exc


def parse_results(payload: bytes | str) -> list[BankResultRow]:
    try:
        document = json.loads(payload.decode("utf-8-sig") if isinstance(payload, bytes) else payload)
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError) as exc:
        raise ValueError("respuesta CMF Bancos no es JSON válido") from exc
    rows = []
    for number, item in enumerate(_result_items(document), start=1):
        required = ("CodigoCuenta", "DescripcionCuenta", "CodigoInstitucion",
                    "NombreInstitucion", "Anho", "Mes", "MonedaTotal")
        if any(key not in item for key in required):
            raise ValueError(f"fila CMF Bancos {number}: esquema incompleto")
        code = str(item["CodigoCuenta"])
        institution = str(item["CodigoInstitucion"]).zfill(3)
        try:
            year, month = int(item["Anho"]), int(item["Mes"])
        except (TypeError, ValueError) as exc:
            raise ValueError(f"fila CMF Bancos {number}: período inválido") from exc
        if not re.fullmatch(r"\d{7}", code) or not re.fullmatch(r"\d{3}", institution):
            raise ValueError(f"fila CMF Bancos {number}: código inválido")
        if year < 2009 or month not in range(1, 13):
            raise ValueError(f"fila CMF Bancos {number}: período fuera de rango")
        rows.append(BankResultRow(
            account_code=code, account_description=str(item["DescripcionCuenta"]).strip(),
            institution_code=institution,
            institution_name=str(item["NombreInstitucion"]).strip(), year=year, month=month,
            total=_decimal(item["MonedaTotal"], number),
        ))
    return rows


def build_bank_dataset(downloads: list[BankDownload]) -> dict:
    observations = []
    sources = []
    allowed_codes = {item["institution_code"]: ticker for ticker, item in LISTED_BANKS.items()}
    for download in downloads:
        if download.institution_code not in allowed_codes:
            raise ValueError("institución descargada no allowlisted")
        rows = parse_results(download.payload)
        if any(row.institution_code != download.institution_code or row.year != download.year
               for row in rows):
            raise ValueError("respuesta CMF Bancos no coincide con institución/año solicitado")
        ticker = allowed_codes[download.institution_code]
        metric = VERIFIED_METRICS["interest_income"]
        verified_rows = [row for row in rows if row.account_code == metric["account_code"]]
        if not verified_rows:
            raise ValueError("CMF Bancos no entregó la cuenta verificada 4100000")
        if any(" ".join(row.account_description.upper().split()) != metric["description"]
               for row in verified_rows):
            raise ValueError("descripción de cuenta 4100000 cambió")
        by_period = {}
        for row in verified_rows:
            key = (row.year, row.month)
            if key in by_period:
                raise ValueError("cuenta CMF Bancos duplicada para institución/período")
            by_period[key] = row
        for (year, month), row in sorted(by_period.items()):
            if month not in {3, 6, 9, 12}:
                continue
            observations.append({
                "ticker": ticker, "institution_code": row.institution_code,
                "institution_name": row.institution_name, "period": f"{year}{month:02d}",
                "months_covered": month,
                "analysis": {"interest_income": format(row.total, "f")},
                "available_at": None,
                "feature_use": "forbidden_until_telegram_join",
            })
        sources.append({
            "year": download.year, "institution_code": download.institution_code,
            "url": download.effective_url_redacted, "retrieved_at": download.retrieved_at,
            "http_status": download.http_status, "content_length": download.content_length,
            "bytes_received": download.bytes_received,
            "sha256": hashlib.sha256(download.payload).hexdigest(), "rows": len(rows),
        })
    observations.sort(key=lambda item: (item["period"], item["ticker"]), reverse=True)
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "feature_use": "forbidden_until_availability_join",
        "metric_schema_status": "partial_verified",
        "verified_metrics": VERIFIED_METRICS,
        "periods": sorted({item["period"] for item in observations}, reverse=True),
        "observations": observations,
        "sources": sources,
    }


def read_bank_dataset(path: str) -> dict | None:
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
        return data if data.get("schema_version") == SCHEMA_VERSION else None
    except (FileNotFoundError, OSError, ValueError, AttributeError):
        return None


def write_bank_dataset(path: str, data: dict) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    temp = path + ".tmp"
    with open(temp, "w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, separators=(",", ":"))
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temp, path)
