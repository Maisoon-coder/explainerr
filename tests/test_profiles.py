import io
import json
import os
from pathlib import Path
import stat
import sys
from types import SimpleNamespace

import pytest

from explainerr import cli, llm, profiles


KEY = "fake-key-for-tests-12345678"
URL = "https://profile.example.test/v1"
MODEL = "test-profile-model"
ERROR = "ModuleNotFoundError: No module named 'requests'"


def add(name="saved", key=KEY):
    profiles.add_profile(name, key, URL, MODEL)


def install_api(monkeypatch, failure=None):
    captured = []
    response = {"choices": [{"message": {"content": json.dumps({
        "conclusion": "模型返回的解释。", "causes": ["测试原因。"], "next_steps": ["检查依赖。"],
    }, ensure_ascii=False)}}]}
    def open_request(request, timeout):
        captured.append((request, timeout))
        if failure:
            raise failure
        return io.BytesIO(json.dumps(response).encode("utf-8"))
    monkeypatch.setattr(llm, "build_opener", lambda *args: SimpleNamespace(open=open_request))
    return captured


def forbid_api(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("此场景不能调用 API")
    monkeypatch.setattr(llm, "build_opener", forbidden)


def set_environment(monkeypatch, key="fake-environment-key", enabled="1"):
    env = {"OPENAI_API_KEY": key, "OPENAI_BASE_URL": "https://env.example.test/v1",
           "OPENAI_MODEL": "environment-model", "EXPLAINERR_USE_LLM": enabled}
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    return env


def corrupt_file(raw=b'{"profiles": invalid-secret-content'):
    path = profiles.config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    return path


def test_storage_path_is_in_home_and_reads_do_not_create_files():
    path = profiles.config_path()
    assert path == Path.home() / ".explainerr" / "config.json"
    assert profiles.load_config() == {"default": None, "profiles": {}}
    assert not path.parent.exists()


def test_add_update_and_preserve_other_profiles():
    add("first")
    add("second", "another-fake-key")
    profiles.set_default("first")
    profiles.add_profile("first", "updated-fake-key", "https://updated.example.test/v1/", "updated-model")
    data = profiles.load_config()
    assert data["default"] == "first"
    assert data["profiles"]["first"] == {
        "api_key": "updated-fake-key", "base_url": "https://updated.example.test/v1", "model": "updated-model",
    }
    assert data["profiles"]["second"]["api_key"] == "another-fake-key"
    assert not list(profiles.config_path().parent.glob("*.tmp"))


def test_remove_default_clears_selection():
    add("first")
    add("second")
    profiles.set_default("first")
    profiles.remove_profile("first")
    assert profiles.load_config()["default"] is None
    assert set(profiles.load_config()["profiles"]) == {"second"}


def test_remove_other_profile_keeps_default():
    add("first")
    add("second")
    profiles.set_default("first")
    profiles.remove_profile("second")
    assert profiles.load_config()["default"] == "first"


@pytest.mark.parametrize("action", [profiles.remove_profile, profiles.set_default])
def test_missing_profile_does_not_modify_file(action):
    add()
    before = profiles.config_path().read_bytes()
    with pytest.raises(profiles.ProfileError, match="未找到"):
        action("missing")
    assert profiles.config_path().read_bytes() == before


@pytest.mark.parametrize("raw", [b"not JSON", b"\xff", b"[]", b"{}", b'{"profiles":[]}',
    b'{"profiles":{"x":{}}}', b'{"profiles":{},"default":"missing"}',
    b'{"profiles":{},"default":[]}', b"x" * (profiles.MAX_CONFIG_BYTES + 1)])
def test_corrupt_config_is_reported_without_echoing_content(raw):
    corrupt_file(raw)
    with pytest.raises(profiles.ProfileError, match="重新创建") as exc:
        profiles.load_config()
    assert "not JSON" not in str(exc.value)


def test_add_does_not_silently_overwrite_corrupt_config():
    path = corrupt_file()
    before = path.read_bytes()
    with pytest.raises(profiles.ProfileError, match="重新创建"):
        add()
    assert path.read_bytes() == before


def test_unreadable_config_has_safe_error(monkeypatch):
    def denied(*args, **kwargs):
        raise PermissionError(KEY)
    monkeypatch.setattr(Path, "open", denied)
    with pytest.raises(profiles.ProfileError, match="无法读取") as exc:
        profiles.load_config()
    assert KEY not in str(exc.value)


def test_failed_atomic_replace_preserves_config(monkeypatch):
    add()
    path = profiles.config_path()
    before = path.read_bytes()
    def denied(*args, **kwargs):
        raise PermissionError(KEY)
    monkeypatch.setattr(os, "replace", denied)
    with pytest.raises(profiles.ProfileError, match="无法保存") as exc:
        add("new")
    assert KEY not in str(exc.value)
    assert path.read_bytes() == before
    assert list(path.parent.iterdir()) == [path]


def test_unwritable_directory_has_safe_error(monkeypatch):
    def denied(*args, **kwargs):
        raise PermissionError(KEY)
    monkeypatch.setattr(Path, "mkdir", denied)
    with pytest.raises(profiles.ProfileError, match="无法保存") as exc:
        add()
    assert KEY not in str(exc.value)


@pytest.mark.skipif(os.name == "nt", reason="POSIX 文件权限检查不适用于 Windows ACL")
def test_private_file_permissions():
    add()
    path = profiles.config_path()
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700


@pytest.mark.parametrize("name", ["../outside", "", "a\nb", "-option", "x" * 65])
def test_invalid_name_is_rejected_without_writing(name):
    with pytest.raises(profiles.ProfileError):
        add(name)
    assert not profiles.config_path().exists()


@pytest.mark.parametrize(("key", "url", "model"), [
    ("", URL, MODEL), (KEY, URL, ""), ("fake\nkey", URL, MODEL),
    (KEY, "file:///private", MODEL), (KEY, "https://user:secret@example.test/v1", MODEL),
    (KEY, "https://example.test/v1?api_key=secret", MODEL),
    (KEY, "https://example.test:bad/v1", MODEL),
    ("fake\ud800key", URL, MODEL), (KEY, URL, "model\u202ename"),
])
def test_invalid_settings_are_rejected(key, url, model):
    with pytest.raises(profiles.ProfileError):
        profiles.add_profile("invalid", key, url, model)
    assert not profiles.config_path().exists()


@pytest.mark.parametrize("key", ["a", "abcd", "12345678", KEY])
def test_key_mask_does_not_expose_complete_key(key):
    masked = profiles.mask_key(key)
    assert key not in masked
    if len(key) > 8:
        assert masked == key[:4] + "…" + key[-4:]


def test_profile_cli_lifecycle(capsys):
    assert cli.main(["profile", "list"]) == 0
    assert "尚未保存" in capsys.readouterr().out
    assert cli.main(["profile", "add", "示例", "--api-key", KEY, "--base-url", URL, "--model", MODEL]) == 0
    assert KEY not in capsys.readouterr().out
    assert cli.main(["profile", "default", "示例"]) == 0
    capsys.readouterr()
    assert cli.main(["profile", "list"]) == 0
    output = capsys.readouterr().out
    assert "示例\t是" in output and URL in output and MODEL in output
    assert KEY not in output and profiles.mask_key(KEY) in output
    assert cli.main(["profile", "remove", "示例"]) == 0
    assert profiles.load_config() == {"default": None, "profiles": {}}


@pytest.mark.parametrize("action", ["remove", "default"])
def test_missing_profile_management_returns_two(action, capsys):
    assert cli.main(["profile", action, "missing"]) == 2
    assert "未找到" in capsys.readouterr().err


def test_profile_parser_errors_do_not_echo_secrets(capsys):
    with pytest.raises(SystemExit) as exc:
        cli.main(["profile", "add", "test", "--wrong-key", KEY])
    assert exc.value.code == 2
    assert KEY not in capsys.readouterr().err


def test_profile_help_does_not_write_config(capsys):
    with pytest.raises(SystemExit) as exc:
        cli.main(["profile", "--help"])
    assert exc.value.code == 0
    assert "default" in capsys.readouterr().out
    assert not profiles.config_path().exists()


def test_no_settings_uses_local_without_creating_config(monkeypatch, capsys):
    forbid_api(monkeypatch)
    assert cli.main([ERROR]) == 0
    assert "Python" in capsys.readouterr().out
    assert not profiles.config_path().exists()


def test_saved_profile_without_default_does_not_enable_llm(monkeypatch):
    add()
    forbid_api(monkeypatch)
    assert cli.main([ERROR]) == 0


def test_explicit_profile_overrides_environment_and_default(monkeypatch, capsys):
    add("chosen")
    add("default", "fake-default-key")
    profiles.set_default("default")
    set_environment(monkeypatch)
    captured = install_api(monkeypatch)
    before = dict(os.environ)
    assert cli.main(["--profile", "chosen", ERROR]) == 0
    request, timeout = captured[0]
    assert request.full_url == URL + "/chat/completions"
    assert request.get_header("Authorization") == "Bearer " + KEY
    assert json.loads(request.data)["model"] == MODEL
    assert dict(os.environ) == before
    assert "模型返回" in capsys.readouterr().out


def test_environment_overrides_default_and_bypasses_bad_config(monkeypatch):
    add()
    profiles.set_default("saved")
    env = set_environment(monkeypatch)
    assert profiles.resolve_llm_env(None, env) == env
    corrupt_file()
    captured = install_api(monkeypatch)
    assert cli.main([ERROR]) == 0
    request, _ = captured[0]
    assert request.full_url == "https://env.example.test/v1/chat/completions"
    assert request.get_header("Authorization") == "Bearer fake-environment-key"


@pytest.mark.parametrize(("enabled", "key"), [("", ""), ("0", "unused-fake-key"), ("1", "")])
def test_default_applies_when_environment_is_not_enabled(monkeypatch, enabled, key):
    add()
    profiles.set_default("saved")
    set_environment(monkeypatch, key=key, enabled=enabled)
    captured = install_api(monkeypatch)
    assert cli.main([ERROR]) == 0
    assert captured[0][0].get_header("Authorization") == "Bearer " + KEY


def test_missing_explicit_profile_falls_back_without_trying_other_sources(monkeypatch, capsys):
    add()
    profiles.set_default("saved")
    set_environment(monkeypatch)
    forbid_api(monkeypatch)
    assert cli.main(["--profile", "missing", ERROR]) == 0
    captured = capsys.readouterr()
    assert "未找到模型配置“missing”" in captured.err and "已回退" in captured.err
    assert "Python" in captured.out


def test_corrupt_config_falls_back_and_management_reports_error(monkeypatch, capsys):
    corrupt_file()
    forbid_api(monkeypatch)
    assert cli.main([ERROR]) == 0
    captured = capsys.readouterr()
    assert "重新创建" in captured.err and "已回退" in captured.err
    assert "invalid-secret-content" not in captured.err
    assert cli.main(["profile", "list"]) == 2
    assert "重新创建" in capsys.readouterr().err


def test_profile_api_failure_falls_back_without_leaking_key(monkeypatch, capsys):
    add()
    install_api(monkeypatch, failure=TimeoutError(KEY))
    assert cli.main(["--profile", "saved", ERROR]) == 0
    captured = capsys.readouterr()
    assert "Python" in captured.out and "LLM 调用失败" in captured.err
    assert KEY not in captured.out + captured.err


def test_local_bypasses_profiles_environment_and_corrupt_file(monkeypatch, capsys):
    corrupt_file()
    set_environment(monkeypatch)
    forbid_api(monkeypatch)
    assert cli.main(["--local", ERROR]) == 0
    assert capsys.readouterr().err == ""


def test_local_and_explicit_profile_are_mutually_exclusive():
    with pytest.raises(SystemExit) as exc:
        cli.main(["--local", "--profile", "saved", ERROR])
    assert exc.value.code == 2


def test_profile_stdin_and_context(monkeypatch, tmp_path):
    add()
    monkeypatch.chdir(tmp_path)
    (tmp_path / "requirements.txt").write_text("requests", encoding="utf-8")
    monkeypatch.setattr(sys, "stdin", io.StringIO(ERROR))
    captured = install_api(monkeypatch)
    assert cli.main(["--profile", "saved", "--context"]) == 0
    user_data = json.loads(json.loads(captured[0][0].data)["messages"][1]["content"])
    assert user_data == {"error": ERROR, "context": {"requirements.txt": "requests"}}


def test_profile_preserves_timeout_only_from_environment(monkeypatch):
    add()
    set_environment(monkeypatch)
    monkeypatch.setenv("EXPLAINERR_TIMEOUT", "60")
    captured = install_api(monkeypatch)
    cli.main(["--profile", "saved", ERROR])
    assert captured[0][1] == 60


def test_short_environment_aliases_remain_supported(monkeypatch):
    for name, value in {"API_KEY": KEY, "BASE_URL": URL, "MODEL": MODEL, "EXPLAINERR_USE_LLM": "1"}.items():
        monkeypatch.setenv(name, value)
    captured = install_api(monkeypatch)
    cli.main([ERROR])
    request, _ = captured[0]
    assert request.full_url == URL + "/chat/completions"
    assert request.get_header("Authorization") == "Bearer " + KEY
    assert json.loads(request.data)["model"] == MODEL


def test_openai_environment_names_take_precedence(monkeypatch):
    monkeypatch.setenv("API_KEY", "unused-fake-key")
    monkeypatch.setenv("BASE_URL", "https://unused.example.test/v1")
    monkeypatch.setenv("MODEL", "unused-model")
    set_environment(monkeypatch)
    captured = install_api(monkeypatch)
    cli.main([ERROR])
    request, _ = captured[0]
    assert request.full_url == "https://env.example.test/v1/chat/completions"
    assert request.get_header("Authorization") == "Bearer fake-environment-key"
    assert json.loads(request.data)["model"] == "environment-model"
