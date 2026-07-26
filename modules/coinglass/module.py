"""Read-only CoinGlass research dashboard and authenticated ingest."""
from __future__ import annotations

import hmac
import json
import os
import threading
import time
from datetime import datetime, timedelta, timezone

from core.module_base import NexusModule
from core.paths import persist_dir
from modules.coinglass.shadow import replay_shadow
from modules.coinglass.visual import (
    VisualSnapshotError,
    build_visual_indicator,
    normalize_visual_snapshot,
)

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
STATE_PATH = os.path.join(persist_dir(ROOT), "coinglass_dashboard.json")
VISUAL_STATE_PATH = os.path.join(persist_dir(ROOT), "coinglass_visual.json")
VISUAL_HISTORY_PATH = os.path.join(persist_dir(ROOT), "coinglass_visual_history.json")
VISUAL_BOOK_HISTORY_PATH = os.path.join(
    persist_dir(ROOT),
    "coinglass_visual_book_history.json",
)
MAX_BODY = 8_000_000
def _recent_by_time(rows: list, *, hours: int, cap: int) -> list:
    """Últimas `hours` horas reales según `captured_at`, con tope de seguridad.

    Recortar por conteo asume que el colector nunca falla; recortar por tiempo
    deja los huecos visibles, que es lo que hay que ver.
    """
    if not isinstance(rows, list) or not rows:
        return []
    corte = datetime.now(timezone.utc) - timedelta(hours=hours)
    frescas = []
    for row in rows:
        stamp = row.get("captured_at") if isinstance(row, dict) else None
        if not isinstance(stamp, str):
            continue
        try:
            when = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
        except ValueError:
            continue
        if when.tzinfo is None:
            continue
        if when >= corte:
            frescas.append(row)
    return frescas[-cap:]


MAX_VISUAL_BOOK_HISTORY = 2_016
PUBLIC_VISUAL_BOOK_HISTORY = 288

# 2.016 capturas cada 5 min son EXACTAMENTE 7 días: todo lo anterior se perdía para
# siempre. Y como nada cruza los niveles de CoinGlass con los setups del Diario, el
# estudio del imán con niveles REALES —el único que quedó pendiente y que no es
# backtesteable— no tenía con qué hacerse nunca. Cada día de espera destruía un día
# de datos irrecuperable.
#
# Se archiva append-only lo que se cae de la ventana. El archivo caliente sigue
# chico (lo que sirve la UI no cambia); el histórico queda en disco para poder unir
# offline por `captured_at` sin que ningún módulo de trading importe CoinGlass —la
# separación research↔ejecución se mantiene intacta—.
VISUAL_BOOK_ARCHIVE_PATH = os.path.join(
    persist_dir(ROOT),
    "coinglass_visual_book_archive.jsonl",
)
# ~1 KB por captura y 288 capturas al día son ~0,3 MB/día, ~110 MB/año. El tope es
# holgado, y al llegar DEJA de escribir en vez de rotar en silencio: perder datos
# calladamente es justo el problema que este archivo viene a resolver.
MAX_ARCHIVE_BYTES = 512_000_000


def _archivar_descartadas(path: str, filas: list) -> dict:
    """Agrega al archivo histórico lo que se cae de la ventana rodante.

    Devuelve un resumen para poder ver desde el estado si esto está funcionando: un
    archivo que falla en silencio es peor que no tenerlo, porque da la sensación de
    estar guardando.
    """
    resumen = {"escritas": 0, "error": None, "lleno": False}
    if not filas:
        return resumen
    try:
        if os.path.exists(path) and os.path.getsize(path) >= MAX_ARCHIVE_BYTES:
            resumen["lleno"] = True
            return resumen
        with open(path, "a", encoding="utf-8") as fh:
            for fila in filas:
                fh.write(json.dumps(fila, separators=(",", ":")) + "\n")
        resumen["escritas"] = len(filas)
    except OSError as exc:
        # No romper la ingesta por esto: el colector ya perdió un ciclo una vez por
        # fallar cerrado en un guard mío. Se reporta y se sigue.
        resumen["error"] = str(exc)
    return resumen


def _estado_del_archivo(path: str) -> dict:
    """Salud del archivo con `stat` solamente.

    Contar líneas obligaría a leer el archivo entero en CADA carga de la página, y
    este archivo está diseñado para crecer a cientos de MB. `bytes` + `ultima_escritura`
    alcanzan para ver que sigue creciendo, que es lo único que hay que vigilar.
    """
    try:
        st = os.stat(path)
    except FileNotFoundError:
        return {"existe": False, "bytes": 0}
    except OSError as exc:
        return {"existe": None, "error": str(exc)}
    return {
        "existe": True,
        "bytes": st.st_size,
        "ultima_escritura": datetime.fromtimestamp(
            st.st_mtime, timezone.utc).isoformat(),
        "lleno": st.st_size >= MAX_ARCHIVE_BYTES,
    }


class CoinGlassModule(NexusModule):
    slug = "coinglass"
    title = "CoinGlass"
    description = "Microestructura BTC: liquidaciones, order book y presión experimental."
    icon = "CG"

    def __init__(self, context):
        super().__init__(context)
        self._lock = threading.Lock()
        # Capturas botadas por el techo duro cuando el archivo historico no acepta.
        # Vive en memoria: se reinicia con el proceso y eso esta bien, porque lo que
        # importa es que un operador VEA que se esta perdiendo ahora, no llevar la
        # contabilidad historica de las perdidas.
        self._perdidas_por_archivo = 0

    def api(self, subpath, query, user=None):
        if subpath != "state":
            return None
        data = self._read()
        if not data:
            data = {
                "mode": "research",
                "execution_enabled": False,
                "waiting": True,
            }
        else:
            data["age_seconds"] = round(time.time() - os.path.getmtime(STATE_PATH), 0)
        visual = self._read_path(VISUAL_STATE_PATH)
        if visual:
            data["visual_snapshot"] = visual
            book_history = self._read_path(VISUAL_BOOK_HISTORY_PATH) or []
            if isinstance(book_history, list):
                # Recorte por TIEMPO, no por conteo: "las últimas 288 entradas"
                # equivale a 24 h solo si el timer nunca falló. Con el colector
                # caído medio día, esas 288 abarcaban 2-3 días y el gráfico las
                # dibujaba contiguas, borrando los huecos.
                data["visual_orderbook_history"] = _recent_by_time(
                    book_history, hours=24, cap=PUBLIC_VISUAL_BOOK_HISTORY)
            # Observable a propósito: si el archivo dejara de crecer habría que
            # enterarse, no descubrirlo dentro de unos meses al ir a usarlo.
            archivo = _estado_del_archivo(VISUAL_BOOK_ARCHIVE_PATH)
            # Se publica junto a la salud del archivo: si hay perdidas, el numero
            # tiene que estar donde ya se mira la frescura, no en un log que nadie lee.
            archivo["capturas_perdidas"] = self._perdidas_por_archivo
            data["visual_book_archive"] = archivo
            try:
                indicator = build_visual_indicator(visual)
                data["visual_indicator"] = indicator
                history = self._read_path(VISUAL_HISTORY_PATH) or []
                data["visual_shadow"] = replay_shadow(history)
            except VisualSnapshotError as exc:
                data["visual_error"] = str(exc)
        return self._json(200, data)

    def api_post(self, subpath, body, headers, user=None):
        if subpath not in {"ingest", "visual-ingest"}:
            return None
        token = os.environ.get("NEXUS_INGEST_TOKEN", "").strip()
        if not token:
            return self._json(503, {"error": "ingesta no configurada"})
        if not hmac.compare_digest(headers.get("x-nexus-token", ""), token):
            return self._json(401, {"error": "token invalido"})
        if not isinstance(body, dict) or body.get("research_only") is not True:
            return self._json(400, {"error": "snapshot CoinGlass invalido"})
        if body.get("execution_enabled") is not False or body.get("mode") != "research":
            if subpath == "ingest":
                return self._json(400, {"error": "solo se aceptan datos research sin ejecucion"})
        raw = json.dumps(body, ensure_ascii=False).encode()
        if len(raw) > MAX_BODY:
            return self._json(413, {"error": "snapshot demasiado grande"})
        with self._lock:
            if subpath == "visual-ingest":
                try:
                    clean = normalize_visual_snapshot(body)
                except VisualSnapshotError as exc:
                    return self._json(400, {"error": str(exc)})
                self._write_path(VISUAL_STATE_PATH, clean)
                indicator = build_visual_indicator(clean)
                history = self._read_path(VISUAL_HISTORY_PATH) or []
                if not isinstance(history, list):
                    history = []
                if not history or history[-1].get("captured_at") != clean["captured_at"]:
                    history.append({
                        "research_only": True,
                        "captured_at": clean["captured_at"],
                        "indicator": indicator,
                    })
                    self._write_path(VISUAL_HISTORY_PATH, history[-10_000:])
                book_history = self._read_path(VISUAL_BOOK_HISTORY_PATH) or []
                if not isinstance(book_history, list):
                    book_history = []
                if (
                    not book_history
                    or book_history[-1].get("captured_at") != clean["captured_at"]
                ):
                    rows = clean["whale_orders"]["rows"]
                    book_history.append({
                        "research_only": True,
                        "captured_at": clean["captured_at"],
                        "price": clean["price"],
                        "bids": [
                            [row["price"], row["amount_usd"]]
                            for row in rows
                            if row["side"] == "bid"
                        ],
                        "asks": [
                            [row["price"], row["amount_usd"]]
                            for row in rows
                            if row["side"] == "ask"
                        ],
                    })
                    # Solo se recorta lo que el archivo CONFIRMÓ haber guardado.
                    #
                    # Antes se archivaba, se botaba el valor de retorno y se recortaba
                    # igual. `_archivar_descartadas` devuelve `{escritas, error,
                    # lleno}` precisamente para que esto no pasara, y yo lo ignoré:
                    # con el archivo lleno o un error de disco, la captura vieja no se
                    # guardaba Y además desaparecía de la ventana caliente. Perdida
                    # para siempre, en silencio, que es exactamente lo que este
                    # archivo venía a evitar (auditoría 2026-07-26).
                    #
                    # Si el archivo falla, la ventana caliente CRECE en vez de perder.
                    # Eso no puede ser infinito, así que hay un techo duro: pasado el
                    # doble, se bota lo más viejo y se cuenta. Perder contando es malo;
                    # perder sin contar es indefendible.
                    if len(book_history) > MAX_VISUAL_BOOK_HISTORY:
                        sobrantes = book_history[:-MAX_VISUAL_BOOK_HISTORY]
                        arch = _archivar_descartadas(VISUAL_BOOK_ARCHIVE_PATH, sobrantes)
                        if arch["escritas"] == len(sobrantes):
                            book_history = book_history[-MAX_VISUAL_BOOK_HISTORY:]
                        else:
                            self.context.log(
                                "coinglass: el archivo historico no acepto "
                                f"{len(sobrantes)} capturas "
                                f"({arch['error'] or 'lleno'}); NO se recortan")
                            if len(book_history) > 2 * MAX_VISUAL_BOOK_HISTORY:
                                perdidas = len(book_history) - 2 * MAX_VISUAL_BOOK_HISTORY
                                book_history = book_history[-2 * MAX_VISUAL_BOOK_HISTORY:]
                                self._perdidas_por_archivo += perdidas
                                self.context.log(
                                    f"coinglass: TECHO DURO, {perdidas} capturas "
                                    f"perdidas (total {self._perdidas_por_archivo})")
                    self._write_path(VISUAL_BOOK_HISTORY_PATH, book_history)
            else:
                self._write(body)
        return self._json(200, {"ok": True})

    @staticmethod
    def _read():
        return CoinGlassModule._read_path(STATE_PATH)

    @staticmethod
    def _read_path(path):
        try:
            with open(path, encoding="utf-8") as fh:
                return json.load(fh)
        except (FileNotFoundError, json.JSONDecodeError):
            return None

    @staticmethod
    def _write(data):
        CoinGlassModule._write_path(STATE_PATH, data)

    @staticmethod
    def _write_path(path, data):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        temp = path + ".tmp"
        with open(temp, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False)
        os.chmod(temp, 0o600)
        os.replace(temp, path)

    @staticmethod
    def _json(status, data):
        return status, "application/json; charset=utf-8", json.dumps(data).encode()

    def health(self):
        data = self._read()
        return {
            "slug": self.slug,
            "status": "ok",
            "mode": "research",
            "has_data": bool(data),
            "has_visual_data": bool(self._read_path(VISUAL_STATE_PATH)),
            "execution": False,
        }


def get_module(context):
    return CoinGlassModule(context)
