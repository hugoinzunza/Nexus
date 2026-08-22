"""Cliente read-only para los TXT IFRS publicados por la CMF.

La CMF publica un archivo delimitado por punto y coma. Cada fila contiene:
periodo, RUT, sociedad, alcance, moneda, cuenta, valor, taxonomía y estado.
Este adaptador solo acepta el host y path oficiales definidos abajo.
"""
from __future__ import annotations

import io
import re
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Iterable


CMF_HOST = "www.cmfchile.cl"
CMF_PATH = "/institucional/estadisticas/ver_archivo.php"
CMF_LIST_PATH = "/institucional/estadisticas/estadisticas_ifrs.php"
DEFAULT_URL = f"https://{CMF_HOST}{CMF_PATH}"
LIST_URL = f"https://{CMF_HOST}{CMF_LIST_PATH}"
MAX_DOWNLOAD_BYTES = 30_000_000
PERIOD_LINK = re.compile(r"ver_archivo\.php\?inicio=(\d{6})&(?:amp;)?termino=(\d{6})")


@dataclass(frozen=True)
class CMFRow:
    period: str
    rut: str
    company: str
    scope: str
    currency: str
    account: str
    value: Decimal
    taxonomy: str
    statement: str


@dataclass(frozen=True)
class CMFDownload:
    period: str
    payload: bytes
    effective_url: str
    retrieved_at: str
    http_status: int
    content_length: int | None
    bytes_received: int


def _validated_url(base_url: str, period: str) -> str:
    if len(period) != 6 or not period.isdigit():
        raise ValueError("period debe tener formato YYYYMM")
    parsed = urllib.parse.urlparse(base_url)
    if (parsed.scheme != "https" or parsed.hostname != CMF_HOST or parsed.path != CMF_PATH
            or parsed.query or parsed.fragment):
        raise ValueError("la fuente CMF no está allowlisted")
    return base_url + "?" + urllib.parse.urlencode({"inicio": period, "termino": period})


def download_period(period: str, base_url: str = DEFAULT_URL, timeout: float = 30.0) -> bytes:
    """Descarga un período oficial. Falla cerrado ante redirecciones inesperadas."""
    return download_period_details(period, base_url, timeout).payload


def download_period_details(period: str, base_url: str = DEFAULT_URL,
                            timeout: float = 30.0) -> CMFDownload:
    url = _validated_url(base_url, period)
    request = urllib.request.Request(url, headers={"User-Agent": "NexUX-AccionesChile/0.1"})
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 - URL allowlisted
        final = urllib.parse.urlparse(response.geturl())
        if final.scheme != "https" or final.hostname != CMF_HOST or final.path != CMF_PATH:
            raise ValueError("la CMF redirigió fuera del endpoint autorizado")
        declared = response.headers.get("Content-Length")
        content_length = int(declared) if declared and declared.isdigit() else None
        status = int(getattr(response, "status", 200))
        body = response.read(MAX_DOWNLOAD_BYTES + 1)
    if len(body) > MAX_DOWNLOAD_BYTES:
        raise ValueError("archivo CMF excede el límite permitido")
    if content_length is not None and len(body) != content_length:
        raise ValueError("descarga CMF truncada según Content-Length")
    return CMFDownload(
        period=period, payload=body, effective_url=url,
        retrieved_at=datetime.now(timezone.utc).isoformat(), http_status=status,
        content_length=content_length, bytes_received=len(body),
    )


def available_periods(timeout: float = 20.0) -> list[str]:
    """Lista períodos individuales publicados por la CMF, más reciente primero."""
    request = urllib.request.Request(LIST_URL, headers={"User-Agent": "NexUX-AccionesChile/0.1"})
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 - URL constante
        final = urllib.parse.urlparse(response.geturl())
        if final.scheme != "https" or final.hostname != CMF_HOST or final.path != CMF_LIST_PATH:
            raise ValueError("la CMF redirigió fuera del listado autorizado")
        body = response.read(3_000_001)
    if len(body) > 3_000_000:
        raise ValueError("listado CMF excede el límite")
    found = [start for start, end in PERIOD_LINK.findall(body.decode("utf-8", errors="replace"))
             if start == end]
    return sorted(set(found), reverse=True)


def parse_rows(payload: bytes | str) -> list[CMFRow]:
    text = payload.decode("utf-8-sig") if isinstance(payload, bytes) else payload
    rows: list[CMFRow] = []
    for number, raw in enumerate(io.StringIO(text), start=1):
        raw = raw.rstrip("\r\n")
        if not raw:
            continue
        fields = raw.split(";")
        if len(fields) != 9:
            raise ValueError(f"fila CMF {number}: se esperaban 9 columnas")
        try:
            value = Decimal(fields[6].strip())
        except InvalidOperation as exc:
            raise ValueError(f"fila CMF {number}: valor inválido") from exc
        rows.append(CMFRow(
            period=fields[0].strip(), rut=fields[1].strip(), company=fields[2].strip(),
            scope=fields[3].strip(), currency=fields[4].strip(), account=fields[5].strip(),
            value=value, taxonomy=fields[7].strip(), statement=fields[8].strip(),
        ))
    return rows


def rows_for_rut(rows: Iterable[CMFRow], rut: str) -> list[CMFRow]:
    wanted = "".join(ch for ch in str(rut) if ch.isdigit())[:8]
    return [row for row in rows if row.rut == wanted]
