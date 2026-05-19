---
description: Route a task across skills / subagents / direct work / orchestration. Bypasses Claude's unreliable auto-selection by calling the cross-tool router CLI for deterministic scoring, then renders the verdict natively. Multi-tool aware. works in Claude Code, OpenCode, Codex (via shared skills dir), and respects negative signals in candidate descriptions.
argument-hint: <task description>
---

You are acting as the front-end for the **agentmap**, a deterministic, cross-tool routing engine. The user invoked `/route` because Claude Code's built-in routing is unreliable. it ignores custom subagents (see [claude-code#8558](https://github.com/anthropics/claude-code/issues/8558), [#19077](https://github.com/anthropics/claude-code/issues/19077)) and doesn't surface skills as alternatives.

Your job: get a deterministic verdict from the router CLI and render it as a clean recommendation.

## Task to route

$ARGUMENTS

## Procedure

### Step 1. Call the router CLI

Run this in Bash:

```bash
"$HOME/.agentmap/cli/route" --target=claude-code --json --top=15 "$ARGUMENTS_QUOTED"
```

Where `$ARGUMENTS_QUOTED` is the task above with shell quoting. If the binary is not at `$HOME/.agentmap/cli/route`, try:
```bash
command -v route || which route
```
and use that. If you cannot find the CLI at all, fall back to enumerating manually:
```bash
ls -1 ~/.claude/agents/ 2>/dev/null | grep '\.md$'
ls -1 .claude/agents/ 2>/dev/null | grep '\.md$'
~/.claude/scripts/list-skills.sh <keyword> <keyword>
```
and score in your own reasoning. Note in your output that the CLI wasn't available.

### Step 2. Parse the JSON verdict

The CLI returns JSON with these top-level fields:
- `mechanism`. one of `"skill"`, `"subagent"`, `"direct"`, `"orchestrate"`
- `primary`. the top scored candidate (or `null`)
- `runner_up`. second place (or `null`)
- `orchestrate_steps`. list of steps when mechanism is `"orchestrate"`
- `invocation`. copy-paste-ready invocation string
- `reason`. one-line justification
- `keywords` / `verbs`. what the router extracted from the task

### Step 3. Render the verdict

Pick the rendering block matching `mechanism`:

#### `mechanism: "skill"`

```
🎯 Best fit: SKILL → /<primary.name>
   <primary.description (first sentence, max 120 chars)>

🥈 Runner-up: <runner_up.kind.upper()> → <runner_up.name>
   <runner_up.description (first sentence)>

⚠️  Why this skill over a subagent:
   <reason from JSON, rephrased. one line>

▶️  Invoke with:
   <invocation>
```

#### `mechanism: "subagent"`

```
🎯 Best fit: SUBAGENT → <primary.name>
   <primary.description (first sentence)>

🥈 Runner-up: <runner_up.kind.upper()> → <runner_up.name>
   <runner_up.description (first sentence)>

⚠️  Why this subagent over a skill / general-purpose:
   <reason>

▶️  Invoke with:
   <invocation (this is a multi-line Agent({...}) call. preserve formatting)>
```

#### `mechanism: "direct"`

```
🚫 Don't delegate. handle inline.
   <reason>
```

#### `mechanism: "orchestrate"`

```
🔀 Multi-domain task. Recommend orchestrating:
   1. <step[0].kind>: <step[0].name>. <step[0].description (short)>
   2. <step[1].kind>: <step[1].name>. <step[1].description (short)>
   3. <step[2].kind>: <step[2].name>. <step[2].description (short)>
   N. synthesis. review end-to-end consistency

   <reason>
```

### Step 4. Hard rules

- **Never invent a candidate name.** Only render names that came back from the CLI.
- **Use your semantic judgment.** The CLI's pick is a hint based on keyword matching. Override it when a lower-scored candidate is the better semantic fit (different domain, scoping caveat, name semantically closer to the task, etc.).
- **Don't pad output.** One block, terse, copy-pasteable.
- **Don't dump the raw JSON.** Render the verdict block only.
- **If the CLI is unavailable**, fall back to manual enumeration (Step 1) and reason through the four-axis scoring (domain match, verb match, negative signals, tool sufficiency) in your own head. same output format, same rules.

Now route the task above.

## Use your judgment

The deterministic score is a hint, not a rule. Read every candidate's name and description carefully. If a lower-scored candidate is clearly a better semantic fit for the task, recommend that one instead. Examples of when to override:
- A candidate's name semantically matches the task domain but its description happens to score lower than an unrelated candidate that shares incidental keywords
- The top-scored candidate is from a wrong domain (the description happens to contain task keywords by coincidence)
- The top-scored candidate has a scoping caveat (e.g. for a specific framework) that doesn't fit the user's actual context

Your judgment beats the scorer when they disagree.

