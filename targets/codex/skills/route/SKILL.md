---
name: route
description: Deterministic task router for Codex CLI. Picks between skills, direct inline work, and multi-step orchestration. Invoke with $route <task> in the Codex composer. Bypasses Codex's implicit skill selection by calling the cross-tool router CLI for a JSON verdict, then rendering the recommendation natively. Works alongside skills in .agents/skills/ (the shared standard with OpenCode).
---

# Cross-Tool Router (Codex CLI edition)

## When you (the Codex agent) are invoked via `$route <task>`

The user wants a deterministic recommendation for how to handle a task. Routing across:

1. **Codex Skills** at `.agents/skills/<name>/SKILL.md` (cwd, walking up to repo root, then `~`, then `/etc`)
2. **Built-in subagents** (session-scoped via `/agent`)
3. **Direct inline work** when the task is trivial
4. **Multi-step orchestration** when the task spans multiple disciplines

Note: Codex has no on-disk subagent definitions, so the router emits skill-or-direct recommendations primarily.

## Procedure

### Step 1. Call the router CLI

```bash
"$HOME/.agentmap/cli/route" --target=codex --json --top=15 "<the task>"
```

If the CLI isn't installed, fall back to Step 2.

### Step 2. Manual enumeration (fallback)

Walk Codex's skill resolution path:
1. `./.agents/skills/`
2. `<repo-root>/.agents/skills/`
3. `~/.agents/skills/`
4. `/etc/codex/skills/`

For each `<name>/SKILL.md` found, read frontmatter (`name`, `description`). Skip duplicates. first occurrence wins per Codex's resolution order.

Score on:
- Domain match (keywords overlap)
- Verb match (review/build/debug/research/plan)
- Negative signals ("do NOT use for X" → hard exclude)

### Step 3. Pick a mechanism

- **Single skill fits** → recommend `$skill-name`
- **No skill fits** → recommend direct inline work
- **Trivial task** → say so, don't delegate
- **Multi-step task** → list the 2-3 skills to invoke in sequence

## Output format

Pick **one**, no preamble:

```
🎯 Best fit: SKILL → $<skill-name>
   <one sentence. what triggered the match>

🥈 Runner-up: SKILL → $<skill-name>
   <one sentence>

▶️  Invoke with:  $<skill-name>
```

Or:

```
🚫 Don't delegate. handle inline.
   <reason>
```

Or:

```
🔀 Multi-step task. Recommend invoking in sequence:
   1. $<skill-1>. <subtask>
   2. $<skill-2>. <subtask>
   3. synthesis. review end-to-end
```


## Use your judgment

The deterministic score is a hint, not a rule. Read every candidate's name and description carefully. If a lower-scored candidate is clearly a better semantic fit for the task, recommend that one instead. Examples of when to override:
- A candidate's name semantically matches the task domain but its description happens to score lower than an unrelated candidate that shares incidental keywords
- The top-scored candidate is from a wrong domain (the description happens to contain task keywords by coincidence)
- The top-scored candidate has a scoping caveat (e.g. for a specific framework) that doesn't fit the user's actual context

Your judgment beats the scorer when they disagree.

## Hard rules

- Never invent skill names. Only those found in Codex's skill resolution path.
- Respect "do NOT use for X" hard excludes.
- Codex's `$` invocation is for skills only. The CLI's verdict may include subagent suggestions from other tools (informational only. Codex can't invoke them natively from disk).
- If the CLI returns `mechanism: subagent`, translate it: pick the closest skill that covers the same domain, or recommend `direct`.

## Why this skill exists

Codex's implicit skill selection (`policy.allow_implicit_invocation`) can be inconsistent under ambiguous prompts. This skill makes the routing decision explicit and deterministic. same scoring engine as the cross-tool CLI, native to Codex's `$skill` invocation pattern.
