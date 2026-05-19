from __future__ import annotations

import os
import re
import time
from pathlib import Path
from typing import Iterable

from .. import frontmatter
from ..scoring import Candidate
from .base import Adapter, InstallArtifact, InstallPlan


_INDEX_STALE_SECONDS = 7 * 24 * 60 * 60


class OpenCodeAdapter(Adapter):
    name = "opencode"
    display_name = "OpenCode"
    invocation_style = "/slash"

    def __init__(self, project_root: Path | None = None):
        self.project_root = project_root or Path.cwd()
        # XDG-style global
        xdg_config = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
        self.global_dir = xdg_config / "opencode"
        self.project_dir = self.project_root / ".opencode"
        self.repo_root = self._find_repo_root()

        # Agent paths
        self.agents_global = self.global_dir / "agents"
        self.agents_project = self.project_dir / "agents"

        self.skill_search_paths = [
            self.project_root / ".opencode" / "skills",
            self.project_root / ".claude" / "skills",
            self.project_root / ".agents" / "skills",
            self.repo_root / ".opencode" / "skills",
            self.repo_root / ".claude" / "skills",
            self.repo_root / ".agents" / "skills",
            self.global_dir / "skills",
            Path.home() / ".claude" / "skills",
            Path.home() / ".agents" / "skills",
        ]
        # Dedupe
        seen: set[str] = set()
        unique = []
        for p in self.skill_search_paths:
            key = str(p)
            if key in seen:
                continue
            seen.add(key)
            unique.append(p)
        self.skill_search_paths = unique

        # Commands
        self.commands_global = self.global_dir / "commands"
        self.commands_project = self.project_dir / "commands"

        self.index_file = self.global_dir / "router-index.tsv"

    # ── Detection ────────────────────────────────────────────────────────
    def detect(self) -> bool:
        if self.global_dir.exists() or self.project_dir.exists():
            return True
        return _which("opencode") is not None

    # ── Enumeration ──────────────────────────────────────────────────────
    def enumerate_candidates(self, keywords: Iterable[str], *,
                             scope: str = "all") -> list[Candidate]:
        keywords_lower = [k.lower() for k in keywords]
        candidates: list[Candidate] = []

        # Agents (read full. small pool)
        if scope in ("all", "global"):
            candidates.extend(self._read_agents(self.agents_global, "global"))
        if scope in ("all", "project"):
            candidates.extend(self._read_agents(self.agents_project, "project"))

        # Skills via index
        self._ensure_index_fresh()
        if self.index_file.exists():
            candidates.extend(_filter_index(self.index_file, keywords_lower))

        return candidates

    def _read_agents(self, dir_path: Path, scope: str) -> list[Candidate]:
        if not dir_path.is_dir():
            return []
        out: list[Candidate] = []
        for f in sorted(dir_path.glob("*.md")):
            fm = frontmatter.parse_file(f)
            name = fm.get("name") or f.stem
            desc = (fm.get("description") or "").strip()
            tools = fm.get("permission") or fm.get("tools") or []
            if isinstance(tools, str):
                tools = [t.strip() for t in re.split(r"[,\s]+", tools) if t.strip()]
            out.append(Candidate(
                name=name, kind="subagent", description=desc,
                tools=list(tools), path=str(f), source=scope,
            ))
        return out

    def _ensure_index_fresh(self, force: bool = False) -> None:
        stale = (
            force
            or not self.index_file.exists()
            or (time.time() - self.index_file.stat().st_mtime) > _INDEX_STALE_SECONDS
        )
        if not stale:
            return
        self._build_index()

    def _build_index(self) -> None:
        lines: list[str] = []
        seen_names: set[str] = set()
        for search_path in self.skill_search_paths:
            if not search_path.is_dir():
                continue
            for d in sorted(search_path.iterdir()):
                if not d.is_dir():
                    continue
                skill_md = d / "SKILL.md"
                if not skill_md.is_file():
                    continue
                fm = frontmatter.parse_file(skill_md)
                name = fm.get("name") or d.name
                if not name or name in seen_names:
                    continue
                seen_names.add(name)
                desc = re.sub(r"\s+", " ", (fm.get("description") or "").strip())[:300]
                scope = _scope_for(search_path)
                lines.append(f"skill\t{name}\t{scope}\t{desc}\t\t{skill_md}")
        self.index_file.parent.mkdir(parents=True, exist_ok=True)
        self.index_file.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def _find_repo_root(self) -> Path:
        cwd = self.project_root
        while True:
            if (cwd / ".git").exists():
                return cwd
            if cwd.parent == cwd:
                return self.project_root
            cwd = cwd.parent

    # ── Invocation formatting ────────────────────────────────────────────
    def format_invocation(self, candidate: Candidate, *,
                          task: str = "", prompt: str = "") -> str:
        if candidate.kind == "skill":
            return f"/{candidate.name}"
        if candidate.kind == "subagent":
            return f"@{candidate.name}"
        return f"# unsupported candidate kind: {candidate.kind}"

    # ── Install ──────────────────────────────────────────────────────────
    def install_plan(self, repo_root: Path, *, scope: str = "global") -> InstallPlan:
        targets = repo_root / "targets" / "opencode"
        if scope == "global":
            base = self.global_dir
        else:
            base = self.project_dir
        artifacts = [
            InstallArtifact(
                target_path=base / "commands" / "route.md",
                source_path=targets / "commands" / "route.md",
            ),
            InstallArtifact(
                target_path=base / "agents" / "agent-router.md",
                source_path=targets / "agents" / "agent-router.md",
            ),
        ]
        return InstallPlan(
            artifacts=artifacts,
            post_install_notes=[
                "Invoke with /route <task> in OpenCode TUI.",
                "Or @agent-router from another agent for self-routing.",
                "OpenCode reads .claude/skills/ and .agents/skills/ as fallbacks. "
                "your existing skill library works.",
            ],
        )


def _scope_for(path: Path) -> str:
    s = str(path)
    if str(Path.home()) in s:
        return "global"
    return "project"


def _filter_index(index_file: Path, keywords_lower: list[str]) -> list[Candidate]:
    if not keywords_lower:
        return []
    out: list[Candidate] = []
    with index_file.open("r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            parts = line.rstrip("\n").split("\t")
            if len(parts) < 6 or parts[0] != "skill":
                continue
            _, name, scope, desc, tools_raw, path = parts[:6]
            hay = (name + " " + desc).lower()
            if not any(kw in hay for kw in keywords_lower):
                continue
            out.append(Candidate(
                name=name, kind="skill", description=desc,
                path=path, source=scope,
            ))
    return out


def _which(cmd: str) -> str | None:
    for path in os.environ.get("PATH", "").split(os.pathsep):
        full = Path(path) / cmd
        if full.is_file() and os.access(full, os.X_OK):
            return str(full)
    return None
