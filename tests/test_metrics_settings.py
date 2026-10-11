import pytest
from pydantic import ValidationError

from ai_incident_investigator.settings import get_settings


def test_metrics_are_disabled_without_url() -> None:
    assert get_settings().prometheus_url is None


def test_metrics_url_is_read_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PROMETHEUS_URL", "http://prometheus:9090")

    assert str(get_settings().prometheus_url) == "http://prometheus:9090/"


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "http://user:password@prometheus:9090",
        "http://prometheus:9090?token=secret",
        "http://prometheus:9090#fragment",
        "http://prometheus:9090/" + "x" * 512,
    ],
)
def test_invalid_metrics_url_is_rejected(url: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PROMETHEUS_URL", url)

    with pytest.raises(ValidationError):
        get_settings()
