import pytest
from pydantic import ValidationError

from ai_incident_investigator.settings import get_settings


def configure_target(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(
        "ACTUATOR_URL",
        "http://order-service:8081/actuator/",
    )
    monkeypatch.setenv("ACTUATOR_SERVICE", "order-service")
    monkeypatch.setenv("ACTUATOR_ENVIRONMENT", "local")


def test_actuator_is_disabled_without_configuration() -> None:
    assert get_settings().actuator_target is None


def test_actuator_configuration_is_read_from_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configure_target(monkeypatch)

    target = get_settings().actuator_target

    assert target is not None
    assert str(target.base_url) == "http://order-service:8081/actuator/"
    assert target.service == "order-service"
    assert target.environment == "local"


@pytest.mark.parametrize(
    "name",
    ["ACTUATOR_URL", "ACTUATOR_SERVICE", "ACTUATOR_ENVIRONMENT"],
)
def test_partial_actuator_configuration_is_rejected(
    name: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configure_target(monkeypatch)
    monkeypatch.delenv(name)

    with pytest.raises(ValidationError):
        get_settings()


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "http://user:password@order-service:8081/actuator/",
        "http://order-service:8081/actuator/?token=secret",
        "http://order-service:8081/actuator/#fragment",
        "http://order-service:8081/" + "x" * 512,
    ],
)
def test_invalid_actuator_url_is_rejected(
    url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configure_target(monkeypatch)
    monkeypatch.setenv("ACTUATOR_URL", url)

    with pytest.raises(ValidationError):
        get_settings()


@pytest.mark.parametrize(
    "name",
    ["ACTUATOR_SERVICE", "ACTUATOR_ENVIRONMENT"],
)
def test_blank_target_identifier_is_rejected(
    name: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configure_target(monkeypatch)
    monkeypatch.setenv(name, "   ")

    with pytest.raises(ValidationError):
        get_settings()
