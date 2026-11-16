"""CLI 输入、模式选择与 Profile 管理；不执行建议命令。"""

import argparse
import os
import sys

from . import __version__
from .context import read_context
from .llm import explain_llm
from .models import plain_text
from . import profiles
from .rules import explain_local


MAX_ERROR_CHARS = 16000


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="explainerr", description="用中文解释 CLI 报错；建议只打印，不执行。",
        epilog="管理模型配置：explainerr profile {add,list,remove,default}；详情：explainerr profile --help",
        add_help=False,
    )
    parser.add_argument("error", nargs="?", metavar="报错文本", help="省略时从 stdin 读取")
    parser.add_argument("--context", action="store_true", help="读取当前目录的四个白名单文件，每个最多 4000 字符")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--profile", metavar="别名", help="使用已保存的模型配置；无需设置环境变量开关")
    mode.add_argument("--local", action="store_true", help="强制使用本地规则，忽略环境变量和默认配置")
    parser.add_argument("-h", "--help", action="help", help="显示帮助并退出")
    parser.add_argument("--version", action="version", version=f"explainerr {__version__}")
    return parser


class _ProfileParser(argparse.ArgumentParser):
    def error(self, message):
        # argparse 默认会回显未知参数，可能包含用户误输入的密钥。
        self.print_usage(sys.stderr)
        self.exit(2, "错误：Profile 参数无效；请使用 explainerr profile --help 查看用法。\n")


def _manage_profiles(argv: list[str]) -> int:
    parser = _ProfileParser(prog="explainerr profile", description="管理 ~/.explainerr/config.json 中的模型配置。")
    commands = parser.add_subparsers(dest="action", required=True, title="配置命令")
    add = commands.add_parser("add", help="添加或更新配置")
    add.add_argument("name", metavar="别名")
    add.add_argument("--api-key", required=True, metavar="密钥")
    add.add_argument("--base-url", required=True, metavar="API根地址")
    add.add_argument("--model", required=True, metavar="模型名")
    commands.add_parser("list", help="列出配置，密钥脱敏")
    remove = commands.add_parser("remove", help="删除配置；删除默认配置时同时清除默认选择")
    remove.add_argument("name", metavar="别名")
    default = commands.add_parser("default", help="设置默认配置")
    default.add_argument("name", metavar="别名")
    args = parser.parse_args(argv)
    try:
        if args.action == "add":
            profiles.add_profile(args.name, args.api_key, args.base_url, args.model)
            print(f"已保存模型配置“{args.name}”。")
        elif args.action == "remove":
            profiles.remove_profile(args.name)
            print(f"已删除模型配置“{args.name}”；若它是默认配置，默认选择也已清除。")
        elif args.action == "default":
            profiles.set_default(args.name)
            print(f"已将“{args.name}”设为默认模型配置。")
        else:
            data = profiles.load_config()
            if not data["profiles"]:
                print("尚未保存模型配置；使用 profile add 添加。")
            else:
                print("别名\t默认\tbase-url\tmodel\tapi-key（脱敏）")
                for name, profile in sorted(data["profiles"].items()):
                    marker = "是" if name == data["default"] else "否"
                    print(f"{name}\t{marker}\t{profile['base_url']}\t{profile['model']}\t{profiles.mask_key(profile['api_key'])}")
        return 0
    except profiles.ProfileError as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 2


def _run(argv: list[str] | None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "profile":
        return _manage_profiles(argv[1:])
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
    llm_env = None
    if not args.local:
        try:
            llm_env = profiles.resolve_llm_env(args.profile, os.environ)
        except profiles.ProfileError as exc:
            print(f"提示：{exc} 已回退到本地规则模式。", file=sys.stderr)
    if llm_env is not None:
        try:
            explanation = explain_llm(error, context, llm_env)
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
