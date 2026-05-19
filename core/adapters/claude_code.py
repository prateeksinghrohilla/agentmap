from __future__ import annotations

import os
import re
import time
from pathlib import Path
from typing import Iterable

from .. import frontmatter
from ..scoring import Candidate
from .base import Adapter, InstallArtifact, InstallPlan


_INDEX_STALE_SECONDS = 7 * 24 * 60 * 60   # 7 days


class ClaudeCodeAdapter(Adapter):
    name = "claude-code"
    display_name = "Claude Code"
    invocation_style = "/slash"

    def __init__(self,
                 home: Path | None = None,
                 project_root: Path | None = None,
                 skills_dir: Path | None = None):
        self.home = home or Path(os.environ.get("CLAUDE_HOME", Path.home() / ".claude"))
        self.project_root = project_root or Path.cwd()
        self.skills_dir = skills_dir or Path(
            os.environ.get("CLAUDE_SKILLS_DIR", self.home / "skills")
        )
        self.agents_dir_global = self.home / "agents"
        self.agents_dir_project = self.project_root / ".claude" / "agents"
        self.commands_dir = self.home / "commands"
        self.scripts_dir = self.home / "scripts"
        self.index_file = self.home / "router-index.tsv"

    # ── Detection ────────────────────────────────────────────────────────
    def detect(self) -> bool:
        return self.home.exists()

    # ── Enumeration ──────────────────────────────────────────────────────
    def enumerate_candidates(self, keywords: Iterable[str], *,
                             scope: str = "all") -> list[Candidate]:
        keywords_lower = [k.lower() for k in keywords]
        candidates: list[Candidate] = []

        if scope in ("all", "global"):
            candidates.extend(self._read_agents(self.agents_dir_global, "global"))
        if scope in ("all", "project"):
            candidates.extend(self._read_agents(self.agents_dir_project, "project"))

        # Skills. use cached index (potentially thousands)
        candidates.extend(self._enumerate_skills(keywords_lower))

        return candidates

    def _read_agents(self, dir_path: Path, scope: str) -> list[Candidate]:
        if not dir_path.is_dir():
            return []
        out: list[Candidate] = []
        for f in sorted(dir_path.glob("*.md")):
            fm = frontmatter.parse_file(f)
            name = fm.get("name") or f.stem
            desc = fm.get("description") or ""
            tools = fm.get("tools") or []
            if isinstance(tools, str):
                tools = [t.strip() for t in re.split(r"[,\s]+", tools) if t.strip()]
            out.append(Candidate(
                name=name, kind="subagent", description=desc,
                tools=list(tools), path=str(f), source=scope,
            ))
        return out

    def _enumerate_skills(self, keywords_lower: list[str]) -> list[Candidate]:
        if not self.skills_dir.is_dir():
            return []
        self._ensure_index_fresh()
        if not self.index_file.exists():
            return []
        return _filter_index(self.index_file, keywords_lower, kind="skill")

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
        """Walk skills_dir, parse each SKILL.md frontmatter, write to index TSV."""
        lines: list[str] = []
        for d in self.skills_dir.iterdir():
            if not d.is_dir():
                continue
            skill_md = d / "SKILL.md"
            if not skill_md.is_file():
                continue
            fm = frontmatter.parse_file(skill_md)
            name = fm.get("name") or d.name
            desc = (fm.get("description") or "").strip()
            if not name:
                continue
            # Truncate description, strip tabs/newlines
            desc = re.sub(r"\s+", " ", desc)[:300]
            lines.append(f"skill\t{name}\tglobal\t{desc}\t\t{skill_md}")
        self.index_file.parent.mkdir(parents=True, exist_ok=True)
        self.index_file.write_text("\n".join(lines) + "\n", encoding="utf-8")

    # ── Invocation formatting ────────────────────────────────────────────
    def format_invocation(self, candidate: Candidate, *,
                          task: str = "", prompt: str = "") -> str:
        if candidate.kind == "skill":
            return f"/{candidate.name}"
        if candidate.kind == "subagent":
            sample_prompt = prompt or task or "<task description>"
            sample_prompt = sample_prompt.replace('"', '\\"')
            return (
                'Agent({\n'
                f'  subagent_type: "{candidate.name}",\n'
                f'  description: "{(task or "Delegated task")[:60]}",\n'
                f'  prompt: "{sample_prompt}"\n'
                '})'
            )
        return f"# unsupported candidate kind: {candidate.kind}"

    # ── Install ──────────────────────────────────────────────────────────
    def install_plan(self, repo_root: Path, *, scope: str = "global") -> InstallPlan:
        targets_dir = repo_root / "targets" / "claude-code"
        out = self.home if scope == "global" else self.project_root / ".claude"

        artifacts = [
            InstallArtifact(
                target_path=out / "commands" / "route.md",
                source_path=targets_dir / "commands" / "route.md",
            ),
            InstallArtifact(
                target_path=out / "agents" / "agent-router.md",
                source_path=targets_dir / "agents" / "agent-router.md",
            ),
            InstallArtifact(
                target_path=out / "scripts" / "list-skills.sh",
                source_path=targets_dir / "scripts" / "list-skills.sh",
                executable=True,
            ),
            InstallArtifact(
                target_path=out / "scripts" / "list-agents.sh",
                source_path=targets_dir / "scripts" / "list-agents.sh",
                executable=True,
            ),
        ]
        return InstallPlan(
            artifacts=artifacts,
            post_install_notes=[
                "Restart Claude Code so /route and agent-router load.",
                "Try: /route <any task description>",
            ],
        )


def _filter_index(index_file: Path, keywords_lower: list[str], *,
                  kind: str) -> list[Candidate]:
    """Stream the index TSV and return candidates whose desc/name matches keywords."""
    if not keywords_lower:
        return []
    out: list[Candidate] = []
    with index_file.open("r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            parts = line.rstrip("\n").split("\t")
            if len(parts) < 6 or parts[0] != kind:
                continue
            _, name, scope, desc, tools_raw, path = parts[:6]
            hay = (name + " " + desc).lower()
            if not any(kw in hay for kw in keywords_lower):
                continue
            tools = [t for t in tools_raw.split(",") if t]
            out.append(Candidate(
                name=name, kind=kind, description=desc,
                tools=tools, path=path, source=scope,
            ))
    return out
