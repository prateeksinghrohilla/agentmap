# agentmap

A task router for AI coding agents. Works in Claude Code, Cursor, Codex CLI, OpenCode, and Gemini CLI. You type `/route some task`, it picks the right specialist (a skill, a subagent, or tells you to just do it inline).

## Why I built this

Every coding agent has the same routing problem. You install a bunch of specialists, the agent ignores them, falls back to general purpose, and burns tokens fumbling around. Claude Code does this with custom subagents. Cursor does it with auto attached rules. Codex does it with implicit skill selection.

Worse, most routers ignore the "do NOT use for X" lines that good specialists put in their descriptions, exactly the line that would have saved you from a misroute.

agentmap fixes that. Deterministic scoring on five axes (domain match, verb match, negative signals, tool fit, mechanism bonus), and it emits the right invocation in your tool's native syntax.

## Install

You need Python 3.7 or later. The router is pure stdlib, no pip step.

```
git clone https://github.com/prateeksinghrohilla/agentmap.git
cd agentmap
bash install.sh
```

The installer detects which AI coding tools you have, copies the router CLI to `~/.agentmap/`, and drops the right artifact into each tool. Restart your AI tool after install so the new slash command (or rule, or skill, depending on the tool) loads.

If you only want it for one tool:

```
bash install.sh --target=claude-code
bash install.sh --target=cursor --project
bash install.sh --target=codex
bash install.sh --target=opencode
bash install.sh --target=gemini-cli
```

## How you use it

Same task, different tool:

```
# Claude Code, OpenCode
/route the user profile page is slow, find the bottleneck

# Cursor
@route the user profile page is slow, find the bottleneck

# Codex CLI
$route the user profile page is slow, find the bottleneck

# Gemini CLI
@agent-router the user profile page is slow, find the bottleneck

# Any terminal
~/.agentmap/cli/route "the user profile page is slow, find the bottleneck"
```

You get back one of four answers. A skill to run (`/performance-analysis`). A subagent to delegate to with the full invocation ready to paste. "Don't delegate, handle it inline" when the task is trivial. Or a sequenced plan across multiple specialists when the task spans domains.

## What makes it different

**Negative signals.** Most routers score on keyword overlap alone. agentmap reads "do NOT use for X" lines in candidate descriptions and treats them as hard excludes. That single thing fixes most of the bad routing I see.

**Cross tool.** Same scoring brain, native invocation in five different AI coding tools.

**Three way mechanism choice.** Most routers only pick between subagents. agentmap also picks skills when one has a matching playbook, refuses to delegate when the task is trivial, and orchestrates multiple specialists when the task spans domains.

## Security

Full notes in [SECURITY.md](SECURITY.md). Short version: no eval, no exec, no shell injection paths. Install paths are validated. No network calls. Pure local read of skill / agent metadata.

The one thing I can't fix on your behalf is prompt injection via untrusted skill descriptions. If you install skills from random sources, audit them.

## Pricing

Free. MIT licensed. Self hosted.

## License

MIT.
