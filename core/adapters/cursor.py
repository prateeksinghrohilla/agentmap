from __future__ import annotations

import os
from pathlib import Path
from typing import Iterable

from .. import frontmatter
from ..scoring import Candidate
from .base import Adapter, InstallArtifact, InstallPlan


class CursorAdapter(Adapter):
    name = "cursor"
    display_name = "Cursor"
    invocation_style = "@mention"

    def __init__(self, project_root: Path | None = None):
        self.project_root = project_root or Path.cwd()
        self.rules_dir = self.project_root / ".cursor" / "rules"

    # ── Detection ────────────────────────────────────────────────────────
    def detect(self) -> bool:
        """Detected if the project has a .cursor/ directory anywhere up the tree."""
        cwd = self.project_root
        while True:
            if (cwd / ".cursor").is_dir():
                return True
            if cwd.parent == cwd:
                return False
            cwd = cwd.parent

    # ── Enumeration ──────────────────────────────────────────────────────
    def enumerate_candidates(self, keywords: Iterable[str], *,
                             scope: str = "all") -> list[Candidate]:
        keywords_lower = [k.lower() for k in keywords]
        rules_root = self._find_rules_root()
        if rules_root is None:
            return []
        out: list[Candidate] = []
        for f in rules_root.rglob("*"):
            if not f.is_file() or f.suffix not in (".mdc", ".md"):
                continue
            fm = frontmatter.parse_file(f)
            name = f.stem
            desc = (fm.get("description") or "").strip()
            rule_type = _classify_rule_type(fm)
            # Always-rules attach automatically; Auto-Attached are file-driven.
            if rule_type not in ("manual", "agent-requested"):
                continue
            hay = (name + " " + desc).lower()
            if keywords_lower and not any(kw in hay for kw in keywords_lower):
                continue
            out.append(Candidate(
                name=name, kind="rule", description=desc,
                path=str(f), source=rule_type,
            ))
        return out

    def _find_rules_root(self) -> Path | None:
        """Walk up from project_root looking for .cursor/rules/."""
        cwd = self.project_root
        while True:
            cand = cwd / ".cursor" / "rules"
            if cand.is_dir():
                return cand
            if cwd.parent == cwd:
                return None
            cwd = cwd.parent

    # ── Invocation formatting ────────────────────────────────────────────
    def format_invocation(self, candidate: Candidate, *,
                          task: str = "", prompt: str = "") -> str:
        return f"@{candidate.name}"

    # ── Install ──────────────────────────────────────────────────────────
    def install_plan(self, repo_root: Path, *, scope: str = "global") -> InstallPlan:
        if scope == "global":
            return InstallPlan(
                artifacts=[],
                post_install_notes=[
                    "Cursor has no global rules directory on disk.",
                    "Install per-project: bash install.sh --target=cursor --project",
                    "Or paste the rule body into Cursor Settings → Rules (User Rules).",
                ],
            )

        targets = repo_root / "targets" / "cursor"
        rules_root = self.rules_dir
        artifacts = [
            InstallArtifact(
                target_path=rules_root / "route.mdc",
                source_path=targets / "rules" / "route.mdc",
            ),
        ]
        return InstallPlan(
            artifacts=artifacts,
            post_install_notes=[
                "Invoke with @route <task> in Cursor chat.",
                "Cursor will not auto-trigger the rule. it's set as Manual type.",
                "For Always-on routing, edit frontmatter to alwaysApply: true (not recommended).",
            ],
        )


def _classify_rule_type(fm: frontmatter.Frontmatter) -> str:
    """Return one of: 'always' | 'auto-attached' | 'agent-requested' | 'manual'."""
    always = fm.get("alwaysApply")
    if always is True or str(always).lower() == "true":
        return "always"
    globs = fm.get("globs")
    desc = fm.get("description")
    if globs:
        return "auto-attached"
    if desc:
        return "agent-requested"
    return "manual"
