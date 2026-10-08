import pytest


@pytest.fixture(autouse=True)
def disable_live_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_ENABLED", "false")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
