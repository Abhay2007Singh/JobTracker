# Alembic migration environment — wires up the database URL and model metadata.

import sys
from pathlib import Path
from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool
from alembic import context

# Put the project root on sys.path so "from app.*" imports work when running alembic
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import config as app_config
from app.database import Base

# Register all models so autogenerate can detect schema changes
from app.models.application import Application  # noqa: F401

alembic_cfg = context.config

# Override the URL with the value from .env so we never hardcode it here
alembic_cfg.set_main_option("sqlalchemy.url", app_config.DATABASE_URL)

if alembic_cfg.config_file_name is not None:
    fileConfig(alembic_cfg.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    url = alembic_cfg.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        alembic_cfg.get_section(alembic_cfg.config_ini_section, {}),
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
