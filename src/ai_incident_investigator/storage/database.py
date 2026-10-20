from pydantic import SecretStr
from sqlalchemy import Engine, create_engine

from ai_incident_investigator.settings import validate_database_url


def create_database_engine(value: SecretStr) -> Engine:
    validated = validate_database_url(value)
    return create_engine(
        validated.get_secret_value(),
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=5,
        pool_timeout=3,
        hide_parameters=True,
        connect_args={
            "connect_timeout": 3,
            "options": "-c statement_timeout=5000 -c lock_timeout=3000",
        },
    )
