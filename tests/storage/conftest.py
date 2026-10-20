import os
from collections.abc import Iterator
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.schema import CreateSchema, DropSchema


@pytest.fixture(params=["sqlite", pytest.param("postgres", marks=pytest.mark.postgres)])
def storage_engine(request: pytest.FixtureRequest, tmp_path: Path) -> Iterator[Engine]:
    admin: Engine | None = None
    schema: str | None = None

    if request.param == "sqlite":
        engine = create_engine(
            f"sqlite:///{tmp_path / 'investigations.db'}",
            connect_args={"check_same_thread": False},
        )
    else:
        raw_url = os.environ.get("TEST_DATABASE_URL")
        if not raw_url:
            pytest.skip("Set TEST_DATABASE_URL to run PostgreSQL integration tests")
        url = make_url(raw_url)
        if url.drivername != "postgresql+psycopg" or not (url.database or "").endswith("_test"):
            pytest.fail("TEST_DATABASE_URL must use psycopg and a database ending in _test")
        schema = f"test_{uuid4().hex}"
        admin = create_engine(url, hide_parameters=True)
        with admin.begin() as connection:
            connection.execute(CreateSchema(schema))
        engine = create_engine(
            url.update_query_dict({"options": f"-c search_path={schema}"}),
            hide_parameters=True,
        )

    try:
        config = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
        with engine.begin() as connection:
            config.attributes["connection"] = connection
            command.upgrade(config, "head")
        yield engine
    finally:
        engine.dispose()
        if admin is not None and schema is not None:
            try:
                with admin.begin() as connection:
                    connection.execute(DropSchema(schema, cascade=True))
            finally:
                admin.dispose()
