#!/usr/bin/env bash
# list-skills.sh. enumerate Claude Code skills, filtered by keyword.
#
# Why this exists: ~/.claude/skills/ can contain thousands of skills (the test
# machine has ~2,000). Listing them all would blow the router's context. So we:
#   1. Build a one-line-per-skill index file (~/.claude/skill-index.tsv) and
#      cache it on disk. Rebuild only when stale (>7 days) or forced.
#   2. Grep the index for keyword matches at lookup time. Fast (<50ms typical).
#
# Usage:
#   list-skills.sh                    # print top 50 + warn about no filter
#   list-skills.sh perf debug         # AND-match all keywords across name + desc
#   list-skills.sh --rebuild          # force rebuild the cached index
#   list-skills.sh --any perf cache   # OR-match any of the keywords
#
# Output format (tab-separated):
#   skill   <skill-name>   <description (truncated to 160 chars)>

set -euo pipefail

SKILLS_DIR="${CLAUDE_SKILLS_DIR:-$HOME/.claude/skills}"
INDEX_FILE="${CLAUDE_SKILL_INDEX:-$HOME/.claude/skill-index.tsv}"
STALE_DAYS=7
MATCH_MODE="all"   # all | any
FORCE_REBUILD=0
KEYWORDS=()

# Parse args
while [[ $# -gt 0 ]]; do
  case "$1" in
    --rebuild) FORCE_REBUILD=1; shift ;;
    --any) MATCH_MODE="any"; shift ;;
    --all) MATCH_MODE="all"; shift ;;
    --help|-h)
      sed -n '2,20p' "$0" | sed 's/^# //; s/^#//'
      exit 0 ;;
    *) KEYWORDS+=("$1"); shift ;;
  esac
done

# Build index if missing / stale / forced
needs_rebuild=0
if [[ $FORCE_REBUILD -eq 1 ]]; then
  needs_rebuild=1
elif [[ ! -f "$INDEX_FILE" ]]; then
  needs_rebuild=1
elif find "$INDEX_FILE" -mtime +"$STALE_DAYS" -print 2>/dev/null | grep -q .; then
  needs_rebuild=1
fi

if [[ $needs_rebuild -eq 1 ]]; then
  echo "[list-skills] Building index from $SKILLS_DIR ..." >&2
  tmp_index="$(mktemp)"
  count=0
  for dir in "$SKILLS_DIR"/*/; do
    [[ -d "$dir" ]] || continue
    skill_md="$dir/SKILL.md"
    [[ -f "$skill_md" ]] || continue
    awk '
      BEGIN { in_fm=0; name=""; desc="" }
      /^---$/ { if (!in_fm) { in_fm=1; next } else { exit } }
      in_fm && /^name:/ {
        sub(/^name:[[:space:]]*/,"")
        gsub(/^"|"$/,"")
        name=$0
      }
      in_fm && /^description:/ {
        sub(/^description:[[:space:]]*/,"")
        gsub(/^"|"$/,"")
        desc=$0
      }
      END {
        if (name != "") {
          if (length(desc) > 160) desc = substr(desc, 1, 157) "..."
          # Replace any tabs in desc with spaces (defensive)
          gsub(/\t/, " ", desc)
          printf "skill\t%s\t%s\n", name, desc
        }
      }
    ' "$skill_md" >> "$tmp_index"
    count=$((count + 1))
  done
  mv "$tmp_index" "$INDEX_FILE"
  echo "[list-skills] Indexed $count skills → $INDEX_FILE" >&2
fi

# Lookup
if [[ ${#KEYWORDS[@]} -eq 0 ]]; then
  echo "[list-skills] No keywords given. ${MATCH_MODE^^}-MATCH disabled. Showing first 50 of $(wc -l < "$INDEX_FILE" | tr -d ' ') skills:" >&2
  head -50 "$INDEX_FILE"
  exit 0
fi

# Build grep pattern. Case-insensitive. For --all mode, chain greps. For --any, single regex.
case "$MATCH_MODE" in
  all)
    cmd="cat \"$INDEX_FILE\""
    for kw in "${KEYWORDS[@]}"; do
      # Escape any regex metachars for safety
      kw_escaped=$(printf '%s' "$kw" | sed 's/[][\.|*$^?+(){}/]/\\&/g')
      cmd="$cmd | grep -i -- \"$kw_escaped\""
    done
    eval "$cmd" 2>/dev/null || true
    ;;
  any)
    pattern=""
    for kw in "${KEYWORDS[@]}"; do
      kw_escaped=$(printf '%s' "$kw" | sed 's/[][\.|*$^?+(){}/]/\\&/g')
      [[ -n "$pattern" ]] && pattern="$pattern\\|$kw_escaped" || pattern="$kw_escaped"
    done
    grep -i -- "$pattern" "$INDEX_FILE" 2>/dev/null || true
    ;;
esac
