from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Optional

from ..scoring import Candidate


@dataclass
class InstallArtifact:
    """One file to write during install."""
    target_path: Path
    source_path: Optional[Path] = None   # Where to copy from (relative to repo root)
    inline_content: Optional[str] = None # Or, inline content to write
    executable: bool = False


@dataclass
class InstallPlan:
    """Everything an adapter needs to install for one tool."""
    artifacts: list[InstallArtifact] = field(default_factory=list)
    post_install_notes: list[str] = field(default_factory=list)


class Adapter:
    """Abstract adapter. Subclass and override the methods below."""

    name: str = ""              # Canonical tool name (e.g. "claude-code")
    display_name: str = ""      # Human-readable (e.g. "Claude Code")
    invocation_style: str = ""  # "/slash" | "@mention" | "$skill"

    # ── Detection ────────────────────────────────────────────────────────
    def detect(self) -> bool:
        """Is this tool installed on the current machine? Override per adapter."""
        raise NotImplementedError

    # ── Enumeration ──────────────────────────────────────────────────────
    def enumerate_candidates(self, keywords: Iterable[str], *,
                             scope: str = "all") -> list[Candidate]:
        """Find all routable candidates (skills/agents/rules) that match keywords."""
        raise NotImplementedError

    # ── Invocation formatting ────────────────────────────────────────────
    def format_invocation(self, candidate: Candidate, *,
                          task: str = "", prompt: str = "") -> str:
        """Return the exact text/command to invoke this candidate."""
        raise NotImplementedError

    # ── Install ──────────────────────────────────────────────────────────
    def install_plan(self, repo_root: Path, *, scope: str = "global") -> InstallPlan:
        """Return an InstallPlan: which files go where for this tool."""
        raise NotImplementedError

    # ── Default helpers (override only when needed) ──────────────────────
    def __repr__(self) -> str:
        return f"{type(self).__name__}({self.name!r})"
