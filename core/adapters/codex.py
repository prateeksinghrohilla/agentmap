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


class CodexAdapter(Adapter):
    name = "codex"
    display_name = "Codex CLI"
    invocation_style = "$skill"

    def __init__(self, project_root: Path | None = None):
        self.project_root = project_root or Path.cwd()
        self.codex_home = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))
        # Skill search paths in resolution order
        self.skill_search_paths = [
            self.project_root / ".agents" / "skills",
            self._find_repo_root() / ".agents" / "skills",
            Path.home() / ".agents" / "skills",
            Path("/etc/codex/skills"),
        ]
        # Dedupe while preserving order
        seen: set[str] = set()
        unique = []
        for p in self.skill_search_paths:
            key = str(p)
            if key in seen:
                continue
            seen.add(key)
            unique.append(p)
        self.skill_search_paths = unique
        self.index_file = self.codex_home / "router-index.tsv"

    # ── Detection ────────────────────────────────────────────────────────
    def detect(self) -> bool:
        if self.codex_home.exists():
            return True
        return _which("codex") is not None

    # ── Enumeration ──────────────────────────────────────────────────────
    def enumerate_candidates(self, keywords: Iterable[str], *,
                             scope: str = "all") -> list[Candidate]:
        keywords_lower = [k.lower() for k in keywords]
        self._ensure_index_fresh()
        if not self.index_file.exists():
            return []
        return _filter_index(self.index_file, keywords_lower)

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
            return f"${candidate.name}"
        return f"# Codex has no on-disk subagent format. handle inline."

    # ── Install ──────────────────────────────────────────────────────────
    def install_plan(self, repo_root: Path, *, scope: str = "global") -> InstallPlan:
        targets = repo_root / "targets" / "codex"
        if scope == "global":
            base = Path.home() / ".agents" / "skills" / "route"
        else:
            base = self.project_root / ".agents" / "skills" / "route"
        artifacts = [
            InstallArtifact(
                target_path=base / "SKILL.md",
                source_path=targets / "skills" / "route" / "SKILL.md",
            ),
        ]
        return InstallPlan(
            artifacts=artifacts,
            post_install_notes=[
                "Invoke with $route in the Codex CLI composer.",
                "Skills load on session start. restart Codex if you don't see it.",
                "This skill location (.agents/skills/) is shared with OpenCode.",
            ],
        )


def _scope_for(path: Path) -> str:
    s = str(path)
    if "/.agents/" in s and str(Path.home()) in s:
        return "global"
    if "/etc/" in s:
        return "system"
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
