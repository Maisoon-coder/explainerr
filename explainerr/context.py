"""只读取当前目录中白名单里的普通文件。"""

import os
from pathlib import Path
import stat


CONTEXT_FILES = ("package.json", "pyproject.toml", "requirements.txt", "README.md")
MAX_CONTEXT_CHARS = 4000


def read_context(directory: Path | None = None) -> dict[str, str]:
    directory = Path.cwd() if directory is None else Path(directory)
    result: dict[str, str] = {}
    for name in CONTEXT_FILES:
        path = directory / name
        try:
            info = path.lstat()
            # 不通过符号链接、Windows 重解析点或硬链接绕过白名单。
            if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
                    or getattr(info, "st_file_attributes", 0) & 0x400):
                continue
            flags = os.O_RDONLY | getattr(os, "O_BINARY", 0)
            flags |= getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
            fd = os.open(path, flags)
            with os.fdopen(fd, "rb") as handle:
                opened = os.fstat(handle.fileno())
                if (not stat.S_ISREG(opened.st_mode) or opened.st_nlink != 1
                        or (opened.st_dev, opened.st_ino) != (info.st_dev, info.st_ino)):
                    continue
                # UTF-8 每字符最多四字节；限制实际读取量，再限制解码后字符数。
                raw = handle.read(MAX_CONTEXT_CHARS * 4)
            result[name] = raw.decode("utf-8-sig", errors="replace")[:MAX_CONTEXT_CHARS]
        except OSError:
            continue  # 缺失、不可读或并发删除的文件均不阻断解释。
    return result
