import pytest
from pydantic import ValidationError

from ai_incident_investigator.settings import get_settings


def test_storage_disabled_without_database_url() -> None:
    assert get_settings().database_url is None


def test_database_credentials_are_not_serialized_or_printed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret = "distinct-test-database-password"
    monkeypatch.setenv("DATABASE_URL", f"postgresql+psycopg://user:{secret}@localhost/investigator")
    settings = get_settings()
    assert settings.database_url is not None
    assert secret not in repr(settings)
    assert secret not in settings.model_dump_json()


@pytest.mark.parametrize(
    "url",
    [
        "sqlite:///private-password",
        "postgresql://user:private-password@localhost/investigator",
        "postgresql+psycopg://user:private-password@localhost/",
        "not-a-url-with-private-password",
    ],
)
def test_invalid_database_url_is_rejected_without_exposing_password(
    monkeypatch: pytest.MonkeyPatch, url: str
) -> None:
    monkeypatch.setenv("DATABASE_URL", url)
    with pytest.raises(ValidationError) as captured:
        get_settings()
    assert "private-password" not in str(captured.value)
