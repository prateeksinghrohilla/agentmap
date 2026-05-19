---
description: Cross-tool task router for OpenCode. Picks between skills, subagents, direct inline work, and multi-domain orchestration. Invoke with /route <task> in the OpenCode TUI. Calls the router CLI for deterministic scoring and renders a clean recommendation. Respects negative signals in candidate descriptions.
subtask: false
---

# Cross-Tool Router (OpenCode)

The user invoked `/route` with: $ARGUMENTS

## Procedure

### Step 1. Call the router CLI

```bash
!`"$HOME/.agentmap/cli/route" --target=opencode --json --top=15 "$ARGUMENTS"`
```

(OpenCode supports `!`` `` bash injection inside command bodies. the above runs the router CLI and substitutes the JSON output into the prompt.)

If the CLI isn't installed, fall back to manual enumeration:

```bash
!`ls -1 ~/.config/opencode/agents/ 2>/dev/null | grep '\.md$'`
!`ls -1 .opencode/agents/ 2>/dev/null | grep '\.md$'`
!`ls -1 ~/.claude/agents/ 2>/dev/null | grep '\.md$'`     # Claude compat fallback
```

OpenCode reads `.claude/skills/` and `.agents/skills/` as fallbacks, so the candidate pool is unusually large. the CLI's keyword-filtered index is the right tool.

### Step 2. Render the verdict

Parse the JSON and emit **one** block:

#### Skill match
```
🎯 Best fit: SKILL → /<primary.name>
   <primary.description (first sentence)>

🥈 Runner-up: <runner_up.kind> → <runner_up.name>
   <runner_up.description>

▶️  Invoke with:  /<primary.name>
```

#### Subagent match
```
🎯 Best fit: SUBAGENT → @<primary.name>
   <primary.description>

🥈 Runner-up: <runner_up.kind> → <runner_up.name>
   <runner_up.description>

▶️  Invoke with:  @<primary.name>
```

#### Direct
```
🚫 Don't delegate. handle inline.
   <reason>
```

#### Orchestrate
```
🔀 Multi-domain task. Recommend invoking in sequence:
   1. <step[0].kind>: <step[0].name>. <subtask>
   2. <step[1].kind>: <step[1].name>. <subtask>
   3. synthesis. review end-to-end
```


## Use your judgment

The deterministic score is a hint, not a rule. Read every candidate's name and description carefully. If a lower-scored candidate is clearly a better semantic fit for the task, recommend that one instead. Examples of when to override:
- A candidate's name semantically matches the task domain but its description happens to score lower than an unrelated candidate that shares incidental keywords
- The top-scored candidate is from a wrong domain (the description happens to contain task keywords by coincidence)
- The top-scored candidate has a scoping caveat (e.g. for a specific framework) that doesn't fit the user's actual context

Your judgment beats the scorer when they disagree.

## Hard rules

- Never invent candidate names. Only those returned by the CLI.
- Respect negative signals. `"do NOT use for X"` in a description is a hard exclude when the task is X.
- OpenCode's invocation styles: `/<name>` for commands and skills; `@<name>` for agents. Don't mix them.
- If CLI returns an agent from `.claude/agents/` (Claude compat fallback), that's fine. OpenCode reads those for skills but NOT for agents. Verify the candidate's `path` field; if it's in `.claude/agents/`, recommend `direct` or `orchestrate` instead unless the user has explicitly enabled Claude compat for agents.
