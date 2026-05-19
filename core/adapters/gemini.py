from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Iterable

from .. import frontmatter
from ..scoring import Candidate
from .base import Adapter, InstallArtifact, InstallPlan


class GeminiAdapter(Adapter):
    name = "gemini-cli"
    display_name = "Gemini CLI"
    invocation_style = "@mention"

    def __init__(self, project_root: Path | None = None):
        self.project_root = project_root or Path.cwd()
        self.gemini_home = Path(os.environ.get("GEMINI_HOME", Path.home() / ".gemini"))
        self.agents_global = self.gemini_home / "agents"
        self.agents_project = self.project_root / ".gemini" / "agents"

    # ── Detection ────────────────────────────────────────────────────────
    def detect(self) -> bool:
        if self.gemini_home.exists():
            return True
        return _which("gemini") is not None

    # ── Enumeration ──────────────────────────────────────────────────────
    def enumerate_candidates(self, keywords: Iterable[str], *,
                             scope: str = "all") -> list[Candidate]:
        keywords_lower = [k.lower() for k in keywords]
        out: list[Candidate] = []
        if scope in ("all", "global"):
            out.extend(self._read_agents(self.agents_global, "global"))
        if scope in ("all", "project"):
            out.extend(self._read_agents(self.agents_project, "project"))
        if keywords_lower:
            out = [
                c for c in out
                if any(kw in (c.name + " " + c.description).lower() for kw in keywords_lower)
            ]
        return out

    def _read_agents(self, dir_path: Path, scope: str) -> list[Candidate]:
        if not dir_path.is_dir():
            return []
        out: list[Candidate] = []
        for f in sorted(dir_path.glob("*.md")):
            fm = frontmatter.parse_file(f)
            name = fm.get("name") or f.stem
            desc = (fm.get("description") or "").strip()
            tools = fm.get("tools") or []
            if isinstance(tools, str):
                tools = [t.strip() for t in re.split(r"[,\s]+", tools) if t.strip()]
            out.append(Candidate(
                name=name, kind="subagent", description=desc,
                tools=list(tools), path=str(f), source=scope,
            ))
        return out

    # ── Invocation formatting ────────────────────────────────────────────
    def format_invocation(self, candidate: Candidate, *,
                          task: str = "", prompt: str = "") -> str:
        return f"@{candidate.name} {task}".strip()

    # ── Install ──────────────────────────────────────────────────────────
    def install_plan(self, repo_root: Path, *, scope: str = "global") -> InstallPlan:
        targets = repo_root / "targets" / "gemini-cli"
        if scope == "global":
            base = self.gemini_home / "agents"
        else:
            base = self.project_root / ".gemini" / "agents"
        artifacts = [
            InstallArtifact(
                target_path=base / "agent-router.md",
                source_path=targets / "agents" / "agent-router.md",
            ),
        ]
        return InstallPlan(
            artifacts=artifacts,
            post_install_notes=[
                "Invoke with @agent-router <task> in Gemini CLI chat.",
                "Gemini CLI has no on-disk slash commands. @mention is the only invocation.",
                "Restart Gemini CLI to load the new subagent.",
            ],
        )


def _which(cmd: str) -> str | None:
    for path in os.environ.get("PATH", "").split(os.pathsep):
        full = Path(path) / cmd
        if full.is_file() and os.access(full, os.X_OK):
            return str(full)
    return None
