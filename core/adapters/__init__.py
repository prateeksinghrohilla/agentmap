from .base import Adapter, Candidate, InstallPlan
from .claude_code import ClaudeCodeAdapter
from .cursor import CursorAdapter
from .codex import CodexAdapter
from .opencode import OpenCodeAdapter
from .gemini import GeminiAdapter

ALL: list[type[Adapter]] = [
    ClaudeCodeAdapter,
    CursorAdapter,
    CodexAdapter,
    OpenCodeAdapter,
    GeminiAdapter,
]


def get(name: str) -> Adapter:
    """Look up an adapter by its canonical name. Raises KeyError if unknown."""
    for cls in ALL:
        if cls.name == name:
            return cls()
    raise KeyError(f"Unknown adapter: {name}. Available: {[c.name for c in ALL]}")


def detect_installed() -> list[Adapter]:
    """Return a list of adapters for tools detected as installed on this machine."""
    return [cls() for cls in ALL if cls().detect()]


__all__ = [
    "Adapter", "Candidate", "InstallPlan", "ALL", "get", "detect_installed",
    "ClaudeCodeAdapter", "CursorAdapter", "CodexAdapter",
    "OpenCodeAdapter", "GeminiAdapter",
]
