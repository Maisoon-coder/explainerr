import io
import os
import subprocess
import sys

import pytest

from explainerr import cli


def test_positional_text(capsys):
    assert cli.main(["npm ERR! missing script: dev"]) == 0
    captured = capsys.readouterr()
    assert "npm 脚本" in captured.out
    assert captured.err == ""


def test_stdin(monkeypatch, capsys):
    monkeypatch.setattr(sys, "stdin", io.StringIO("EADDRINUSE: address already in use :::3000\n"))
    assert cli.main([]) == 0
    assert "3000" in capsys.readouterr().out


def test_positional_input_takes_precedence(monkeypatch, capsys):
    monkeypatch.setattr(sys, "stdin", io.StringIO("Permission denied"))
    cli.main(["command not found"])
    assert "终端找不到" in capsys.readouterr().out


@pytest.mark.parametrize("args", [[""], ["  \n\t"], ["\x1b[31m\x1b[0m"], []])
def test_empty_input(args, monkeypatch, capsys):
    monkeypatch.setattr(sys, "stdin", io.StringIO(""))
    with pytest.raises(SystemExit) as exc:
        cli.main(args)
    assert exc.value.code == 2
    assert "不能为空" in capsys.readouterr().err


def test_terminal_without_input_shows_usage(monkeypatch, capsys):
    stream = io.StringIO()
    monkeypatch.setattr(stream, "isatty", lambda: True)
    monkeypatch.setattr(sys, "stdin", stream)
    with pytest.raises(SystemExit) as exc:
        cli.main([])
    assert exc.value.code == 2
    assert "请传入报错文本" in capsys.readouterr().err


def test_input_limit(monkeypatch, capsys):
    stream = io.StringIO("command not found\n" + "x" * 50000)
    monkeypatch.setattr(sys, "stdin", stream)
    cli.main([])
    captured = capsys.readouterr()
    assert stream.tell() == cli.MAX_ERROR_CHARS + 1
    assert "已截断" in captured.err
    assert "终端找不到" in captured.out


def test_context_is_opt_in(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "package.json").write_text('{"scripts":{"start":"node main.js"}}', encoding="utf-8")
    cli.main(["missing script: dev"])
    assert "包含：start" not in capsys.readouterr().out
    cli.main(["--context", "missing script: dev"])
    assert "包含：start" in capsys.readouterr().out


@pytest.mark.parametrize(("key", "enabled"), [("", "1"), ("secret", "0"), ("secret", ""), ("   ", "1")])
def test_llm_requires_both_environment_variables(key, enabled, monkeypatch, capsys):
    monkeypatch.setenv("OPENAI_API_KEY", key)
    monkeypatch.setenv("EXPLAINERR_USE_LLM", enabled)
    def unexpected(*args):
        pytest.fail("未同时启用两个变量时不应访问 API")
    monkeypatch.setattr(cli, "explain_llm", unexpected)
    assert cli.main(["command not found"]) == 0
    assert capsys.readouterr().err == ""


def test_commands_are_never_executed_and_files_are_unchanged(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    source = tmp_path / "README.md"
    source.write_text("existing content", encoding="utf-8")
    def forbidden(*args, **kwargs):
        pytest.fail("解释器不能执行命令")
    monkeypatch.setattr(os, "system", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    for error in ("command not found", "permission denied", "missing script: dev",
                  "EADDRINUSE :::3000", "ModuleNotFoundError: No module named 'requests'",
                  "Cannot find module 'express'; touch injected"):
        assert cli.main(["--context", error]) == 0
    assert source.read_text(encoding="utf-8") == "existing content"
    assert list(tmp_path.iterdir()) == [source]


@pytest.mark.parametrize("flag", ["--help", "--version"])
def test_help_and_version(flag, capsys):
    with pytest.raises(SystemExit) as exc:
        cli.main([flag])
    assert exc.value.code == 0
    assert "explainerr" in capsys.readouterr().out


def test_module_entrypoint():
    completed = subprocess.run(
        [sys.executable, "-m", "explainerr", "bash: foo: command not found"],
        capture_output=True, text=True, encoding="utf-8",
        env={**os.environ, "PYTHONIOENCODING": "utf-8"}, check=True,
    )
    assert "终端找不到" in completed.stdout
    assert completed.stderr == ""
