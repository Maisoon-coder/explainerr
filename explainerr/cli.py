"""CLI 输入、模式选择与输出；不包含命令执行或文件修改操作。"""

import argparse
import os
import sys

from . import __version__
from .context import read_context
from .llm import explain_llm, is_enabled
from .models import plain_text
from .rules import explain_local


MAX_ERROR_CHARS = 16000


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="explainerr", description="用中文解释 CLI 报错；建议只打印，不执行。",
        add_help=False,
    )
    parser.add_argument("error", nargs="?", metavar="报错文本", help="省略时从 stdin 读取")
    parser.add_argument("--context", action="store_true", help="读取当前目录的四个白名单文件，每个最多 4000 字符")
    parser.add_argument("-h", "--help", action="help", help="显示帮助并退出")
    parser.add_argument("--version", action="version", version=f"explainerr {__version__}")
    return parser


def _run(argv: list[str] | None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.error is None:
        if sys.stdin.isatty():
            parser.error("请传入报错文本，或通过管道提供 stdin。")
        try:
            error = sys.stdin.read(MAX_ERROR_CHARS + 1)
        except (OSError, UnicodeError):
            parser.error("无法读取 stdin；请检查输入和终端编码。")
    else:
        error = args.error
    if len(error) > MAX_ERROR_CHARS:
        print(f"提示：报错文本已截断为前 {MAX_ERROR_CHARS} 字符。", file=sys.stderr)
        error = error[:MAX_ERROR_CHARS]
    error = plain_text(error).strip()
    if not error:
        parser.error("报错文本不能为空。")

    context = read_context() if args.context else {}
    explanation = None
    if is_enabled(os.environ):
        try:
            explanation = explain_llm(error, context, os.environ)
        except Exception:
            # 可选服务的配置、网络和响应错误均不能阻断本地模式。
            # 不打印异常内容，避免泄露密钥、请求内容或服务端响应。
            print("提示：LLM 调用失败，已回退到本地规则模式。", file=sys.stderr)
    if explanation is None:
        explanation = explain_local(error, context)
    print(explanation.render())
    return 0


def main(argv: list[str] | None = None) -> int:
    try:
        return _run(argv)
    except BrokenPipeError:
        # 下游提前关闭管道属于正常退出；丢弃尚未刷出的输出。
        try:
            sys.stdout.close()
        except OSError:
            pass
        return 0
    except KeyboardInterrupt:
        print("已取消。", file=sys.stderr)
        return 130
