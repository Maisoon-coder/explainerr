import pytest
from pathlib import Path


@pytest.fixture(autouse=True)
def isolated_environment(monkeypatch, tmp_path):
    for name in ("OPENAI_API_KEY", "EXPLAINERR_USE_LLM", "OPENAI_BASE_URL",
                 "OPENAI_MODEL", "EXPLAINERR_TIMEOUT", "API_KEY", "BASE_URL", "MODEL"):
        monkeypatch.delenv(name, raising=False)
    # 同时隔离进程内调用和 CLI 子进程，绝不读取真实用户的 Profile。
    fake_home = tmp_path / "isolated-home"
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: fake_home))
    monkeypatch.setenv("HOME", str(fake_home))
    monkeypatch.setenv("USERPROFILE", str(fake_home))
