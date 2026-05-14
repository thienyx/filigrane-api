from __future__ import annotations

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool
from sqlalchemy.engine import Connection

import filigrane_api.models.auth_tokens  # noqa: F401
import filigrane_api.models.entities  # noqa: F401
from filigrane_api.models.base import Base

config = context.config
if config.config_file_name:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _sync_database_url(raw: str) -> str:
    if raw.startswith("postgresql+asyncpg://"):
        return raw.replace(
            "postgresql+asyncpg://", "postgresql+psycopg://", maxsplit=1
        )
    if raw.startswith("postgres://"):
        return raw.replace("postgres://", "postgresql+psycopg://", maxsplit=1)
    if raw.startswith("postgresql://"):
        return raw.replace("postgresql://", "postgresql+psycopg://", maxsplit=1)
    if raw.startswith("postgresql+psycopg://"):
        return raw
    return raw


def _configure_url_from_env() -> None:
    raw = os.environ.get("FILIGRANE_DATABASE_URL")
    if raw is None:
        msg = "FILIGRANE_DATABASE_URL is required for Alembic migrations"
        raise RuntimeError(msg)
    sync_url = _sync_database_url(raw)
    config.set_main_option("sqlalchemy.url", sync_url)


def run_migrations_offline() -> None:
    _configure_url_from_env()
    url = config.get_main_option("sqlalchemy.url")
    if url is None:
        raise RuntimeError("sqlalchemy.url is not configured")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    _configure_url_from_env()
    ini_section = config.get_section(config.config_ini_section)
    if ini_section is None:
        raise RuntimeError("alembic.ini section missing")
    connectable = engine_from_config(
        ini_section,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    def do_run_migrations(connection: Connection) -> None:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()

    with connectable.connect() as connection:
        do_run_migrations(connection)


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
