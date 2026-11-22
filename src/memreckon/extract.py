"""Claim extraction: read an entry's text, find its checkable claim.

Deterministic pattern matching only -- no model calls, no guessing. The
patterns run in a fixed priority order and the first that matches wins,
so every entry yields at most one claim in v1. An entry with no matching
pattern is a JUDGMENT claim: memreckon will stamp it UNVERIFIABLE with
reason ``not-mechanically-checkable`` rather than pretend to check it.

The taxonomy is the one the audit is honest about: file existence,
symbol existence, test outcomes, dependency versions, config values,
command outcomes, and git state. Those are the claim types a coding
agent's memory is dense with -- and the ones a machine can settle.
"""

from __future__ import annotations

import re
from pathlib import Path

from . import model
from .model import Claim, Entry

_TEST_RE = re.compile(
    r"\btests?\b[^.!?\n]{0,48}?\b(pass(?:es|ed|ing)?|green|fail(?:s|ed|ing|ure)?|broken|red)\b"
    r"|\btest suite\b[^.!?\n]{0,32}?\b(pass(?:es|ed|ing)?|green|fail(?:s|ed|ing|ure)?|broken|red)\b",
    re.I,
)
_DEP_EQ_RE = re.compile(r"([A-Za-z0-9_.\-]+)\s*==\s*([0-9][\w.\-]*)")
_DEP_VER_RE = re.compile(
    r"([A-Za-z0-9_.\-]+)\s+(?:version|v)\s+([0-9]+\.[0-9]+(?:\.[0-9]+)?)", re.I
)
_VERSION_TOKEN_RE = re.compile(r"\b([0-9]+\.[0-9]+(?:\.[0-9]+)?)\b")
_BRANCH_RE = re.compile(r"\bbranch\s+(?:is\s+)?(?:on\s+)?`?([\w][\w./\-]*)`?", re.I)
_ON_BRANCH_RE = re.compile(r"\bon branch\s+`?([\w][\w./\-]*)`?", re.I)
_HEAD_RE = re.compile(r"\bHEAD\s+(?:is\s+)?(?:at\s+)?`?([0-9a-f]{7,40})`?", re.I)
_WORKTREE_RE = re.compile(r"\bworking tree\s+(?:is\s+)?(clean|dirty)\b", re.I)
_BACKTICK_RE = re.compile(r"`([^`]{2,120})`")
_OUTCOME_WORD_RE = re.compile(
    r"\b(prints?|outputs?|returns?|produces?|exits?|succeeds?|fails?)\b", re.I
)
_FILE_DEF_RE = re.compile(r"\b(\S+\.\w{1,6})\s+defines?\s+`?([A-Za-z_]\w*)`?", re.I)
_DEFINED_IN_RE = re.compile(
    r"`?([A-Za-z_]\w*)`?[^.!?\n]{0,40}?\bdefined in\s+`?([\w][\w./\-]*)`?", re.I
)
_SYMBOL_KW_AFTER_RE = re.compile(
    r"`?([A-Za-z_]\w*)`?\s+(?:function|class|method|helper|symbol|routine)\b", re.I
)
_SYMBOL_KW_BEFORE_RE = re.compile(
    r"\b(?:function|class|method|symbol)\s+`?([A-Za-z_][\w.]*)`?", re.I
)
_CALL_SHAPE_RE = re.compile(r"`([A-Za-z_]\w*)\s*\([^`]*\)`")
_PATH_TOKEN_RE = re.compile(
    r"(?<![\w.\-/])((?:\./|\.\./)?[\w.\-]+(?:/[\w.\-]+)+"
    r"|[\w.\-]+\.(?:py|js|ts|tsx|jsx|md|toml|json|ya?ml|txt|sh|rs|go|java|c|h|cpp))"
    r"(?![\w\-])"
)
_GONE_RE = re.compile(r"\b(deleted|removed|no longer exists|does not exist|gone)\b", re.I)
_CONFIG_TRIGGER_RE = re.compile(r"\b(config|setting|settings|env|option|flag|parameter)\b", re.I)
_CONFIG_KV_RE = re.compile(r"([A-Za-z_][\w.\-]*)\s*(?:is|=|:)\s*`?\"?([^\s`\",]+)`?\"?")
_CAPS_KEY_RE = re.compile(r"^[A-Z][A-Z0-9_]{2,}$")
_SYMBOL_STOPWORDS = {"the", "a", "an", "this", "that", "each", "every", "any"}


def _looks_like_path(token: str) -> bool:
    if "://" in token or token.startswith("v") and token[1:2].isdigit():
        return False
    if re.fullmatch(r"[0-9.]+", token):
        return False
    return True


def extract_claim(entry: Entry, manifest_packages: set[str]) -> Claim:
    """Classify one entry into a checkable claim (or JUDGMENT)."""
    text = entry.text
    eid = entry.id

    # 1. Test outcome ------------------------------------------------------
    m = _TEST_RE.search(text)
    if m:
        word = (m.group(1) or m.group(2) or "").lower()
        expected = "fail" if word.startswith(("fail", "broken", "red")) else "pass"
        return Claim(eid, model.TEST_OUTCOME, {"expected": expected})

    # 2. Dependency version --------------------------------------------------
    m = _DEP_EQ_RE.search(text) or _DEP_VER_RE.search(text)
    if m:
        return Claim(
            eid,
            model.DEPENDENCY_VERSION,
            {"package": m.group(1), "version": m.group(2)},
        )
    vm = _VERSION_TOKEN_RE.search(text)
    if vm and manifest_packages:
        low = text.lower()
        for pkg in sorted(manifest_packages, key=len, reverse=True):
            if re.search(r"(?<![\w.\-])" + re.escape(pkg.lower()) + r"(?![\w.\-])", low):
                return Claim(
                    eid,
                    model.DEPENDENCY_VERSION,
                    {"package": pkg, "version": vm.group(1)},
                )

    # 3. Git state -----------------------------------------------------------
    m = _ON_BRANCH_RE.search(text) or _BRANCH_RE.search(text)
    if m:
        return Claim(eid, model.GIT_STATE, {"kind": "branch", "expected": m.group(1)})
    m = _HEAD_RE.search(text)
    if m:
        return Claim(eid, model.GIT_STATE, {"kind": "head", "expected": m.group(1).lower()})
    m = _WORKTREE_RE.search(text)
    if m:
        return Claim(
            eid, model.GIT_STATE, {"kind": "worktree", "expected": m.group(1).lower()}
        )

    # 4. Command outcome -------------------------------------------------------
    bt = _BACKTICK_RE.search(text)
    if bt and _OUTCOME_WORD_RE.search(text):
        cmd = bt.group(1).strip()
        if " " in cmd or "/" in cmd:
            params: dict = {"command": cmd}
            em = re.search(r"\bexits?\s+(?:with\s+)?(?:code\s+)?(\d+)\b", text, re.I)
            if em:
                params["expected_exit"] = int(em.group(1))
            return Claim(eid, model.COMMAND_OUTCOME, params)

    # 5. Symbol existence ------------------------------------------------------
    m = _FILE_DEF_RE.search(text)
    if m:
        return Claim(
            eid,
            model.SYMBOL_EXISTS,
            {"symbol": m.group(2), "file": m.group(1)},
            targets=[m.group(1)],
        )
    m = _DEFINED_IN_RE.search(text)
    if m:
        path = m.group(2).rstrip(".,")
        return Claim(
            eid,
            model.SYMBOL_EXISTS,
            {"symbol": m.group(1), "file": path},
            targets=[path],
        )
    for pattern in (_SYMBOL_KW_BEFORE_RE, _SYMBOL_KW_AFTER_RE):
        m = pattern.search(text)
        if m and m.group(1).lower() not in _SYMBOL_STOPWORDS:
            return Claim(eid, model.SYMBOL_EXISTS, {"symbol": m.group(1)})
    m = _CALL_SHAPE_RE.search(text)
    if m:
        return Claim(eid, model.SYMBOL_EXISTS, {"symbol": m.group(1)})

    # 6. File existence ----------------------------------------------------------
    for pm in _PATH_TOKEN_RE.finditer(text):
        token = pm.group(1)
        if _looks_like_path(token):
            expected_exists = not _GONE_RE.search(text)
            return Claim(
                eid,
                model.FILE_EXISTS,
                {"path": token, "expected_exists": expected_exists},
                targets=[token] if expected_exists else [],
            )

    # 7. Config value --------------------------------------------------------------
    if _CONFIG_TRIGGER_RE.search(text) or _CAPS_KEY_RE.search(text.strip()):
        m = _CONFIG_KV_RE.search(text)
        if m:
            key = m.group(1)
            if key.lower() not in ("config", "setting", "settings", "env", "option"):
                return Claim(
                    eid, model.CONFIG_VALUE, {"key": key, "value": m.group(2)}
                )

    # Nothing mechanically checkable: say so.
    return Claim(eid, model.JUDGMENT, {})
