from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional


@dataclass
class Frontmatter:
    """Parsed frontmatter + remaining body."""
    fields: dict[str, Any] = field(default_factory=dict)
    body: str = ""

    def get(self, key: str, default: Any = None) -> Any:
        return self.fields.get(key, default)


_FENCE = "---"


def parse_file(path: Path) -> Frontmatter:
    """Parse the frontmatter at the top of a markdown/mdc file."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except (OSError, UnicodeDecodeError):
        return Frontmatter()
    return parse_string(text)


def parse_string(text: str) -> Frontmatter:
    """Parse frontmatter from a string. Returns empty Frontmatter if no fence."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != _FENCE:
        return Frontmatter(body=text)

    # Find closing fence
    close_idx = None
    for i in range(1, len(lines)):
        if lines[i].strip() == _FENCE:
            close_idx = i
            break
    if close_idx is None:
        return Frontmatter(body=text)

    fm_lines = lines[1:close_idx]
    body = "\n".join(lines[close_idx + 1:])
    return Frontmatter(fields=_parse_block(fm_lines), body=body)


def _parse_block(lines: list[str]) -> dict[str, Any]:
    """Parse a list of YAML-ish lines into a dict."""
    out: dict[str, Any] = {}
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        # Skip empty / comment lines
        if not stripped or stripped.startswith("#"):
            i += 1
            continue

        if line.startswith((" ", "\t")):
            i += 1
            continue

        m = re.match(r"^([A-Za-z_][A-Za-z0-9_-]*)\s*:\s*(.*)$", line)
        if not m:
            i += 1
            continue

        key, rest = m.group(1), m.group(2)
        rest = rest.strip()

        # Multi-line literal or folded
        if rest in ("|", ">"):
            joiner = "\n" if rest == "|" else " "
            block, i = _consume_indented_block(lines, i + 1)
            out[key] = joiner.join(block).strip()
            continue

        # Inline list
        if rest.startswith("[") and rest.endswith("]"):
            inner = rest[1:-1].strip()
            if not inner:
                out[key] = []
            else:
                out[key] = [_unquote(x.strip()) for x in _split_csv(inner)]
            i += 1
            continue

        # Block list (next lines start with "- ")
        if rest == "":
            items, i = _consume_block_list(lines, i + 1)
            if items:
                out[key] = items
            else:
                obj, i = _consume_nested_object(lines, i)
                if obj:
                    out[key] = obj
                else:
                    out[key] = ""
            continue

        # Plain scalar
        out[key] = _unquote(rest)
        i += 1

    return out


def _consume_indented_block(lines: list[str], start: int) -> tuple[list[str], int]:
    """Consume consecutive indented lines as a multi-line value."""
    out: list[str] = []
    i = start
    while i < len(lines):
        line = lines[i]
        if line.startswith((" ", "\t")):
            out.append(line.lstrip())
            i += 1
        elif line.strip() == "":
            out.append("")
            i += 1
        else:
            break
    return out, i


def _consume_block_list(lines: list[str], start: int) -> tuple[list[Any], int]:
    """Consume lines starting with `- ` as list items."""
    out: list[Any] = []
    i = start
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        if not stripped:
            i += 1
            continue
        # Must be indented AND start with "- "
        if not (line.startswith((" ", "\t")) and stripped.startswith("- ")):
            break

        rest = stripped[2:].strip()

        # Detect: list-of-dicts (`- key: value` pattern)
        m = re.match(r"^([A-Za-z_][A-Za-z0-9_-]*)\s*:\s*(.*)$", rest)
        if m:
            # First key:value pair of a dict item
            item: dict[str, Any] = {}
            key, val = m.group(1), m.group(2).strip()
            item[key] = _unquote(val)
            i += 1
            dash_indent = len(line) - len(line.lstrip())
            while i < len(lines):
                cont = lines[i]
                cont_strip = cont.strip()
                if not cont_strip:
                    i += 1
                    continue
                cont_indent = len(cont) - len(cont.lstrip())
                if cont_strip.startswith("- ") and cont_indent <= dash_indent:
                    break
                if cont_indent <= dash_indent:
                    break
                m2 = re.match(r"^([A-Za-z_][A-Za-z0-9_-]*)\s*:\s*(.*)$", cont_strip)
                if not m2:
                    i += 1
                    continue
                k2, v2 = m2.group(1), m2.group(2).strip()
                item[k2] = _unquote(v2)
                i += 1
            out.append(item)
            continue

        # Plain scalar list item
        out.append(_unquote(rest))
        i += 1
    return out, i


def _consume_nested_object(lines: list[str], start: int) -> tuple[dict[str, Any], int]:
    """Consume a one-level-deep nested object (indented k:v pairs)."""
    out: dict[str, Any] = {}
    i = start + 1
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        if not stripped:
            i += 1
            continue
        if not line.startswith((" ", "\t")):
            break
        m = re.match(r"^\s+([A-Za-z_][A-Za-z0-9_-]*)\s*:\s*(.*)$", line)
        if m:
            out[m.group(1)] = _unquote(m.group(2).strip())
            i += 1
        else:
            break
    return out, i


def _unquote(s: str) -> str:
    """Strip surrounding quotes if present."""
    s = s.strip()
    if len(s) >= 2 and s[0] == s[-1] and s[0] in ('"', "'"):
        return s[1:-1]
    return s


def _split_csv(s: str) -> list[str]:
    """Split on commas, respecting quoted segments."""
    out: list[str] = []
    buf: list[str] = []
    in_quote: Optional[str] = None
    for ch in s:
        if in_quote:
            buf.append(ch)
            if ch == in_quote:
                in_quote = None
        elif ch in ('"', "'"):
            in_quote = ch
            buf.append(ch)
        elif ch == ",":
            out.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
    if buf:
        out.append("".join(buf))
    return out
