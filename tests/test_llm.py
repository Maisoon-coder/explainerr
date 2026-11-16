import io
import json
from types import SimpleNamespace
from urllib.error import HTTPError, URLError
from urllib.request import Request

import pytest

from explainerr import cli, llm


VALID = {"conclusion": "当前环境缺少依赖。", "causes": ["依赖未安装。"],
         "next_steps": ["python -m pip --version"]}


def response_bytes(data=VALID):
    return json.dumps({"choices": [{"message": {"content": json.dumps(data, ensure_ascii=False)}}]}).encode()


@pytest.fixture
def enabled_env(monkeypatch):
    env = {"OPENAI_API_KEY": "test-secret", "EXPLAINERR_USE_LLM": "1"}
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    return env


def install_response(monkeypatch, raw):
    captured = {}
    def open_request(request, timeout):
        captured.update(request=request, timeout=timeout)
        return io.BytesIO(raw)
    monkeypatch.setattr(llm, "build_opener", lambda *handlers: SimpleNamespace(open=open_request))
    return captured


def test_request_and_valid_response(monkeypatch, enabled_env):
    captured = install_response(monkeypatch, response_bytes())
    env = {**enabled_env, "OPENAI_BASE_URL": "https://example.test/v1/", "OPENAI_MODEL": "test-model",
           "EXPLAINERR_TIMEOUT": "3.5"}
    result = llm.explain_llm("ModuleNotFoundError", {"requirements.txt": "requests"}, env)
    assert result.conclusion == VALID["conclusion"]
    request = captured["request"]
    assert request.full_url == "https://example.test/v1/chat/completions"
    assert request.get_method() == "POST"
    assert request.get_header("Authorization") == "Bearer test-secret"
    assert captured["timeout"] == 3.5
    payload = json.loads(request.data)
    assert payload["model"] == "test-model"
    user_data = json.loads(payload["messages"][1]["content"])
    assert user_data == {"error": "ModuleNotFoundError", "context": {"requirements.txt": "requests"}}
    assert "不可信" in payload["messages"][0]["content"]


def test_llm_cli_success(monkeypatch, enabled_env, capsys):
    install_response(monkeypatch, response_bytes())
    assert cli.main(["command not found"]) == 0
    captured = capsys.readouterr()
    assert VALID["conclusion"] in captured.out
    assert captured.err == ""


@pytest.mark.parametrize("failure", [TimeoutError("test-secret"), URLError("test-secret"),
    HTTPError("https://example.test", 401, "test-secret", {}, None),
    OSError("test-secret"), ValueError("test-secret")])
def test_network_failures_fall_back(monkeypatch, enabled_env, capsys, failure):
    def failed(*args, **kwargs):
        raise failure
    monkeypatch.setattr(llm, "build_opener", lambda *handlers: SimpleNamespace(open=failed))
    assert cli.main(["command not found"]) == 0
    captured = capsys.readouterr()
    assert "终端找不到" in captured.out
    assert "已回退到本地规则模式" in captured.err
    assert "test-secret" not in captured.out + captured.err


@pytest.mark.parametrize("raw", [b"not json", b"{}", b'{"choices": []}',
    b'{"choices":[{"message":{"content":null}}]}', b"\xff",
    b"x" * (llm.MAX_RESPONSE_BYTES + 1), response_bytes({}),
    response_bytes({**VALID, "causes": "bad"}), response_bytes({**VALID, "next_steps": []}),
    response_bytes({**VALID, "conclusion": "English only"})])
def test_bad_responses_fall_back(monkeypatch, enabled_env, capsys, raw):
    install_response(monkeypatch, raw)
    assert cli.main(["command not found"]) == 0
    captured = capsys.readouterr()
    assert "终端找不到" in captured.out
    assert "已回退" in captured.err


@pytest.mark.parametrize(("name", "value"), [
    ("EXPLAINERR_TIMEOUT", "nan"), ("EXPLAINERR_TIMEOUT", "0"),
    ("EXPLAINERR_TIMEOUT", "999"), ("EXPLAINERR_TIMEOUT", "invalid"),
    ("OPENAI_BASE_URL", "file:///tmp/api"), ("OPENAI_BASE_URL", "https://user:secret@example.test/v1"),
    ("OPENAI_BASE_URL", "https://example.test/v1?secret=value"),
])
def test_bad_configuration_falls_back(monkeypatch, enabled_env, capsys, name, value):
    monkeypatch.setenv(name, value)
    def unexpected(*args):
        pytest.fail("配置错误时不应发送请求")
    monkeypatch.setattr(llm, "build_opener", unexpected)
    assert cli.main(["command not found"]) == 0
    assert "已回退" in capsys.readouterr().err


def test_redirects_are_rejected():
    request = Request("https://example.test/v1/chat/completions", headers={"Authorization": "Bearer secret"})
    with pytest.raises(HTTPError):
        llm._NoRedirect().redirect_request(request, None, 302, "redirect", {}, "https://other.test")


def test_markdown_json_is_accepted(monkeypatch, enabled_env):
    content = "```json\n" + json.dumps(VALID, ensure_ascii=False) + "\n```"
    raw = json.dumps({"choices": [{"message": {"content": content}}]}).encode()
    install_response(monkeypatch, raw)
    assert llm.explain_llm("error", {}, enabled_env).conclusion == VALID["conclusion"]
