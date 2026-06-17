"""Capa de persistencia Postgres (Fase multi-usuario).

Backend elegido por ENTORNO: si hay DATABASE_URL → Postgres (Railway/web); si no
→ los módulos siguen con sus stores JSON (VPS/motor, o local sin DB). Por eso el
engine se crea de forma PEREZOSA: importar este módulo nunca abre una conexión, así
el motor del VPS (sin DATABASE_URL) lo importa sin efectos.

SQLAlchemy 2.0 SYNC + psycopg3 — los handlers de los módulos son síncronos.

Esquema Fase 1 (mínimo, multi-tenant): el payload ingerido se guarda tal cual (JSONB)
por usuario y tipo; aún no se normalizan trades/posiciones (cambio mínimo, features
idénticas). Se normaliza más adelante si hay razón.
"""
from __future__ import annotations

import os
from contextlib import contextmanager
from datetime import datetime
from typing import Optional

from sqlalchemy import (BigInteger, ForeignKey, String, UniqueConstraint,
                        create_engine, func)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import (DeclarativeBase, Mapped, mapped_column, sessionmaker)


def database_url() -> Optional[str]:
    """DATABASE_URL normalizada para SQLAlchemy + psycopg3, o None si no hay DB.
    Railway entrega postgres:// o postgresql://; psycopg3 requiere +psycopg."""
    url = os.environ.get("DATABASE_URL", "").strip()
    if not url:
        return None
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    if url.startswith("postgresql://") and "+psycopg" not in url:
        url = "postgresql+psycopg://" + url[len("postgresql://"):]
    return url


def database_enabled() -> bool:
    return database_url() is not None


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(320), unique=True)
    name: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    # Auth (Fase funcional): rol, identidad de Google y rastro de acceso.
    role: Mapped[str] = mapped_column(String(16), server_default="beta")  # "admin" | "beta"
    google_sub: Mapped[Optional[str]] = mapped_column(String(64), unique=True, nullable=True)
    picture: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    last_login: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class Invitation(Base):
    """Beta cerrada: solo emails con invitación (o el admin) pueden entrar."""
    __tablename__ = "invitations"
    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(320), unique=True)
    invited_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    used_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)


class IngestedData(Base):
    """Último payload ingerido del motor (colector), por usuario y tipo."""
    __tablename__ = "ingested_data"
    __table_args__ = (UniqueConstraint("user_id", "kind", name="uq_ingest_user_kind"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(32))   # "journal" | "setups"
    payload: Mapped[dict] = mapped_column(JSONB)
    received_at_ms: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), onupdate=func.now())


class PushSubscription(Base):
    __tablename__ = "push_subscriptions"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True)
    endpoint: Mapped[str] = mapped_column(String, unique=True)
    subscription: Mapped[dict] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


_engine = None
_Session = None


def _ensure():
    global _engine, _Session
    if _Session is None:
        url = database_url()
        if not url:
            raise RuntimeError("DATABASE_URL no configurada")
        _engine = create_engine(url, pool_pre_ping=True, future=True)
        _Session = sessionmaker(bind=_engine, expire_on_commit=False)
    return _Session


@contextmanager
def session():
    """Sesión transaccional: commit al salir, rollback si hay excepción."""
    Session = _ensure()
    s = Session()
    try:
        yield s
        s.commit()
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()


def get_engine():
    _ensure()
    return _engine
