"""本地规则和 LLM 共用的输出约束。"""

from dataclasses import dataclass
import re
import unicodedata


_ANSI = re.compile(r"\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)|\x1b\[[0-?]*[ -/]*[@-~]")


def plain_text(value: str) -> str:
    """移除终端转义和不可见控制字符，保留日志换行。"""
    value = _ANSI.sub("", value)
    return "".join(
        char for char in value
        if char in "\n\r\t" or unicodedata.category(char) not in {"Cc", "Cf", "Cs"}
    )


def _line(value: str) -> str:
    if not isinstance(value, str):
        raise ValueError("输出条目必须是文本")
    result = " ".join(plain_text(value).split())[:500]
    if not result:
        raise ValueError("输出条目不能为空")
    return result


@dataclass(frozen=True)
class Explanation:
    conclusion: str
    causes: tuple[str, ...]
    next_steps: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "conclusion", _line(self.conclusion))
        for field in ("causes", "next_steps"):
            items = getattr(self, field)
            if not isinstance(items, (list, tuple)) or not items:
                raise ValueError("原因和建议必须是非空列表")
            object.__setattr__(self, field, tuple(_line(item) for item in items[:3]))

    @classmethod
    def from_mapping(cls, data: object) -> "Explanation":
        if not isinstance(data, dict):
            raise ValueError("解释必须是 JSON 对象")
        return cls(data["conclusion"], data["causes"], data["next_steps"])

    def render(self) -> str:
        return "\n".join([
            f"一句话结论：{self.conclusion}",
            "可能原因：",
            *(f"- {item}" for item in self.causes),
            "下一步建议：",
            *(f"- {item}" for item in self.next_steps),
        ])
