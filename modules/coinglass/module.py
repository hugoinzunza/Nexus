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


class CoinGlassModule(NexusModule):
    slug = "coinglass"
    title = "CoinGlass"
    description = "Microestructura BTC: liquidaciones, order book y presión experimental."
    icon = "CG"

    def __init__(self, context):
        super().__init__(context)
        self._lock = threading.Lock()

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
                    self._write_path(
                        VISUAL_BOOK_HISTORY_PATH,
                        book_history[-MAX_VISUAL_BOOK_HISTORY:],
                    )
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
