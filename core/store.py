"""Almacenamiento CONMUTABLE: Postgres si hay DATABASE_URL, si no archivos JSON.

Centraliza la elección de backend para que los módulos (journal, push) no sepan de
la DB. Fase 1 single-tenant: todo cuelga del usuario por defecto (Hugo). Cuando
lleguen las cuentas (auth), `user_id` dejará de ser fijo.

Esto preserva el comportamiento actual cuando NO hay DB (VPS/motor, local): mismos
archivos en persist_dir, escritura atómica. Con DB, los mismos datos viven en
ingested_data / push_subscriptions por usuario.
"""
from __future__ import annotations

import json
import os
import threading
from typing import List, Optional

from core import db
from core.paths import persist_dir

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = persist_dir(ROOT)
_LOCK = threading.Lock()

# Usuario por defecto (single-tenant Fase 1).
DEFAULT_EMAIL = "hugoinzunza@gmail.com"
DEFAULT_NAME = "Hugo"
_default_uid: Optional[int] = None


def default_user_id() -> int:
    """Id del usuario por defecto; lo crea si no existe (idempotente)."""
    global _default_uid
    if _default_uid is not None:
        return _default_uid
    from sqlalchemy import select
    with db.session() as s:
        u = s.scalar(select(db.User).where(db.User.email == DEFAULT_EMAIL))
        if u is None:
            u = db.User(email=DEFAULT_EMAIL, name=DEFAULT_NAME)
            s.add(u)
            s.flush()
        _default_uid = u.id
    return _default_uid


def _json_atomic_write(path: str, obj, indent=None) -> None:
    os.makedirs(DATA_DIR, exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, ensure_ascii=False, indent=indent)
    os.replace(tmp, path)


def _json_read(path: str):
    if not os.path.isfile(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:  # noqa: BLE001
        return None


# --- Ingesta del colector (kind: "journal" | "setups") -------------------
def _ingest_path(kind: str) -> str:
    name = "journal_ingest.json" if kind == "journal" else "setups_ingest.json"
    return os.path.join(DATA_DIR, name)


def read_ingest(kind: str, user_id: Optional[int] = None) -> Optional[dict]:
    """Lee la ingesta de un usuario. `user_id=None` → usuario por defecto (Hugo),
    para preservar el modo single-tenant local/inerte. En modo DB (Railway) cada
    usuario ve solo lo suyo. En modo JSON (sin DB) hay un solo archivo (un usuario)."""
    if db.database_enabled():
        from sqlalchemy import select
        uid = user_id if user_id is not None else default_user_id()
        with db.session() as s:
            row = s.scalar(select(db.IngestedData).where(
                db.IngestedData.user_id == uid,
                db.IngestedData.kind == kind))
            return dict(row.payload) if row else None
    return _json_read(_ingest_path(kind))


def write_ingest(kind: str, payload: dict, user_id: Optional[int] = None) -> None:
    """Escribe la ingesta de un usuario. `user_id=None` → usuario por defecto (Hugo)."""
    if db.database_enabled():
        from sqlalchemy import select
        uid = user_id if user_id is not None else default_user_id()
        with db.session() as s:
            row = s.scalar(select(db.IngestedData).where(
                db.IngestedData.user_id == uid, db.IngestedData.kind == kind))
            if row is None:
                s.add(db.IngestedData(user_id=uid, kind=kind, payload=payload,
                                      received_at_ms=payload.get("_received_at_ms")))
            else:
                row.payload = payload
                row.received_at_ms = payload.get("_received_at_ms")
        return
    with _LOCK:
        _json_atomic_write(_ingest_path(kind), payload)


# --- Suscripciones push --------------------------------------------------
def _subs_path() -> str:
    return os.path.join(DATA_DIR, "push_subs.json")


def load_push_subs(user_id: Optional[int] = None) -> List[dict]:
    if db.database_enabled():
        from sqlalchemy import select
        uid = user_id if user_id is not None else default_user_id()
        with db.session() as s:
            rows = s.scalars(select(db.PushSubscription).where(
                db.PushSubscription.user_id == uid)).all()
            return [r.subscription for r in rows]
    return _json_read(_subs_path()) or []


def save_push_subs(subs: List[dict], user_id: Optional[int] = None) -> None:
    if db.database_enabled():
        from sqlalchemy import delete
        uid = user_id if user_id is not None else default_user_id()
        with db.session() as s:
            s.execute(delete(db.PushSubscription).where(
                db.PushSubscription.user_id == uid))
            for sub in subs:
                ep = (sub or {}).get("endpoint")
                if not ep:
                    continue
                s.add(db.PushSubscription(user_id=uid, endpoint=ep, subscription=sub))
        return
    with _LOCK:
        _json_atomic_write(_subs_path(), subs, indent=2)


# --- Conexiones a exchange (bóveda, Fase B) ------------------------------
# Solo en modo DB (Railway). En modo local/sin-DB no aplica: el motor usa su
# propia key del entorno (single-tenant), no la bóveda multi-usuario.
def save_exchange_connection(user_id: int, sealed: dict, exchange: str = "binance") -> None:
    """Guarda (o reemplaza) el sobre cifrado de un usuario. Queda en 'pending':
    el colector del VPS la verificará (read-only) y la pasará a 'active'/'rejected'."""
    if not db.database_enabled():
        raise RuntimeError("la bóveda requiere base de datos (DATABASE_URL)")
    from sqlalchemy import select
    from datetime import datetime
    with db.session() as s:
        row = s.scalar(select(db.ExchangeConnection).where(
            db.ExchangeConnection.user_id == user_id,
            db.ExchangeConnection.exchange == exchange))
        if row is None:
            s.add(db.ExchangeConnection(user_id=user_id, exchange=exchange,
                                        sealed=sealed, status="pending"))
        else:
            row.sealed = sealed
            row.status = "pending"
            row.status_detail = None
            row.last_verified_at = None
            row.updated_at = datetime.utcnow()


def exchange_status(user_id: int, exchange: str = "binance") -> dict:
    """Estado de la conexión para el frontend. NUNCA devuelve el sobre ni la llave."""
    if not db.database_enabled():
        return {"connected": False, "status": "unsupported", "detail": None}
    from sqlalchemy import select
    with db.session() as s:
        row = s.scalar(select(db.ExchangeConnection).where(
            db.ExchangeConnection.user_id == user_id,
            db.ExchangeConnection.exchange == exchange))
        if row is None:
            return {"connected": False, "status": "none", "detail": None}
        return {"connected": row.status == "active", "status": row.status,
                "detail": row.status_detail, "exchange": row.exchange,
                "updated_at_ms": int(row.updated_at.timestamp() * 1000) if row.updated_at else None}


def delete_exchange_connection(user_id: int, exchange: str = "binance") -> bool:
    if not db.database_enabled():
        return False
    from sqlalchemy import delete
    with db.session() as s:
        res = s.execute(delete(db.ExchangeConnection).where(
            db.ExchangeConnection.user_id == user_id,
            db.ExchangeConnection.exchange == exchange))
        return (res.rowcount or 0) > 0


def list_connections_for_collector() -> List[dict]:
    """Para el colector del VPS: conexiones a verificar/colectar (incluye el sobre).
    Devuelve pending (a verificar) y active (a colectar)."""
    if not db.database_enabled():
        return []
    from sqlalchemy import select
    with db.session() as s:
        rows = s.scalars(select(db.ExchangeConnection).where(
            db.ExchangeConnection.status.in_(("pending", "active", "error")))).all()
        return [{"id": r.id, "user_id": r.user_id, "exchange": r.exchange,
                 "sealed": dict(r.sealed), "status": r.status} for r in rows]


def set_exchange_status(user_id: int, status: str, detail: Optional[str] = None,
                        exchange: str = "binance") -> None:
    """El colector marca el resultado de la verificación/colección."""
    if not db.database_enabled():
        return
    from sqlalchemy import select
    from datetime import datetime
    with db.session() as s:
        row = s.scalar(select(db.ExchangeConnection).where(
            db.ExchangeConnection.user_id == user_id,
            db.ExchangeConnection.exchange == exchange))
        if row is None:
            return
        row.status = status
        row.status_detail = detail
        row.last_verified_at = datetime.utcnow()
        row.updated_at = datetime.utcnow()
