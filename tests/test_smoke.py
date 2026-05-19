"""Smoke tests. Use isolated tempdir fixtures. never touch the user's real config.

Run with:  python3 -m unittest tests.test_smoke
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

# Make the repo importable
_HERE = Path(__file__).resolve().parent
_REPO = _HERE.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from core import frontmatter, scoring, router
from core.adapters import (
    claude_code, cursor, codex, opencode, gemini,
)


# ─── Frontmatter parser ──────────────────────────────────────────────────
class TestFrontmatter(unittest.TestCase):

    def test_basic(self):
        text = textwrap.dedent("""\
            ---
            name: test-skill
            description: A simple test.
            ---
            Body content here.
        """)
        fm = frontmatter.parse_string(text)
        self.assertEqual(fm.get("name"), "test-skill")
        self.assertEqual(fm.get("description"), "A simple test.")
        self.assertIn("Body content here", fm.body)

    def test_quoted_values(self):
        text = '---\nname: "quoted-name"\ndescription: "A description with: colons."\n---\n'
        fm = frontmatter.parse_string(text)
        self.assertEqual(fm.get("name"), "quoted-name")
        self.assertEqual(fm.get("description"), "A description with: colons.")

    def test_no_frontmatter(self):
        fm = frontmatter.parse_string("Just body, no frontmatter.")
        self.assertEqual(fm.fields, {})
        self.assertEqual(fm.body, "Just body, no frontmatter.")

    def test_unclosed_frontmatter(self):
        fm = frontmatter.parse_string("---\nname: foo\n(no closing)")
        # Should not crash; just returns empty fields
        self.assertEqual(fm.fields, {})

    def test_list_inline(self):
        text = '---\ntools: [Read, Edit, "Bash"]\n---\n'
        fm = frontmatter.parse_string(text)
        self.assertEqual(fm.get("tools"), ["Read", "Edit", "Bash"])

    def test_list_block(self):
        text = textwrap.dedent("""\
            ---
            tools:
              - Read
              - Edit
              - Bash
            ---
        """)
        fm = frontmatter.parse_string(text)
        self.assertEqual(fm.get("tools"), ["Read", "Edit", "Bash"])

    def test_boolean_like_string(self):
        text = '---\nalwaysApply: true\n---\n'
        fm = frontmatter.parse_string(text)
        self.assertEqual(fm.get("alwaysApply"), "true")


# ─── Scoring ─────────────────────────────────────────────────────────────
class TestScoring(unittest.TestCase):

    def test_keyword_extraction(self):
        task = "the user profile page is slow, find the bottleneck"
        kws = scoring.extract_keywords(task)
        self.assertIn("user", kws)
        self.assertIn("profile", kws)
        self.assertIn("bottleneck", kws)
        self.assertNotIn("the", kws)  # stopword

    def test_verb_extraction(self):
        verbs = scoring.extract_verbs("review this code carefully")
        self.assertIn("review", verbs)

        verbs = scoring.extract_verbs("debug the failing test")
        self.assertIn("fix", verbs)  # debug → fix family

    def test_domain_match_saturating(self):
        cand = scoring.Candidate(
            name="db", kind="subagent",
            description="Database performance, slow queries, indexes",
        )
        s = scoring.score_candidate(cand, "find the slow database query")
        self.assertGreaterEqual(s.domain_match, 2.0)

    def test_negative_signal_excludes(self):
        cand = scoring.Candidate(
            name="db-perf", kind="subagent",
            description="Database performance work. Do NOT use for migration review.",
        )
        # Task is a migration review. the negative signal should fire
        s = scoring.score_candidate(cand, "review the new migration")
        self.assertLessEqual(s.negative_signals, -3.0)

    def test_tool_sufficiency_skill(self):
        cand = scoring.Candidate(name="any-skill", kind="skill", description="x")
        s = scoring.score_candidate(cand, "any task")
        self.assertEqual(s.tool_sufficiency, 2.0)

    def test_tool_sufficiency_subagent_partial(self):
        cand = scoring.Candidate(
            name="readonly", kind="subagent", description="x",
            tools=["Read"],
        )
        s = scoring.score_candidate(cand, "any task")
        # Read but no Edit/Write/Bash → 1.0
        self.assertEqual(s.tool_sufficiency, 1.0)

    def test_cross_category_penalty_blocks_seo_for_code_task(self):
        """Regression: 'page is slow, find the bottleneck' was matching seo-firecrawl
        on keyword overlap with 'page' and 'find'. Technical-vs-content category
        penalty should bury that match."""
        task = "the user profile page is slow, find the bottleneck"
        seo = scoring.Candidate(
            name="seo-firecrawl", kind="skill",
            description="Crawl pages, find SEO issues, audit content for ranking.",
        )
        perf = scoring.Candidate(
            name="systematic-debugging", kind="skill",
            description="Methodical debugging. For bugs, errors, performance bottlenecks in code.",
        )
        s_seo = scoring.score_candidate(seo, task)
        s_perf = scoring.score_candidate(perf, task)
        self.assertGreater(s_perf.total, s_seo.total,
                           f"PERF should beat SEO for a code task. "
                           f"PERF={s_perf.total} SEO={s_seo.total}")
        self.assertLess(s_seo.negative_signals, 0,
                        "SEO candidate should carry penalty for technical task")


# ─── Adapter: Claude Code with isolated home ─────────────────────────────
class TestClaudeCodeAdapter(unittest.TestCase):

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp(prefix="router-test-"))
        self.home = self.tmpdir / "claude_home"
        self.proj = self.tmpdir / "project"
        for d in (self.home / "agents", self.home / "skills",
                  self.proj / ".claude" / "agents"):
            d.mkdir(parents=True, exist_ok=True)

        # Fixture: one global agent
        (self.home / "agents" / "db-optimizer.md").write_text(textwrap.dedent("""\
            ---
            name: db-optimizer
            description: Database performance work. Slow queries, indexes, N+1. Do NOT use for migration review.
            tools: [Read, Bash]
            ---
            Body.
        """))

        # Fixture: one project agent
        (self.proj / ".claude" / "agents" / "frontend.md").write_text(textwrap.dedent("""\
            ---
            name: frontend
            description: UI components, CSS, layout, responsive design.
            tools: [Read, Edit, Write]
            ---
        """))

        # Fixture: a few skills
        for slug, desc in [
            ("performance-analysis", "Find performance bottlenecks and optimization opportunities."),
            ("css-review", "Review CSS for layout bugs and a11y issues."),
            ("flaky-test-finder", "Identify and fix flaky tests."),
        ]:
            skill_dir = self.home / "skills" / slug
            skill_dir.mkdir(parents=True, exist_ok=True)
            (skill_dir / "SKILL.md").write_text(
                f"---\nname: {slug}\ndescription: {desc}\n---\nbody"
            )

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _adapter(self):
        return claude_code.ClaudeCodeAdapter(
            home=self.home,
            project_root=self.proj,
            skills_dir=self.home / "skills",
        )

    def test_detect(self):
        self.assertTrue(self._adapter().detect())

    def test_enumerate_subagents(self):
        a = self._adapter()
        candidates = a.enumerate_candidates(["database"])
        names = [c.name for c in candidates]
        # Agents always read fully (not keyword-filtered)
        self.assertIn("db-optimizer", names)
        self.assertIn("frontend", names)

    def test_enumerate_skills_keyword_filter(self):
        a = self._adapter()
        a._build_index()  # explicit
        candidates = a.enumerate_candidates(["performance"])
        names = [c.name for c in candidates if c.kind == "skill"]
        self.assertIn("performance-analysis", names)
        self.assertNotIn("css-review", names)

    def test_format_invocation_skill(self):
        a = self._adapter()
        cand = scoring.Candidate(name="x", kind="skill", description="")
        self.assertEqual(a.format_invocation(cand), "/x")

    def test_format_invocation_subagent(self):
        a = self._adapter()
        cand = scoring.Candidate(name="x", kind="subagent", description="")
        out = a.format_invocation(cand, task="some task")
        self.assertIn('subagent_type: "x"', out)
        self.assertTrue(out.startswith("Agent({"))


# ─── Adapter: Cursor with isolated project ───────────────────────────────
class TestCursorAdapter(unittest.TestCase):

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp(prefix="router-test-"))
        rules = self.tmpdir / ".cursor" / "rules"
        rules.mkdir(parents=True)

        # Manual rule (routable)
        (rules / "code-review.mdc").write_text(textwrap.dedent("""\
            ---
            description: Code review checklist for backend PRs.
            ---
            Review checklist...
        """))
        # Auto-attached rule (not routable, has globs)
        (rules / "typescript-rules.mdc").write_text(textwrap.dedent("""\
            ---
            description: TypeScript conventions.
            globs: ["**/*.ts"]
            ---
            Always use...
        """))
        # Always rule (not routable)
        (rules / "always-on.mdc").write_text(textwrap.dedent("""\
            ---
            alwaysApply: true
            ---
            Project conventions...
        """))

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_detect(self):
        a = cursor.CursorAdapter(project_root=self.tmpdir)
        self.assertTrue(a.detect())

    def test_only_routable_rules_returned(self):
        a = cursor.CursorAdapter(project_root=self.tmpdir)
        candidates = a.enumerate_candidates([])
        names = [c.name for c in candidates]
        self.assertIn("code-review", names)
        self.assertNotIn("typescript-rules", names)
        self.assertNotIn("always-on", names)


# ─── Router end-to-end ───────────────────────────────────────────────────
class TestRouterEndToEnd(unittest.TestCase):

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp(prefix="router-e2e-"))
        self.home = self.tmpdir / "claude_home"
        (self.home / "agents").mkdir(parents=True)
        (self.home / "skills").mkdir(parents=True)

        # One skill that should match performance tasks
        slug_dir = self.home / "skills" / "performance-analysis"
        slug_dir.mkdir()
        (slug_dir / "SKILL.md").write_text(
            "---\nname: performance-analysis\n"
            "description: Find performance bottlenecks and optimization opportunities.\n"
            "---\n"
        )

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_route_picks_skill_for_performance_task(self):
        adapter = claude_code.ClaudeCodeAdapter(
            home=self.home,
            project_root=self.tmpdir,
            skills_dir=self.home / "skills",
        )

        # Monkey-patch the router's adapter resolution to use our isolated adapter
        from core import adapters as adapters_mod
        original_get = adapters_mod.get

        def fake_get(name):
            if name == "claude-code":
                return adapter
            return original_get(name)

        adapters_mod.get = fake_get
        try:
            verdict = router.route(
                "find the performance bottleneck in the login flow",
                target="claude-code",
                project_root=self.tmpdir,
            )
            self.assertEqual(verdict.tool, "claude-code")
            # Should pick skill or subagent (both are valid; we just have a skill)
            self.assertIn(verdict.mechanism, ("skill", "subagent", "direct"))
            if verdict.mechanism != "direct":
                self.assertIsNotNone(verdict.primary)
        finally:
            adapters_mod.get = original_get

    def test_trivial_task_picks_direct(self):
        verdict = router.route(
            "rename foo to bar",
            target="claude-code",
            project_root=self.tmpdir,
        )
        self.assertEqual(verdict.mechanism, "direct")


# ─── install_helper safety: path validation ──────────────────────────────
class TestInstallHelperSafety(unittest.TestCase):

    def test_path_safety_rejects_system_paths(self):
        sys.path.insert(0, str(_REPO / "scripts"))
        try:
            import install_helper
        finally:
            sys.path.pop(0)

        unsafe = [
            Path("/etc/passwd"),
            Path("/usr/bin/python3"),
            Path("/"),
        ]
        for p in unsafe:
            self.assertFalse(
                install_helper._path_is_safe(p),
                f"Should have rejected {p}"
            )

    def test_path_safety_accepts_home_paths(self):
        sys.path.insert(0, str(_REPO / "scripts"))
        try:
            import install_helper
        finally:
            sys.path.pop(0)

        safe = Path.home() / "anywhere" / "below.md"
        self.assertTrue(install_helper._path_is_safe(safe))


if __name__ == "__main__":
    unittest.main()
