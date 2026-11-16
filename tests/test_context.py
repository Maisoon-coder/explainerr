import os
from pathlib import Path
import stat
from types import SimpleNamespace

import pytest

from explainerr.context import CONTEXT_FILES, MAX_CONTEXT_CHARS, read_context


def test_only_allowlisted_files_are_read_and_truncated(tmp_path):
    for name in CONTEXT_FILES:
        (tmp_path / name).write_text("中" * 5000, encoding="utf-8")
    (tmp_path / ".env").write_text("SECRET=never_read", encoding="utf-8")
    (tmp_path / "private.pem").write_text("secret", encoding="utf-8")
    for name in ("node_modules", ".git", "subdirectory"):
        (tmp_path / name).mkdir()
        (tmp_path / name / "README.md").write_text("nested secret", encoding="utf-8")
    context = read_context(tmp_path)
    assert set(context) == set(CONTEXT_FILES)
    assert all(value == "中" * MAX_CONTEXT_CHARS for value in context.values())


def test_missing_files_and_directories_are_skipped(tmp_path):
    (tmp_path / "README.md").mkdir()
    assert read_context(tmp_path) == {}


def test_unreadable_file_does_not_abort(tmp_path, monkeypatch):
    (tmp_path / "README.md").write_text("text", encoding="utf-8")
    def denied(*args, **kwargs):
        raise PermissionError("not readable")
    monkeypatch.setattr(os, "open", denied)
    assert read_context(tmp_path) == {}


def test_invalid_utf8_is_replaced(tmp_path):
    (tmp_path / "README.md").write_bytes(b"hello\xffworld")
    assert read_context(tmp_path) == {"README.md": "hello\ufffdworld"}


def test_bom_is_removed(tmp_path):
    (tmp_path / "package.json").write_text('{"scripts": {}}', encoding="utf-8-sig")
    assert read_context(tmp_path)["package.json"].startswith("{")


@pytest.mark.parametrize("kind", ["symlink", "hardlink"])
def test_links_cannot_read_sensitive_file(tmp_path, kind):
    secret = tmp_path / ".env"
    secret.write_text("SECRET=never_read", encoding="utf-8")
    alias = tmp_path / "README.md"
    try:
        if kind == "symlink":
            alias.symlink_to(secret)
        else:
            os.link(secret, alias)
    except OSError as exc:
        pytest.skip(f"系统不允许创建此类链接：{exc}")
    assert read_context(tmp_path) == {}


def test_current_directory_is_used(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    Path("requirements.txt").write_text("requests", encoding="utf-8")
    assert read_context() == {"requirements.txt": "requests"}


@pytest.mark.parametrize("attributes", [
    {"st_mode": stat.S_IFLNK},
    {"st_nlink": 2},
    {"st_file_attributes": 0x400},
    {"st_mode": stat.S_IFIFO},
])
def test_unsafe_file_types_are_rejected_before_open(tmp_path, monkeypatch, attributes):
    metadata = {"st_mode": stat.S_IFREG, "st_nlink": 1, "st_file_attributes": 0}
    metadata.update(attributes)
    monkeypatch.setattr(Path, "lstat", lambda self: SimpleNamespace(**metadata))
    def forbidden(*args, **kwargs):
        pytest.fail("不安全的文件类型不能被打开")
    monkeypatch.setattr(os, "open", forbidden)
    assert read_context(tmp_path) == {}


def test_file_replacement_is_detected(tmp_path, monkeypatch):
    path = tmp_path / "README.md"
    path.write_text("private replacement", encoding="utf-8")
    metadata = path.stat()
    # fstat 也是 pytest 输出捕获使用的函数，替换仅限于被测调用。
    with monkeypatch.context() as patch:
        patch.setattr(os, "fstat", lambda fd: SimpleNamespace(
            st_mode=stat.S_IFREG, st_nlink=1, st_dev=metadata.st_dev, st_ino=metadata.st_ino + 1,
        ))
        assert read_context(tmp_path) == {}
