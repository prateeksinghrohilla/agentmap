#!/usr/bin/env python3
from __future__ import annotations

import os
import shutil
import stat
import sys
from pathlib import Path


_VALID_TARGETS = frozenset({
    "claude-code", "cursor", "codex", "opencode", "gemini-cli",
})
_VALID_SCOPES = frozenset({"global", "project"})


def main(argv: list[str]) -> int:
    if len(argv) < 5:
        print("Usage: install_helper.py <install|uninstall> <repo_root> <target> <scope>",
              file=sys.stderr)
        return 2

    action = argv[1]
    repo_root_str = argv[2]
    target = argv[3]
    scope = argv[4]

    # ── Validate args ────────────────────────────────────────────────────
    if action not in ("install", "uninstall"):
        print(f"Invalid action: {action!r}. Must be 'install' or 'uninstall'.",
              file=sys.stderr)
        return 2

    if target not in _VALID_TARGETS:
        print(f"Unknown target: {target!r}. Valid: {sorted(_VALID_TARGETS)}",
              file=sys.stderr)
        return 2

    if scope not in _VALID_SCOPES:
        print(f"Invalid scope: {scope!r}. Must be 'global' or 'project'.",
              file=sys.stderr)
        return 2

    repo_root = Path(repo_root_str).resolve()
    if not repo_root.is_dir():
        print(f"Repo root does not exist: {repo_root}", file=sys.stderr)
        return 2
    if not (repo_root / "core" / "adapters" / "__init__.py").is_file():
        print(f"Repo root does not contain expected structure: {repo_root}",
              file=sys.stderr)
        return 2

    # Make core/ importable from this helper
    sys.path.insert(0, str(repo_root))
    try:
        from core import adapters
    except ImportError as e:
        print(f"Failed to import core.adapters: {e}", file=sys.stderr)
        return 2

    adapter = adapters.get(target)
    plan = adapter.install_plan(repo_root, scope=scope)

    if action == "install":
        return _do_install(plan)
    else:
        return _do_uninstall(plan)


def _do_install(plan) -> int:
    if not plan.artifacts:
        print(f"  no install artifacts ({plan.__class__.__name__}).")
        for note in plan.post_install_notes:
            print(f"     {note}")
        return 0

    for art in plan.artifacts:
        src = art.source_path
        dst = art.target_path

        if not _path_is_safe(dst):
            print(f"  unsafe destination, skipping: {dst}", file=sys.stderr)
            continue

        if src is None and art.inline_content is None:
            continue

        dst.parent.mkdir(parents=True, exist_ok=True)
        if src is not None:
            if not src.exists():
                print(f"  source missing: {src}", file=sys.stderr)
                continue
            shutil.copy2(src, dst)
        else:
            dst.write_text(art.inline_content, encoding="utf-8")

        if art.executable:
            os.chmod(dst, os.stat(dst).st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)

        print(f"  installed: {dst}")

    for note in plan.post_install_notes:
        print(f"     {note}")
    return 0


def _do_uninstall(plan) -> int:
    for art in plan.artifacts:
        dst = art.target_path
        if not _path_is_safe(dst):
            print(f"  unsafe destination, skipping: {dst}", file=sys.stderr)
            continue
        if dst.exists():
            dst.unlink()
            print(f"  removed: {dst}")
    return 0


def _path_is_safe(path: Path) -> bool:
    """Refuse to touch paths outside $HOME or cwd."""
    resolved = path.resolve()
    home = Path.home().resolve()
    cwd = Path.cwd().resolve()
    parts = resolved.parts
    # Allow paths under $HOME or cwd
    return (
        _is_descendant(resolved, home)
        or _is_descendant(resolved, cwd)
    )


def _is_descendant(child: Path, parent: Path) -> bool:
    try:
        child.relative_to(parent)
        return True
    except ValueError:
        return False


if __name__ == "__main__":
    sys.exit(main(sys.argv))
