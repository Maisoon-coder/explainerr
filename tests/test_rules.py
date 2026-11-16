import pytest

from explainerr.models import Explanation
from explainerr.rules import explain_local


@pytest.mark.parametrize(("error", "expected"), [
    ("bash: foo: command not found", "终端找不到"),
    ("'foo' is not recognized as an internal or external command", "终端找不到"),
    ("foo : The term 'foo' is not recognized as the name of a cmdlet", "终端找不到"),
    ("Permission denied: /tmp/app", "权限"),
    ("npm ERR! code EACCES", "权限"),
    ('npm ERR! missing script: dev', "npm 脚本"),
    ('npm error Missing script: "dev"', "npm 脚本"),
    ("ModuleNotFoundError: No module named 'requests'", "requests"),
    ("ImportError: cannot import name 'app' from 'project'", "指定名称"),
    ("Error: Cannot find module 'express'", "无法解析"),
    ("Error [ERR_MODULE_NOT_FOUND]: Cannot find package 'vite'", "无法解析"),
    ("Module not found: Can't resolve './missing'", "无法解析"),
    ("EADDRINUSE: address already in use :::3000", "3000"),
    ("OSError: [Errno 98] Address already in use", "端口"),
    ("[WinError 10048] Only one usage of each socket address", "端口"),
    ("unclassified failure", "无法确定"),
])
def test_rules(error, expected):
    result = explain_local(error)
    assert expected in result.conclusion
    assert 1 <= len(result.causes) <= 3
    assert 1 <= len(result.next_steps) <= 3
    assert result.render().startswith("一句话结论：")


def test_python_error_is_not_misclassified_as_node():
    assert "Python" in explain_local("ModuleNotFoundError: No module named 'foo'").conclusion


def test_context_supplies_available_scripts():
    result = explain_local("missing script: dev", {
        "package.json": '{"scripts": {"start": "node main.js", "test": "pytest"}}'
    })
    assert "start、test" in result.render()
    assert "node main.js" not in result.render()


@pytest.mark.parametrize("content", ['{"scripts":', "null", "[]", '{"scripts": []}'])
def test_invalid_package_json_is_ignored(content):
    assert "npm 脚本" in explain_local("missing script: dev", {"package.json": content}).conclusion


def test_ansi_is_removed_before_matching():
    assert "终端找不到" in explain_local("bash: foo: \x1b[31mcommand not found\x1b[0m").conclusion


def test_output_is_bounded_and_has_no_terminal_controls():
    result = Explanation("\x1b[31m结论\x1b[0m\n第二行", ["原因"] * 5,
                         ["\x1b]0;title\x07检查\n文件"] * 4)
    assert result.conclusion == "结论 第二行"
    assert len(result.causes) == len(result.next_steps) == 3
    assert "\x1b" not in result.render()
    assert len(result.render().splitlines()) == 9


@pytest.mark.parametrize("data", [None, [], {}, {"conclusion": "原因", "causes": "错误", "next_steps": []}])
def test_malformed_explanation_is_rejected(data):
    with pytest.raises((ValueError, KeyError)):
        Explanation.from_mapping(data)
