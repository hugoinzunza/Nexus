"""Entorno de Alembic para Nexux.

La URL de conexión sale de DATABASE_URL (vía core.db.database_url), no del .ini —
así la misma config sirve en local (nexux_dev) y en Railway. target_metadata son
los modelos de core.db, para autogenerar migraciones.
"""
import os
import sys
from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool

from alembic import context

# Hacer importable el proyecto (core/)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import db  # noqa: E402

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# URL desde el entorno; si no hay DATABASE_URL, Alembic fallará con un error claro.
_url = db.database_url()
if _url:
    config.set_main_option("sqlalchemy.url", _url)

target_metadata = db.Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
