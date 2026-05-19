from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterable, Optional


_VERB_FAMILIES: dict[str, frozenset[str]] = {
    "review":   frozenset({"review", "audit", "inspect", "check", "examine", "evaluate", "critique"}),
    "build":    frozenset({"build", "create", "implement", "write", "generate", "scaffold", "draft", "ship"}),
    "fix":      frozenset({"fix", "debug", "resolve", "repair", "patch", "troubleshoot"}),
    "refactor": frozenset({"refactor", "rewrite", "restructure", "clean", "tidy", "modernize"}),
    "research": frozenset({"research", "investigate", "explore", "find", "discover", "analyze"}),
    "plan":     frozenset({"plan", "design", "architect", "outline", "sketch", "propose"}),
    "test":     frozenset({"test", "verify", "validate", "qa"}),
    "deploy":   frozenset({"deploy", "release", "rollout", "ship", "publish"}),
    "explain":  frozenset({"explain", "describe", "document", "summarize"}),
    "optimize": frozenset({"optimize", "improve", "tune", "speed", "accelerate"}),
}

_NEGATIVE_PATTERNS = [
    r"\bdo\s*not\s+use\s+for\b",
    r"\bdon't\s+use\s+for\b",
    r"\bnot\s+for\b",
    r"\bskip\s+when\b",
    r"\bavoid\s+for\b",
    r"\bnever\s+use\s+for\b",
    r"\bexcept\s+for\b",
    r"\binstead\s+use\b",
]
_NEGATIVE_RE = re.compile("|".join(_NEGATIVE_PATTERNS), re.IGNORECASE)

# Words ignored when extracting keywords.
_STOPWORDS = frozenset({
    "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "should",
    "can", "could", "may", "might", "must", "shall", "to", "of", "in", "on",
    "at", "by", "for", "with", "from", "as", "into", "during", "before",
    "after", "above", "below", "between", "through", "and", "or", "but",
    "if", "while", "this", "that", "these", "those", "i", "you", "he", "she",
    "it", "we", "they", "what", "which", "who", "whom", "whose", "where",
    "when", "why", "how", "so", "than", "too", "very", "just", "also", "now",
    "then", "here", "there", "any", "some", "no", "not", "only", "own",
    "same", "more", "most", "other", "another", "such", "all", "each",
    "every", "both", "few", "many",
})


@dataclass
class Candidate:
    """A routable candidate (skill / subagent / rule)."""
    name: str
    kind: str                 # "skill" | "subagent" | "rule"
    description: str
    tools: list[str] = field(default_factory=list)
    path: Optional[str] = None
    source: str = ""          # scope: "global" | "project" | adapter-specific


@dataclass
class Score:
    """Score breakdown for one candidate against one task."""
    total: float = 0.0
    domain_match: float = 0.0
    verb_match: float = 0.0
    negative_signals: float = 0.0
    tool_sufficiency: float = 0.0
    mechanism_bonus: float = 0.0
    explanation: str = ""


def extract_keywords(task: str, limit: int = 8) -> list[str]:
    """Pull domain-significant keywords from a task description."""
    tokens = re.findall(r"[A-Za-z][A-Za-z0-9_-]+", task.lower())
    seen: set[str] = set()
    out: list[str] = []
    for tok in tokens:
        if tok in _STOPWORDS or tok in seen or len(tok) < 3:
            continue
        seen.add(tok)
        out.append(tok)
        if len(out) >= limit:
            break
    return out


def extract_verbs(task: str) -> set[str]:
    """Return the verb families present in the task."""
    tokens = set(re.findall(r"[A-Za-z]+", task.lower()))
    out: set[str] = set()
    for family, members in _VERB_FAMILIES.items():
        if tokens & members:
            out.add(family)
    return out


def score_candidate(candidate: Candidate, task: str,
                    keywords: Optional[Iterable[str]] = None,
                    verbs: Optional[Iterable[str]] = None) -> Score:
    """Score a candidate against a task. Pure function, deterministic."""
    if keywords is None:
        keywords = extract_keywords(task)
    if verbs is None:
        verbs = extract_verbs(task)

    keywords = list(keywords)
    verbs = set(verbs)

    desc_lower = candidate.description.lower()
    name_lower = candidate.name.lower()

    domain = _domain_match(desc_lower, keywords)
    verb = _verb_match(desc_lower, verbs)
    negative = _negative_signals(desc_lower, keywords, verbs)
    tools = _tool_sufficiency(candidate)
    mech = _mechanism_bonus(candidate, task)
    cross = _cross_category_penalty(task, desc_lower + " " + name_lower)
    name_bonus = _name_match_bonus(name_lower, list(keywords))

    total = domain + verb + negative + tools + mech + cross + name_bonus

    explanation = _explanation(
        candidate, domain=domain, verb=verb, negative=negative,
        tools=tools, mech=mech, total=total
    )

    return Score(
        total=total, domain_match=domain, verb_match=verb,
        negative_signals=negative + cross, tool_sufficiency=tools,
        mechanism_bonus=mech, explanation=explanation,
    )


_KEYWORD_SYNONYMS = {
    "slow": ("performance", "perf", "speed", "latency", "fast", "optimization"),
    "fast": ("performance", "speed", "latency", "optimization"),
    "bottleneck": ("performance", "perf", "optimization", "profiler", "profile", "profil"),
    "bottlenecks": ("performance", "perf", "optimization", "profiler", "profile", "profil"),
    "performance": ("bottleneck", "perf", "profiler", "profile", "optimization", "speed", "slow"),
    "perf": ("performance", "bottleneck", "profiler", "optimization"),
    "latency": ("performance", "perf", "slow", "speed"),
    "timing": ("performance", "perf", "latency", "speed", "slow"),
    "timeout": ("performance", "latency", "slow", "perf"),
    "timeouts": ("performance", "latency", "slow", "perf"),
    "review": ("audit", "inspect", "check", "examine"),
    "audit": ("review", "inspect", "check", "examine"),
    "debug": ("bug", "fix", "troubleshoot", "investigate", "diagnose"),
    "fix": ("debug", "bug", "patch", "resolve"),
    "refactor": ("rewrite", "restructure", "clean", "modernize"),
    "investigate": ("debug", "diagnose", "trace", "find"),
    "vulnerability": ("security", "exploit", "cve", "vuln"),
    "vulnerabilities": ("security", "exploit", "cve", "vuln"),
    "injection": ("security", "vulnerability", "xss", "sqli"),
    "sql": ("database", "query", "queries"),
    "auth": ("authentication", "authorization", "security", "session", "token"),
    "security": ("vulnerability", "auth", "exploit", "audit"),
    "exploit": ("security", "vulnerability", "cve"),
}


def _expand_keywords(keywords: list[str]) -> list[str]:
    """Expand a keyword list with semantic synonyms (one hop)."""
    expanded = list(keywords)
    seen = set(k.lower() for k in keywords)
    for kw in keywords:
        for syn in _KEYWORD_SYNONYMS.get(kw.lower(), ()):
            if syn not in seen:
                expanded.append(syn)
                seen.add(syn)
    return expanded


def _name_match_bonus(name_lower: str, keywords: list[str]) -> float:
    """Bonus when candidate name tokens match expanded task keywords."""
    if not keywords:
        return 0.0
    expanded = _expand_keywords(keywords)
    name_tokens = set(re.findall(r"[a-z]+", name_lower))
    if not name_tokens:
        return 0.0
    hits = sum(1 for kw in expanded if kw in name_tokens)
    if hits == 0:
        return 0.0
    if hits == 1:
        return 1.5
    if hits == 2:
        return 2.5
    return 3.5


def _domain_match(desc_lower: str, keywords: list[str]) -> float:
    """Count how many task keywords (and synonyms) appear in the description."""
    if not keywords:
        return 0.0
    expanded = _expand_keywords(keywords)
    hit_tokens = set()
    for kw in expanded:
        if kw and kw in desc_lower:
            hit_tokens.add(kw)
    hits = len(hit_tokens)
    if hits == 0:
        return 0.0
    if hits == 1:
        return 1.5
    if hits == 2:
        return 3.0
    if hits == 3:
        return 4.0
    return 5.0


# "audience model", A/B "test", "deploy" ads, etc. They falsely tag content
_TECHNICAL_SIGNALS = frozenset({
    "bug", "bugs", "bottleneck", "bottlenecks", "performance", "perf",
    "slow", "latency", "timeout", "timeouts", "debug", "debugging",
    "refactor", "rewrite", "function", "functions", "class", "classes",
    "method", "methods", "endpoint", "endpoints", "query", "queries",
    "database", "sql", "schema", "migration", "migrations",
    "compile", "lint", "stacktrace", "exception",
    "frontend", "backend", "controller", "repository",
    "module", "package", "import",
    "codebase", "repo", "commit", "branch", "merge",
    "framework", "library", "javascript", "typescript", "python",
    "react", "vue", "angular", "django", "flask",
    "docker", "kubernetes",
})

_CONTENT_SIGNALS = frozenset({
    "seo", "marketing", "campaign", "ad", "ads", "advertisement",
    "blog", "newsletter",
    "social-media", "instagram", "linkedin", "facebook", "twitter",
    "youtube", "tiktok", "audience", "engagement", "conversion",
    "funnel", "copywriting", "branding", "logo",
    "keyword", "keywords", "backlink", "backlinks", "ranking",
    "rankings", "sitemap", "schema-markup",
    "google-ads", "facebook-ads", "tiktok-ads",
})


def _category_of(text: str) -> set[str]:
    tokens = set(re.findall(r"[A-Za-z]+", text.lower()))
    out: set[str] = set()
    if tokens & _TECHNICAL_SIGNALS:
        out.add("technical")
    if tokens & _CONTENT_SIGNALS:
        out.add("content")
    return out


def _cross_category_penalty(task: str, candidate_text: str) -> float:
    """Penalize when task and candidate clearly belong to different categories."""
    task_cats = _category_of(task)
    cand_cats = _category_of(candidate_text)
    if not task_cats or not cand_cats:
        return _strong_content_only_penalty(task, candidate_text)
    if task_cats & cand_cats:
        return _strong_content_only_penalty(task, candidate_text)
    return -5.0


_STRONG_CONTENT_MARKERS = frozenset({
    "seo", "marketing", "ad", "ads", "advertisement", "campaign",
    "keyword", "keywords", "backlink", "backlinks", "ranking", "rankings",
    "sitemap", "copywriting", "branding", "newsletter", "blog",
    "instagram", "facebook", "tiktok", "linkedin", "youtube", "twitter",
    "semrush", "ahrefs", "moz",
})


def _strong_content_only_penalty(task: str, candidate_text: str) -> float:
    """Hard penalty when the candidate is clearly a content/marketing tool"""
    cand_tokens = set(re.findall(r"[a-z]+", candidate_text.lower()))
    task_tokens = set(re.findall(r"[a-z]+", task.lower()))
    cand_marketing = bool(cand_tokens & _STRONG_CONTENT_MARKERS)
    task_marketing = bool(task_tokens & _STRONG_CONTENT_MARKERS)
    if cand_marketing and not task_marketing:
        return -6.0
    return 0.0


def _verb_match(desc_lower: str, verbs: set[str]) -> float:
    """Does the description contain language matching the task's verb family?"""
    if not verbs:
        return 0.0
    hits = 0
    for verb in verbs:
        members = _VERB_FAMILIES.get(verb, frozenset())
        if any(m in desc_lower for m in members):
            hits += 1
    if hits == 0:
        return 0.0
    if hits == 1:
        return 2.0
    return 3.0


def _negative_signals(desc_lower: str, keywords: list[str], verbs: set[str]) -> float:
    """Hard penalty when description says 'do NOT use for X' and task is X."""
    if not _NEGATIVE_RE.search(desc_lower):
        return 0.0

    penalty = 0.0
    for m in _NEGATIVE_RE.finditer(desc_lower):
        tail = desc_lower[m.end():m.end() + 100]
        if any(kw in tail for kw in keywords):
            penalty -= 5.0
            break
        # Or any verb family member
        for verb in verbs:
            members = _VERB_FAMILIES.get(verb, frozenset())
            if any(member in tail for member in members):
                penalty -= 3.0
                break
        if penalty < 0:
            break
    return penalty


def _tool_sufficiency(candidate: Candidate) -> float:
    """Skills are 2.0 (no tool dependency). Subagents are checked."""
    if candidate.kind == "skill":
        return 2.0
    if not candidate.tools:
        return 1.0
    tools_set = {t.strip() for t in candidate.tools}
    has_read = "Read" in tools_set
    has_mutate = any(t in tools_set for t in ("Edit", "Write", "Bash", "NotebookEdit"))
    if has_read and has_mutate:
        return 2.0
    if has_read or has_mutate:
        return 1.0
    return 0.5


def _mechanism_bonus(candidate: Candidate, task: str) -> float:
    """Tie-breaker."""
    task_lower = task.lower()
    is_research = any(w in task_lower for w in (
        "investigate", "research", "audit", "analyze", "diagnose", "find out",
        "trace", "explore",
    ))
    is_multi_step = any(w in task_lower for w in (
        "end-to-end", "across", "throughout", "all of", "every", "comprehensive",
    ))

    if candidate.kind == "skill":
        if not is_research and not is_multi_step:
            return 2.0
        return 0.5
    if candidate.kind == "subagent":
        if is_research or is_multi_step:
            return 2.0
        return 0.5
    if candidate.kind == "rule":
        return 0.0
    return 0.0


def _explanation(candidate: Candidate, *, domain: float, verb: float,
                 negative: float, tools: float, mech: float, total: float) -> str:
    """One-line human-readable score summary (for debugging / verbose output)."""
    return (
        f"{candidate.kind}:{candidate.name} "
        f"total={total:.1f} "
        f"(domain={domain:.0f}, verb={verb:.0f}, neg={negative:.0f}, "
        f"tools={tools:.0f}, mech={mech:.0f})"
    )


def rank(scored: list[tuple[Candidate, Score]],
         top_n: Optional[int] = None) -> list[tuple[Candidate, Score]]:
    """Sort by descending score, optionally truncate."""
    ranked = sorted(scored, key=lambda x: x[1].total, reverse=True)
    if top_n is not None:
        ranked = ranked[:top_n]
    return ranked
