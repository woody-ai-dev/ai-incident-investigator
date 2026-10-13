import pytest


@pytest.fixture(autouse=True)
def disable_live_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_ENABLED", "false")

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("PROMETHEUS_URL", raising=False)

    monkeypatch.delenv("ACTUATOR_URL", raising=False)
    monkeypatch.delenv("ACTUATOR_SERVICE", raising=False)
    monkeypatch.delenv("ACTUATOR_ENVIRONMENT", raising=False)
