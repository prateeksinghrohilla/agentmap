# Security

## What this tool does and doesn't do

agentmap runs locally. It does not:

- Send anything to any remote service of mine. No telemetry, no logging endpoint.
- Execute code from the candidates it routes between. It reads metadata only (`name`, `description`, `tools` from frontmatter).
- Require sudo or any privileged capability.
- Touch anything outside `$HOME` (and `cwd` for project-local installs).
- Make any network calls.

API keys are not handled by this tool.

## What I checked before publishing

- No `eval` / `exec` / `os.system` / `subprocess` / `pickle` / `__import__` anywhere in the Python code.
- No `shell=True` anywhere.
- No hardcoded credentials or tokens.
- No heredoc Python with bash-variable interpolation. `install.sh` uses `scripts/install_helper.py` with argv passing.
- `rm -rf` only ever runs on `$AGENTMAP_HOME` after `validate_prefix()` confirms it's under `$HOME` and literally contains `agentmap` in the path. You cannot accidentally point it at `/` or `$HOME`.
- Target names are validated against a hardcoded allowlist.
- The frontmatter parser is hand-rolled. No `yaml.load`, no PyYAML deserialization attack surface.
- File writes restricted to under `$HOME` or `cwd` (validated by install_helper.py).

## Risks worth knowing about

### Prompt injection via untrusted skill / agent descriptions

A community-wide issue every router has. If you install a skill from an untrusted source and its description contains adversarial instructions, the LLM may follow them.

agentmap does not execute or evaluate descriptions. It just shows them to the LLM, same as Claude Code / Codex / OpenCode would do natively. Mitigation: only install skills from sources you trust. Audit `~/.claude/skills/**/SKILL.md` (and equivalent paths) before installing anything new.

The keyword-filtered enumeration limits exposure (only skills matching the task's keywords are surfaced), but that's a small defensive layer, not a real fix.

### Install overwrites existing files at known paths

`bash install.sh` will replace `~/.claude/commands/route.md`, `~/.claude/agents/agent-router.md`, etc. without prompting. If you've customized those files, the install will clobber your version.

## Reporting

If you find a security issue, open an issue on the GitHub repo.

## What's not in scope

- Anthropic / OpenAI / Cursor / Google product security. This tool is a local utility; the AI tool you're using is the larger trust boundary.
- Your `~/.claude/skills/` content. That's your skill library, and the router only reads it.
- Plugin marketplaces (claudemarketplaces.com etc). Vetting skills from those is on you.
