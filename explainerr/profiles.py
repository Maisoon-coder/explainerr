"""用户目录下的模型配置存档；不输出密钥或底层异常内容。"""

from collections.abc import Mapping
import json
import os
from pathlib import Path
import re
import tempfile
import unicodedata

from .llm import is_enabled, validate_base_url


MAX_CONFIG_BYTES = 1024 * 1024


class ProfileError(Exception):
    """可以安全显示给用户的配置错误。"""


def config_path() -> Path:
    return Path.home() / ".explainerr" / "config.json"


def validate_name(name: str) -> str:
    if not isinstance(name, str) or not re.fullmatch(r"\w[\w.-]{0,63}", name):
        raise ProfileError("配置别名须为 1 至 64 个字母、数字、下划线、点或连字符，且以字母、数字或下划线开头。")
    return name


def _text(value: object) -> str:
    if (not isinstance(value, str) or not value.strip() or len(value) > 4096
            or any(char.isspace() for char in value.strip())
            or any(unicodedata.category(char) in {"Cc", "Cf", "Cs"} for char in value)):
        raise ProfileError("密钥、API 根地址和模型名必须是非空文本，不能包含空白或控制字符。")
    return value.strip()


def _profile(api_key: object, base_url: object, model: object) -> dict[str, str]:
    key, url, model_name = _text(api_key), _text(base_url), _text(model)
    try:
        url = validate_base_url(url)
    except ValueError:
        raise ProfileError("API 根地址无效；请填写不含认证信息、查询参数和片段的 HTTP(S) 根地址。") from None
    return {"api_key": key, "base_url": url, "model": model_name}


def _validate(data: object) -> dict:
    if not isinstance(data, dict) or not isinstance(data.get("profiles"), dict):
        raise ValueError("配置结构错误")
    profiles = {}
    for name, entry in data["profiles"].items():
        validate_name(name)
        if not isinstance(entry, dict):
            raise ValueError("配置条目错误")
        profiles[name] = _profile(entry["api_key"], entry["base_url"], entry["model"])
    default = data.get("default")
    if default is not None and (not isinstance(default, str) or default not in profiles):
        raise ValueError("默认配置不存在")
    return {"default": default, "profiles": profiles}


def load_config() -> dict:
    try:
        with config_path().open("rb") as handle:
            raw = handle.read(MAX_CONFIG_BYTES + 1)
    except FileNotFoundError:
        return {"default": None, "profiles": {}}
    except (OSError, RuntimeError):
        raise ProfileError("无法读取 ~/.explainerr/config.json；请检查目录和文件权限。") from None
    try:
        if len(raw) > MAX_CONFIG_BYTES:
            raise ValueError("配置过大")
        return _validate(json.loads(raw.decode("utf-8-sig")))
    except (ValueError, KeyError, TypeError, RecursionError, ProfileError):
        raise ProfileError("~/.explainerr/config.json 已损坏或格式不正确；请移走损坏文件后用 profile add 重新创建。") from None


def save_config(data: dict) -> None:
    """先写同目录临时文件再原子替换；失败时保留原配置。"""
    temporary = None
    try:
        payload = (json.dumps(_validate(data), ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        if len(payload) > MAX_CONFIG_BYTES:
            raise ProfileError("配置文件过大；请减少保存的配置。")
        path = config_path()
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        fd, name = tempfile.mkstemp(prefix=".config-", suffix=".tmp", dir=path.parent)
        temporary = Path(name)
        # mkstemp 在 POSIX 上以 0600 创建；Windows 使用用户目录的 ACL。
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except (OSError, RuntimeError):
        raise ProfileError("无法保存 ~/.explainerr/config.json；请检查目录权限和磁盘空间，原配置未被主动清空。") from None
    finally:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass


def add_profile(name: str, api_key: str, base_url: str, model: str) -> None:
    name = validate_name(name)
    profile = _profile(api_key, base_url, model)
    data = load_config()
    data["profiles"][name] = profile
    save_config(data)


def _require(data: dict, name: str) -> dict[str, str]:
    validate_name(name)
    if name not in data["profiles"]:
        raise ProfileError(f"未找到模型配置“{name}”；请用 profile list 查看，或用 profile add 添加。")
    return data["profiles"][name]


def remove_profile(name: str) -> None:
    data = load_config()
    _require(data, name)
    del data["profiles"][name]
    if data["default"] == name:
        data["default"] = None
    save_config(data)


def set_default(name: str) -> None:
    data = load_config()
    _require(data, name)
    data["default"] = name
    save_config(data)


def mask_key(key: str) -> str:
    # 短密钥不能因首尾重叠而被完整显示。
    return key[:4] + "…" + key[-4:] if len(key) > 8 else "****"


def resolve_llm_env(name: str | None, env: Mapping[str, str]) -> dict[str, str] | None:
    """显式 Profile > 已启用的环境变量 > 默认 Profile > 本地。"""
    if name is None and is_enabled(env):
        return dict(env)
    data = load_config()
    selected = name if name is not None else data["default"]
    if selected is None:
        return None
    profile = _require(data, selected)
    result = {
        "OPENAI_API_KEY": profile["api_key"], "OPENAI_BASE_URL": profile["base_url"],
        "OPENAI_MODEL": profile["model"], "EXPLAINERR_USE_LLM": "1",
    }
    if "EXPLAINERR_TIMEOUT" in env:
        result["EXPLAINERR_TIMEOUT"] = env["EXPLAINERR_TIMEOUT"]
    return result
