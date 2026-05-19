#!/usr/bin/env bash
# install.sh. unified multi-tool installer for the cross-tool router.
#
# Usage:
#   bash install.sh                       # autodetect installed tools, install for all
#   bash install.sh --target=claude-code  # explicit single target
#   bash install.sh --target=cursor --project   # project-local install
#   bash install.sh --all                  # install for every supported tool (creates dirs)
#   bash install.sh --uninstall            # remove router files (keeps cached indexes)
#   bash install.sh --uninstall --target=cursor   # uninstall from one tool
#   bash install.sh --list                 # show what's detected, install nothing
#
# Supported targets: claude-code, cursor, codex, opencode, gemini-cli
#
# Requires: Python 3.7+. The CLI's scoring engine is Python stdlib-only.
#
# Security notes:
#   - All Python work is done via scripts/install_helper.py (argv-based),
#     not inline heredocs. Target args are validated against an allowlist
#     before being passed to Python.
#   - File writes are restricted to paths under $HOME or cwd.
#   - $AGENTMAP_HOME (if set) must be inside $HOME and contain
#     "agentmap" in its path, or we refuse to use it.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCOPE="global"
ACTION="install"
TARGETS=()
INSTALL_ALL=0

# Allowlist. must match _VALID_TARGETS in scripts/install_helper.py.
ALLOWED_TARGETS=("claude-code" "cursor" "codex" "opencode" "gemini-cli")

# ─── Parse args ──────────────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
  case "$1" in
    --project) SCOPE="project"; shift ;;
    --target=*) TARGETS+=("${1#--target=}"); shift ;;
    --target)   shift; TARGETS+=("$1"); shift ;;
    --all)      INSTALL_ALL=1; shift ;;
    --uninstall) ACTION="uninstall"; shift ;;
    --list)     ACTION="list"; shift ;;
    --help|-h)
      sed -n '2,15p' "$0" | sed 's/^# //; s/^#//'
      exit 0 ;;
    *) echo "Unknown arg: $1" >&2; exit 2 ;;
  esac
done

# ─── Validate target names against allowlist ─────────────────────────────
validate_target() {
  local t="$1"
  for allowed in "${ALLOWED_TARGETS[@]}"; do
    [[ "$t" == "$allowed" ]] && return 0
  done
  echo "Invalid target: $t. Allowed: ${ALLOWED_TARGETS[*]}" >&2
  exit 2
}

if [[ ${#TARGETS[@]} -gt 0 ]]; then
  for t in "${TARGETS[@]}"; do
    validate_target "$t"
  done
fi

# ─── Verify Python ───────────────────────────────────────────────────────
if ! command -v python3 >/dev/null 2>&1; then
  echo "Error: Python 3.7+ is required (router CLI is Python stdlib-only)." >&2
  echo "Install Python 3, then re-run this script." >&2
  exit 1
fi

PYTHON_OK="$(python3 -c 'import sys; print("ok" if sys.version_info >= (3, 7) else "")')"
if [[ -z "$PYTHON_OK" ]]; then
  echo "Error: Python 3.7+ required. Found: $(python3 --version)" >&2
  exit 1
fi

# ─── Detection (via helper, no inline interpolation) ─────────────────────
detect_installed() {
  python3 -c "
import sys
sys.path.insert(0, sys.argv[1])
from core import adapters
for a in adapters.detect_installed():
    print(a.name)
" "$SCRIPT_DIR"
}

if [[ "$INSTALL_ALL" -eq 1 ]]; then
  TARGETS=("${ALLOWED_TARGETS[@]}")
elif [[ ${#TARGETS[@]} -eq 0 && "$ACTION" != "list" ]]; then
  while IFS= read -r t; do
    [[ -n "$t" ]] && TARGETS+=("$t")
  done < <(detect_installed)
fi

# ─── --list action ───────────────────────────────────────────────────────
if [[ "$ACTION" == "list" ]]; then
  echo "Detected on this machine:"
  while IFS= read -r t; do
    [[ -n "$t" ]] && echo "  - $t"
  done < <(detect_installed)
  echo ""
  echo "Supported targets (use --target=<name>):"
  for t in "${ALLOWED_TARGETS[@]}"; do echo "  - $t"; done
  exit 0
fi

if [[ ${#TARGETS[@]} -eq 0 ]]; then
  echo "No AI coding tools detected on this machine." >&2
  echo "Specify one: --target=claude-code (or cursor, codex, opencode, gemini-cli)" >&2
  echo "Or install for all supported tools at once: --all" >&2
  exit 1
fi

# ─── Resolve and validate INSTALL_PREFIX ─────────────────────────────────
INSTALL_PREFIX_DEFAULT="$HOME/.agentmap"
INSTALL_PREFIX="${AGENTMAP_HOME:-$INSTALL_PREFIX_DEFAULT}"

# Refuse to use a prefix that:
#   - is not under $HOME
#   - doesn't contain "agentmap" (so an rm -rf can't escape)
#   - is $HOME itself
validate_prefix() {
  local p="$1"
  local home_resolved
  home_resolved="$(cd "$HOME" && pwd -P)"
  # Resolve symlinks defensively
  local p_resolved
  p_resolved="$(realpath -m "$p" 2>/dev/null || echo "$p")"

  if [[ "$p_resolved" == "$home_resolved" || "$p_resolved" == "/" ]]; then
    echo "Refusing to use $p as install prefix (would risk catastrophic rm)." >&2
    exit 3
  fi
  if [[ "$p_resolved" != "$home_resolved"* ]]; then
    echo "Refusing prefix outside \$HOME: $p_resolved" >&2
    exit 3
  fi
  if [[ "$p_resolved" != *"agentmap"* ]]; then
    echo "Refusing prefix without 'agentmap' in path: $p_resolved" >&2
    exit 3
  fi
}
validate_prefix "$INSTALL_PREFIX"

install_cli() {
  echo "[install] Installing router CLI → $INSTALL_PREFIX"
  mkdir -p "$INSTALL_PREFIX"
  # Wipe and recopy. `cp -r SRC DST` semantics differ on some systems when
  # DST already exists (it nests SRC inside DST), so always remove first to
  # guarantee a clean overwrite on re-install.
  rm -rf "$INSTALL_PREFIX/core" "$INSTALL_PREFIX/cli" "$INSTALL_PREFIX/scripts"
  cp -r "$SCRIPT_DIR/core" "$INSTALL_PREFIX/core"
  cp -r "$SCRIPT_DIR/cli" "$INSTALL_PREFIX/cli"
  cp -r "$SCRIPT_DIR/scripts" "$INSTALL_PREFIX/scripts"
  chmod +x "$INSTALL_PREFIX/cli/route"
  chmod +x "$INSTALL_PREFIX/scripts/install_helper.py"
}

uninstall_cli() {
  if [[ -d "$INSTALL_PREFIX" ]]; then
    # validate_prefix already ran; this rm is safe by construction
    rm -rf "$INSTALL_PREFIX"
    echo "  removed: $INSTALL_PREFIX"
  fi
}

# ─── Per-target install via helper (no inline Python) ────────────────────
HELPER="$SCRIPT_DIR/scripts/install_helper.py"
if [[ ! -f "$HELPER" ]]; then
  echo "Missing install helper: $HELPER" >&2
  exit 2
fi

install_target() {
  local target="$1"
  local scope="$2"
  python3 "$HELPER" install "$SCRIPT_DIR" "$target" "$scope"
}

uninstall_target() {
  local target="$1"
  local scope="$2"
  python3 "$HELPER" uninstall "$SCRIPT_DIR" "$target" "$scope"
}

# ─── Run ─────────────────────────────────────────────────────────────────
echo ""
if [[ "$ACTION" == "uninstall" ]]; then
  echo "Uninstalling..."
  for target in "${TARGETS[@]}"; do
    echo "[$target]"
    uninstall_target "$target" "$SCOPE"
  done
  echo ""
  printf "Remove CLI as well (%s)? (y/N) " "$INSTALL_PREFIX"
  read -r confirm
  if [[ "${confirm,,}" == "y" ]]; then
    uninstall_cli
  fi
  echo ""
  echo "Done. Cached indexes (router-index.tsv, skill-index.tsv) left in place."
  exit 0
fi

echo "Installing cross-tool router for: ${TARGETS[*]} (scope: $SCOPE)"
echo ""
install_cli
echo ""

for target in "${TARGETS[@]}"; do
  echo "[$target]"
  install_target "$target" "$SCOPE"
  echo ""
done

echo "Building skill indexes (one-time, ~5-10s)..."
"$INSTALL_PREFIX/cli/route" --rebuild-index 2>&1 | sed 's/^/  /' || true

echo ""
echo "Install complete."
echo ""
echo "Next steps:"
echo "  1. Restart your AI tool (Claude Code / Cursor / etc.) so the new artifacts load."
echo "  2. Try:  /route <task>  (or @route / \$route / @agent-router depending on tool)"
echo ""
echo "Uninstall anytime with: bash install.sh --uninstall"
