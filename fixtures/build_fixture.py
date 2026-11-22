#!/usr/bin/env python3
"""Build the canonical memreckon fixture: one repo, two memory stores,
four claims with four known stamps.

The fixture is *built*, not shipped as static files, because the STALE
stamp depends on file mtimes relative to the timestamps recorded in the
memory -- and mtimes do not survive being copied around. The builder
sets every timestamp explicitly, so the expected outcome is exact:

  claim (both stores)                              expected stamp
  ----------------------------------------------   --------------
  "Dependency requests: 2.31.0"                    VERIFIED
  "Test suite: all tests pass"                     REFUTED (a test fails)
  "slugify helper: defined in src/util.py"         STALE (util.py changed
                                                    after the memory was
                                                    written; claim still true)
  "Review style: the team prefers small,          UNVERIFIABLE (judgment)
   frequent pull requests"

Usage: python3 fixtures/build_fixture.py [target_dir]
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

BASE = 1_700_000_000  # the moment the memories were "written"
OLDER = BASE - 1000  # artifacts that predate the memory
NEWER = BASE + 1000  # artifacts changed after the memory was written


def _write(path: Path, content: str, mtime: float) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    os.utime(path, (mtime, mtime))


MEMORYVAULT_DOC = """---
title: Project state
tags: []
sources:
  - session:fixture
version: 1
updated_at: 1700000000
facts:
  - subject: Dependency requests
    value: 2.31.0
    source: session:fixture
    updated_at: 1700000000
  - subject: Test suite
    value: all tests pass
    source: session:fixture
    updated_at: 1700000000
  - subject: slugify helper
    value: defined in src/util.py
    source: session:fixture
    updated_at: 1700000000
  - subject: Review style
    value: the team prefers small, frequent pull requests
    source: session:fixture
    updated_at: 1700000000
---

# Project state

- **Dependency requests**: 2.31.0
- **Review style**: the team prefers small, frequent pull requests
- **Test suite**: all tests pass
- **slugify helper**: defined in src/util.py
"""

CLAUDE_MD = """# Project memory

- Dependency requests: 2.31.0
- Test suite: all tests pass
- slugify helper: defined in src/util.py
- Review style: the team prefers small, frequent pull requests
"""

UTIL_PY = '''"""Fixture utilities."""


def slugify(text: str) -> str:
    return "-".join(text.lower().split())
'''

APP_PY = '''"""Fixture application entry point."""


def main() -> int:
    return 0
'''

TEST_PY = '''"""Fixture test suite.

test_arithmetic_deliberately_fails is the point of the fixture: the
memory claims all tests pass, and they do not.
"""

import unittest


class TestFixture(unittest.TestCase):
    def test_arithmetic_passes(self):
        self.assertEqual(1 + 1, 2)

    def test_arithmetic_deliberately_fails(self):
        self.assertEqual(1 + 1, 3)  # deliberate: the REFUTED exhibit


if __name__ == "__main__":
    unittest.main()
'''


def build(target: Path) -> dict[str, Path]:
    repo = target / "repo"
    _write(repo / "src" / "app.py", APP_PY, OLDER)
    _write(repo / "src" / "util.py", UTIL_PY, NEWER)
    _write(repo / "requirements.txt", "requests==2.31.0\n", OLDER)
    _write(repo / "tests" / "test_fixture.py", TEST_PY, OLDER)

    vault = target / "memoryvault"
    _write(vault / "project-state.md", MEMORYVAULT_DOC, BASE)

    markdown = target / "markdown"
    _write(markdown / "CLAUDE.md", CLAUDE_MD, BASE)

    return {"repo": repo, "memoryvault": vault, "markdown": markdown}


if __name__ == "__main__":
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("fixture-out")
    paths = build(target)
    for name, p in paths.items():
        print(f"{name}: {p}")
