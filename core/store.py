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
