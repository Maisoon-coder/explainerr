"""按具体程度匹配常见报错；所有命令均为输出文本。"""

import json
import os
import re
from collections.abc import Mapping

from .models import Explanation, plain_text


def _script_context(context: Mapping[str, str]) -> str | None:
    try:
        package = json.loads(context.get("package.json", "{}"))
        scripts = package.get("scripts", {}) if isinstance(package, dict) else {}
        if not isinstance(scripts, dict):
            return None
        names = [name for name in scripts if re.fullmatch(r"[\w:.-]{1,64}", name)][:8]
        if names:
            return "检查脚本名；当前 package.json 包含：" + "、".join(names)
    except (ValueError, TypeError):
        pass  # 截断或不合法的 JSON 不影响本地解释。
    return None


def explain_local(error: str, context: Mapping[str, str] | None = None) -> Explanation:
    text = plain_text(error)
    context = context or {}

    if re.search(r"missing script\s*:", text, re.I):
        return Explanation(
            "当前项目没有定义你要运行的 npm 脚本。",
            ("package.json 的 scripts 中缺少该名称，或名称拼写不一致。",
             "命令在错误的目录或工作区中执行。"),
            ("npm run", _script_context(context) or "检查 package.json 的 scripts 字段。",
             "检查当前目录是否为目标项目根目录。"),
        )

    if re.search(r"No module named\s+[\"']?", text, re.I):
        match = re.search(r"No module named\s+[\"']?([A-Za-z_][\w.]*)", text, re.I)
        module = match.group(1) if match else "所需模块"
        return Explanation(
            f"当前 Python 环境找不到模块 {module}。",
            ("依赖未安装在运行程序所用的 Python 环境中。",
             "虚拟环境未激活，或 pip 与 Python 指向不同环境。",
             "本地模块名、运行目录或导入路径不正确。"),
            ('python -c "import sys; print(sys.executable)"',
             "python -m pip --version",
             "检查 pyproject.toml / requirements.txt 中的依赖与导入路径；模块名不一定等于安装包名。"),
        )

    if re.search(r"cannot import name", text, re.I):
        return Explanation(
            "Python 找到了模块，但无法导入指定名称。",
            ("依赖版本不匹配，该名称已变更或不存在。", "模块之间存在循环导入。",
             "同名本地文件遮蔽了预期的依赖模块。"),
            ("检查 traceback 中模块的实际文件路径。", "检查依赖版本和该版本的导出名称。",
             "检查导入链是否形成循环。"),
        )

    if re.search(r"cannot find (?:module|package)|ERR_MODULE_NOT_FOUND|MODULE_NOT_FOUND|module not found", text, re.I):
        return Explanation(
            "Node 或构建工具无法解析所需模块。",
            ("项目依赖尚未安装，或安装目录不对应当前项目。",
             "导入路径、文件名大小写或文件扩展名不正确。",
             "依赖未声明，或当前版本没有导出所需入口。"),
            ("检查 package.json、锁文件和项目约定的包管理器。",
             "检查缺失模块是第三方依赖还是本地相对路径。",
             "检查当前项目的依赖安装状态，以及导入路径和包的 exports 配置。"),
        )

    if re.search(r"EADDRINUSE|address already in use|port\b.*\balready in use|WinError 10048", text, re.I):
        match = re.search(r"(?::|\bport\s+)(\d{1,5})(?!\d)", text, re.I)
        port = int(match.group(1)) if match else None
        if port is not None and not 1 <= port <= 65535:
            port = None
        command = "netstat -ano" if os.name == "nt" else (
            f"lsof -nP -iTCP{':' + str(port) if port else ''} -sTCP:LISTEN"
        )
        return Explanation(
            f"端口{(' ' + str(port) + ' ') if port else ''}已被占用，服务无法绑定该地址。",
            ("同一服务已启动，或上次启动的进程仍在运行。", "其他程序正在使用相同端口。"),
            (command, "检查监听进程的 PID 和用途，确认是否为重复启动的服务。",
             "检查服务的端口配置，选择空闲端口后再启动。"),
        )

    if re.search(r"permission denied|EACCES|EPERM|access is denied|WinError 5\b", text, re.I):
        return Explanation(
            "当前进程没有完成该操作所需的权限。",
            ("当前用户没有目标文件或目录的访问权限。", "文件缺少执行权限，或被其他进程锁定。",
             "操作涉及受保护的目录或端口。"),
            ("检查报错中的目标路径、文件所有者和访问权限。", "检查目标文件是否被其他进程占用。",
             "检查是否可以使用当前用户可写的目录或普通端口。"),
        )

    if re.search(r"command not found|is not recognized as an internal or external command|is not recognized as (?:the name of )?a cmdlet|CommandNotFoundException|不是内部或外部命令", text, re.I):
        return Explanation(
            "终端找不到要执行的命令。",
            ("命令对应的工具尚未安装。", "工具的可执行目录没有加入当前终端的 PATH。",
             "命令拼写错误，或所需虚拟环境尚未激活。"),
            ("检查命令拼写及工具是否已安装。", "检查当前终端的 PATH 是否包含工具所在目录。",
             "检查项目要求的虚拟环境或运行时是否已启用。"),
        )

    return Explanation(
        "现有本地规则无法确定这条报错的具体原因。",
        ("日志信息不足，或报错类型尚未覆盖。", "实际原因可能出现在这条报错之前。"),
        ("检查完整日志中的第一条错误及其前后文。", "检查触发错误的命令、当前目录和运行时版本。",
         "检查项目 README 中的安装和启动要求。"),
    )
