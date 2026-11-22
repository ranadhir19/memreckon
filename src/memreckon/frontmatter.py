"""A tolerant parser for the small frontmatter subset memoryvault-agents
writes.

memreckon's adapters must run on the Python standard library alone, so
this module implements just enough of the YAML frontmatter shape that a
MemoryDoc uses:

    ---
    title: Project state
    tags: [alpha, beta]
    sources:
      - session:s1
    version: 3
    updated_at: 1700000000.0
    facts:
      - subject: Test suite
        value: all tests pass
        source: session:s1
        updated_at: 1700000000.0
    ---

Top-level scalars, simple flow/block lists of scalars, and a ``facts``
list of flat string-keyed dicts. Anything outside that subset is not an
error: the caller falls back to parsing the rendered body, which carries
the same facts as ``- **subject**: value`` lines. A store the parser
cannot read becomes entries stamped UNVERIFIABLE downstream -- never a
crash, never a guess.
"""

from __future__ import annotations

import re
from typing import Any, Optional


def split_frontmatter(text: str) -> tuple[Optional[str], str]:
    """Return (frontmatter_block, body). Block is None when absent."""
    if not text.startswith("---"):
        return None, text
    lines = text.splitlines()
    for i in range(1, len(lines)):
        if lines[i].strip() in ("---", "..."):
            return "\n".join(lines[1:i]), "\n".join(lines[i + 1 :])
    return None, text


def _scalar(raw: str) -> Any:
    s = raw.strip()
    if len(s) >= 2 and s[0] == s[-1] and s[0] in ("'", '"'):
        return s[1:-1]
    if s.lower() in ("true", "false"):
        return s.lower() == "true"
    try:
        return int(s)
    except ValueError:
        pass
    try:
        return float(s)
    except ValueError:
        pass
    return s


def parse_frontmatter(block: str) -> dict[str, Any]:
    """Parse the supported subset into a dict. Best-effort by design."""
    out: dict[str, Any] = {}
    lines = block.splitlines()
    i = 0
    n = len(lines)
    while i < n:
        line = lines[i]
        if not line.strip() or line.lstrip().startswith("#"):
            i += 1
            continue
        m = re.match(r"^([A-Za-z_][\w\-]*):\s*(.*)$", line)
        if not m:
            i += 1
            continue
        key, rest = m.group(1), m.group(2).strip()
        if rest.startswith("[") and rest.endswith("]"):
            inner = rest[1:-1].strip()
            out[key] = [_scalar(x) for x in inner.split(",")] if inner else []
            i += 1
            continue
        if rest:
            out[key] = _scalar(rest)
            i += 1
            continue
        # Block value: a list of scalars, or (for `facts`) a list of dicts.
        items: list[Any] = []
        i += 1
        current: Optional[dict[str, Any]] = None
        while i < n:
            sub = lines[i]
            if not sub.strip():
                i += 1
                continue
            if not sub.startswith((" ", "\t")):
                break
            stripped = sub.strip()
            if stripped.startswith("- "):
                item_text = stripped[2:]
                # A mapping needs "key: value" (space after the colon);
                # "session:fixture" is a plain scalar.
                kv = re.match(r"^([A-Za-z_][\w\-]*):(?:\s+(.*))?$", item_text)
                if kv:
                    current = {kv.group(1): _scalar(kv.group(2) or "")}
                    items.append(current)
                else:
                    current = None
                    items.append(_scalar(item_text))
                i += 1
                continue
            kv = re.match(r"^([A-Za-z_][\w\-]*):(?:\s+(.*))?$", stripped)
            if kv and current is not None:
                current[kv.group(1)] = _scalar(kv.group(2) or "")
            i += 1
        out[key] = items
    return out
