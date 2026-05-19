#!/usr/bin/env bash
# list-agents.sh. enumerate all Claude Code subagents available in the current environment.
# Outputs: <scope>\t<name>\t<description (truncated)>
# Scopes: global (~/.claude/agents), project (./.claude/agents)
# Used by the agent-router agent and the /route slash command, but also useful standalone.

set -euo pipefail

print_agents_from() {
  local dir="$1"
  local scope="$2"
  [[ -d "$dir" ]] || return 0
  for f in "$dir"/*.md; do
    [[ -e "$f" ]] || continue
    # Pull name + description from YAML frontmatter (first --- block)
    awk -v scope="$scope" '
      /^---$/ { if (!in_fm) { in_fm=1; next } else { exit } }
      in_fm && /^name:/ { sub(/^name:[[:space:]]*/,""); name=$0 }
      in_fm && /^description:/ { sub(/^description:[[:space:]]*/,""); desc=$0 }
      END {
        if (name) {
          # Truncate description to 120 chars
          if (length(desc) > 120) desc = substr(desc, 1, 117) "..."
          printf "%s\t%s\t%s\n", scope, name, desc
        }
      }
    ' "$f"
  done
}

print_agents_from "$HOME/.claude/agents" "global"
print_agents_from "./.claude/agents" "project"
