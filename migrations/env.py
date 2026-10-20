import os

from alembic import context
from pydantic import SecretStr
from sqlalchemy import Connection

from ai_incident_investigator.storage.database import create_database_engine
from ai_incident_investigator.storage.models import Base

target_metadata = Base.metadata


def run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


if context.is_offline_mode():
    raise RuntimeError("This migration environment requires a database connection")

provided_connection = context.config.attributes.get("connection")
if isinstance(provided_connection, Connection):
    run_migrations(provided_connection)
else:
    raw_url = os.environ.get("DATABASE_URL", "").strip()
    if not raw_url:
        raise RuntimeError("DATABASE_URL is required for migrations")
    engine = create_database_engine(SecretStr(raw_url))
    try:
        with engine.connect() as connection:
            run_migrations(connection)
    finally:
        engine.dispose()
