from __future__ import annotations

import json
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import Optional

from . import adapters
from .scoring import (
    Candidate, Score, extract_keywords, extract_verbs, score_candidate, rank,
)


_MIN_SCORE_FOR_DELEGATION = 4.5    # below this we recommend DIRECT
_ORCHESTRATE_GAP = 1.5             # if top-3 candidates all score within this gap
_TOP_N = 6                         # how many candidates to keep in the verdict


@dataclass
class ScoredCandidate:
    candidate: Candidate
    score: Score

    def to_dict(self) -> dict:
        return {
            "name": self.candidate.name,
            "kind": self.candidate.kind,
            "description": self.candidate.description,
            "tools": self.candidate.tools,
            "source": self.candidate.source,
            "path": self.candidate.path,
            "score": {
                "total": round(self.score.total, 2),
                "domain_match": self.score.domain_match,
                "verb_match": self.score.verb_match,
                "negative_signals": self.score.negative_signals,
                "tool_sufficiency": self.score.tool_sufficiency,
                "mechanism_bonus": self.score.mechanism_bonus,
            },
            "explanation": self.score.explanation,
        }


@dataclass
class Verdict:
    """The router's recommendation for one task."""
    task: str
    tool: str
    keywords: list[str]
    verbs: list[str]
    mechanism: str               # "skill" | "subagent" | "direct" | "orchestrate"
    primary: Optional[ScoredCandidate]
    runner_up: Optional[ScoredCandidate]
    orchestrate_steps: list[ScoredCandidate] = field(default_factory=list)
    invocation: str = ""
    reason: str = ""
    all_scored: list[ScoredCandidate] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "task": self.task,
            "tool": self.tool,
            "keywords": self.keywords,
            "verbs": self.verbs,
            "mechanism": self.mechanism,
            "primary": self.primary.to_dict() if self.primary else None,
            "runner_up": self.runner_up.to_dict() if self.runner_up else None,
            "orchestrate_steps": [s.to_dict() for s in self.orchestrate_steps],
            "invocation": self.invocation,
            "reason": self.reason,
            "all_scored": [s.to_dict() for s in self.all_scored],
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent)


def route(task: str, *,
          target: Optional[str] = None,
          project_root: Optional[Path] = None,
          top_n: int = _TOP_N) -> Verdict:
    """Main entry point. Route a task and return a Verdict."""
    adapter = _resolve_adapter(target, project_root)
    keywords = extract_keywords(task)
    verbs = extract_verbs(task)

    raw_candidates = adapter.enumerate_candidates(keywords)

    scored = [
        ScoredCandidate(candidate=c, score=score_candidate(c, task, keywords, verbs))
        for c in raw_candidates
    ]
    scored.sort(key=lambda sc: sc.score.total, reverse=True)
    top = scored[:top_n]

    mechanism, reason = _pick_mechanism(task, top)
    primary, runner_up, steps = _pick_winners(top, mechanism)

    invocation = ""
    if primary is not None:
        invocation = adapter.format_invocation(
            primary.candidate, task=task, prompt=task,
        )

    return Verdict(
        task=task,
        tool=adapter.name,
        keywords=keywords,
        verbs=sorted(verbs),
        mechanism=mechanism,
        primary=primary,
        runner_up=runner_up,
        orchestrate_steps=steps,
        invocation=invocation,
        reason=reason,
        all_scored=top,
    )


def _resolve_adapter(target: Optional[str], project_root: Optional[Path]):
    """Pick the adapter: explicit > autodetect > Claude Code default."""
    if target:
        return adapters.get(target)
    installed = adapters.detect_installed()
    if not installed:
        return adapters.get("claude-code")
    return installed[0]


def _pick_mechanism(task: str, top: list[ScoredCandidate]) -> tuple[str, str]:
    """Pick one of: skill | subagent | direct | orchestrate."""
    task_lower = task.lower()
    # Heuristic 1: trivial task → DIRECT
    if _looks_trivial(task_lower):
        return "direct", "Single-file or trivial operation. delegating costs more tokens than the work."

    if not top:
        return "direct", "No candidates found; handle inline."

    best = top[0]
    if best.score.total < _MIN_SCORE_FOR_DELEGATION:
        return "direct", (
            f"No candidate scored above the delegation threshold "
            f"({_MIN_SCORE_FOR_DELEGATION}). Top score was {best.score.total:.1f} "
            f"({best.candidate.kind}:{best.candidate.name})."
        )

    close_set = [
        s for s in top[:4]
        if (best.score.total - s.score.total) <= _ORCHESTRATE_GAP
        and s.score.total >= _MIN_SCORE_FOR_DELEGATION
    ]
    kinds = {s.candidate.kind for s in close_set}
    if len(close_set) >= 3 and len(kinds) >= 2 and _is_multi_domain(task_lower):
        return "orchestrate", (
            "Multi-domain task with several strong candidates spanning different "
            "kinds. sequence them rather than forcing one to span everything."
        )

    return best.candidate.kind, (
        f"Top candidate scored {best.score.total:.1f} "
        f"({best.candidate.kind}:{best.candidate.name}); "
        f"runner-up score gap: "
        f"{(best.score.total - top[1].score.total):.1f}" if len(top) > 1
        else f"Top candidate scored {best.score.total:.1f} (sole candidate above threshold)."
    )


def _pick_winners(top: list[ScoredCandidate], mechanism: str):
    """Pick (primary, runner_up, steps) based on the chosen mechanism."""
    if mechanism == "direct":
        return None, None, []
    if mechanism == "orchestrate":
        steps = [s for s in top[:4] if s.score.total >= _MIN_SCORE_FOR_DELEGATION]
        return steps[0] if steps else None, steps[1] if len(steps) > 1 else None, steps
    primary = top[0] if top else None
    runner_up = top[1] if len(top) > 1 else None
    return primary, runner_up, []


def _looks_trivial(task_lower: str) -> bool:
    """Identify tasks that should never be delegated."""
    triggers = (
        "rename ", "rename_", "rename:", "rename '", "rename \"",
        "change the value", "fix typo", "single-line", "one-liner",
        "add a comment", "remove a comment",
    )
    if any(t in task_lower for t in triggers):
        return True
    words = task_lower.split()
    if len(words) < 6 and not any(
        w in task_lower for w in ("debug", "investigate", "audit", "review", "fix", "refactor")
    ):
        return True
    return False


def _is_multi_domain(task_lower: str) -> bool:
    """Detect tasks that span multiple disciplines."""
    domain_words = (
        "copy", "layout", "ux", "design", "css", "frontend", "backend",
        "api", "database", "sql", "auth", "test", "analytics", "tracking",
        "deploy", "ci", "infra", "seo", "perf", "security",
    )
    hits = sum(1 for w in domain_words if w in task_lower)
    return hits >= 3


def route_to_json(task: str, **kwargs) -> str:
    """Convenience: route + JSON-serialize."""
    verdict = route(task, **kwargs)
    return verdict.to_json()
