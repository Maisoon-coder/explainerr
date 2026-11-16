import pytest


@pytest.fixture(autouse=True)
def isolated_environment(monkeypatch):
    for name in ("OPENAI_API_KEY", "EXPLAINERR_USE_LLM", "OPENAI_BASE_URL",
                 "OPENAI_MODEL", "EXPLAINERR_TIMEOUT"):
        monkeypatch.delenv(name, raising=False)
