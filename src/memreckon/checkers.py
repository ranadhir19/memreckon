"""Reality checks: settle a claim against the live repository.

Each checker returns a ``RawCheck``: a substantive outcome of ``pass``,
``fail``, or ``unable`` (with a reason code), the evidence it gathered,
and the artifact paths the claim is about (the audit layer uses those
for the staleness rule). Checkers never see the stamp set; turning a
pass into STALE when the artifact moved after the memory was written is
the audit layer's job, applied uniformly.

Safety posture: checkers read files and git state freely. They execute
code in exactly two ways -- running the repository's own test suite
(the thing a test-outcome claim is *about*), and, only behind the
explicit ``--run-commands`` opt-in, a command a memory names. A poisoned
memory therefore cannot make the auditor run arbitrary commands by
default; a command-outcome claim without the opt-in is UNVERIFIABLE.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from . import model
from .model import Claim

SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", "dist", "build", ".tox"}
MAX_TEXT_FILE = 2_000_000
MAX_FILES = 20_000


@dataclass
class RawCheck:
    outcome: str  # "pass" | "fail" | "unable"
    reason: str = ""
    evidence: dict[str, Any] = field(default_factory=dict)
    targets: list[str] = field(default_factory=list)


@dataclass
class CheckContext:
    repo: Path
    run_commands: bool = False
    test_timeout: int = 120
    exclude: list[Path] = field(default_factory=list)  # e.g. the store dir


# --------------------------------------------------------------------------
# Repo walking / manifests / config discovery
# --------------------------------------------------------------------------

def iter_repo_files(repo: Path, exclude: Optional[list[Path]] = None) -> list[Path]:
    excluded = [e.resolve() for e in (exclude or [])]
    out: list[Path] = []
    for root, dirs, files in os.walk(repo):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        root_p = Path(root)
        if any(root_p.resolve() == e or e in root_p.resolve().parents for e in excluded):
            dirs[:] = []
            continue
        for name in files:
            out.append(root_p / name)
            if len(out) >= MAX_FILES:
                return out
    return out


def _norm_pkg(name: str) -> str:
    return name.strip().lower().replace("_", "-")


def read_manifests(repo: Path) -> dict[str, dict[str, Any]]:
    """Map normalized package name -> {spec, file} from manifests/lockfiles."""
    found: dict[str, dict[str, Any]] = {}

    def add(name: str, spec: str, fname: str) -> None:
        key = _norm_pkg(name)
        if key and key not in found:
            found[key] = {"spec": str(spec).strip(), "file": fname}

    for req in sorted(repo.glob("requirements*.txt")) + sorted(repo.glob("*.requirements.txt")):
        try:
            for line in req.read_text(encoding="utf-8", errors="replace").splitlines():
                line = line.strip()
                if not line or line.startswith(("#", "-")):
                    continue
                m = re.match(r"([A-Za-z0-9_.\-]+)\s*(.*)", line)
                if m:
                    add(m.group(1), m.group(2) or "*", req.name)
        except OSError:
            pass

    pyproject = repo / "pyproject.toml"
    if pyproject.exists():
        try:
            data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
            deps = (data.get("project") or {}).get("dependencies") or []
            for dep in deps:
                m = re.match(r"([A-Za-z0-9_.\-]+)\s*(.*)", str(dep))
                if m:
                    add(m.group(1), m.group(2) or "*", "pyproject.toml")
            cargo_deps = (data.get("dependencies") or {})
            if isinstance(cargo_deps, dict):
                for name, spec in cargo_deps.items():
                    add(name, spec if isinstance(spec, str) else (spec or {}).get("version", "*"), "pyproject.toml")
        except (ValueError, OSError):
            pass

    cargo = repo / "Cargo.toml"
    if cargo.exists():
        try:
            data = tomllib.loads(cargo.read_text(encoding="utf-8"))
            deps = data.get("dependencies") or {}
            if isinstance(deps, dict):
                for name, spec in deps.items():
                    add(name, spec if isinstance(spec, str) else (spec or {}).get("version", "*"), "Cargo.toml")
        except (ValueError, OSError):
            pass

    pkg_json = repo / "package.json"
    if pkg_json.exists():
        try:
            data = json.loads(pkg_json.read_text(encoding="utf-8"))
            for section in ("dependencies", "devDependencies"):
                deps = data.get(section) or {}
                if isinstance(deps, dict):
                    for name, spec in deps.items():
                        add(name, str(spec), "package.json")
        except (ValueError, OSError):
            pass

    gomod = repo / "go.mod"
    if gomod.exists():
        try:
            for line in gomod.read_text(encoding="utf-8", errors="replace").splitlines():
                m = re.match(r"\s*(?:require\s+)?([\w.\-/]+)\s+v?([0-9][\w.\-]*)", line)
                if m and "/" in m.group(1):
                    add(m.group(1).split("/")[-1], m.group(2), "go.mod")
        except OSError:
            pass

    return found


def manifest_packages(repo: Path) -> set[str]:
    return set(read_manifests(repo).keys())


def _version_tuple(v: str) -> Optional[tuple[int, ...]]:
    parts = []
    for chunk in re.split(r"[.\-+_]", v.strip()):
        if chunk.isdigit():
            parts.append(int(chunk))
        else:
            m = re.match(r"(\d+)", chunk)
            if not m:
                return None
            parts.append(int(m.group(1)))
            break
    return tuple(parts) if parts else None


def version_satisfies(claimed: str, spec: str) -> Optional[bool]:
    """Does `claimed` satisfy a manifest spec? None when undecidable."""
    spec = spec.strip().strip(",").strip()
    ct = _version_tuple(claimed)
    if ct is None:
        return None
    if spec in ("", "*"):
        return True
    m = re.match(r"(==|>=|<=|~=|\^|>|<)?\s*v?([0-9][\w.\-]*)", spec)
    if not m:
        return None
    op, sv = m.group(1) or "==", m.group(2)
    st = _version_tuple(sv)
    if st is None:
        return None
    n = max(len(ct), len(st))
    c = ct + (0,) * (n - len(ct))
    s = st + (0,) * (n - len(st))
    if op == "==":
        return c == s
    if op == ">=":
        return c >= s
    if op == "<=":
        return c <= s
    if op == ">":
        return c > s
    if op == "<":
        return c < s
    if op == "^":
        return c >= s and c[0] == s[0]
    if op == "~=":
        return c >= s and c[:2] == s[:2]
    return None


# --------------------------------------------------------------------------
# Individual checkers
# --------------------------------------------------------------------------

def check_file_exists(claim: Claim, ctx: CheckContext) -> RawCheck:
    path = claim.params["path"]
    expected = claim.params.get("expected_exists", True)
    target = ctx.repo / path
    exists = target.exists()
    ok = exists == expected
    return RawCheck(
        "pass" if ok else "fail",
        evidence={"path": path, "exists": exists, "expected_exists": expected},
        targets=[path] if exists else [],
    )


_DEF_PATTERNS = (
    r"\bdef\s+{n}\b",
    r"\bclass\s+{n}\b",
    r"\bfunction\s+{n}\b",
    r"\bfn\s+{n}\b",
    r"\bconst\s+{n}\b",
    r"\b{n}\s*=\s*(?:async\s+)?(?:function|\()",
)


def check_symbol_exists(claim: Claim, ctx: CheckContext) -> RawCheck:
    symbol = claim.params["symbol"]
    base = symbol.split(".")[-1]
    named_file = claim.params.get("file")
    files: list[Path]
    if named_file:
        f = ctx.repo / named_file
        if not f.exists():
            return RawCheck(
                "fail",
                evidence={"symbol": symbol, "file": named_file, "file_exists": False},
            )
        files = [f]
    else:
        files = iter_repo_files(ctx.repo, ctx.exclude)
    def_res = [re.compile(p.format(n=re.escape(base))) for p in _DEF_PATTERNS]
    ref_re = re.compile(r"\b" + re.escape(base) + r"\b")
    def_hits: list[str] = []
    ref_hits: list[str] = []
    for f in files:
        try:
            if f.stat().st_size > MAX_TEXT_FILE:
                continue
            text = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        rel = str(f.relative_to(ctx.repo)) if f.is_relative_to(ctx.repo) else str(f)
        if any(r.search(text) for r in def_res):
            def_hits.append(rel)
        elif ref_re.search(text):
            ref_hits.append(rel)
    if def_hits:
        return RawCheck(
            "pass",
            evidence={"symbol": symbol, "match_kind": "definition", "files": def_hits[:5]},
            targets=def_hits[:5],
        )
    if ref_hits:
        return RawCheck(
            "pass",
            evidence={"symbol": symbol, "match_kind": "reference-only", "files": ref_hits[:5]},
            targets=ref_hits[:5],
        )
    return RawCheck(
        "fail",
        evidence={"symbol": symbol, "match_kind": "absent", "files": []},
    )


def _discover_test_command(repo: Path) -> Optional[tuple[list[str], str]]:
    """Return (command, label) for the repo's own test suite, or None."""
    if (repo / "validate.py").exists():
        return [sys.executable, "validate.py"], "validate.py"
    has_pytest_cfg = (repo / "pytest.ini").exists() or (repo / "tox.ini").exists()
    if not has_pytest_cfg and (repo / "pyproject.toml").exists():
        try:
            data = tomllib.loads((repo / "pyproject.toml").read_text(encoding="utf-8"))
            has_pytest_cfg = "pytest" in ((data.get("tool") or {}))
        except (ValueError, OSError):
            pass
    test_files = list(repo.rglob("test_*.py")) + list(repo.rglob("*_test.py"))
    test_files = [t for t in test_files if ".git" not in t.parts and "node_modules" not in t.parts]
    import importlib.util

    if (has_pytest_cfg or test_files) and importlib.util.find_spec("pytest") is not None:
        return [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider"], "pytest"
    if test_files:
        start = "tests" if (repo / "tests").is_dir() else "."
        return [sys.executable, "-m", "unittest", "discover", "-s", start, "-t", "."], "unittest"
    if list(repo.rglob("*.test.js")) or list(repo.rglob("*.test.ts")):
        return ["npm", "test", "--silent"], "npm test"
    return None


def check_test_outcome(claim: Claim, ctx: CheckContext) -> RawCheck:
    expected = claim.params.get("expected", "pass")
    discovered = _discover_test_command(ctx.repo)
    if discovered is None:
        return RawCheck("unable", reason=model.R_NO_TEST_SUITE)
    cmd, label = discovered
    started = time.time()
    try:
        proc = subprocess.run(
            cmd,
            cwd=ctx.repo,
            capture_output=True,
            text=True,
            timeout=ctx.test_timeout,
        )
        exit_code: Optional[int] = proc.returncode
        tail = (proc.stdout + proc.stderr)[-800:]
    except subprocess.TimeoutExpired:
        return RawCheck(
            "unable",
            reason=model.R_CHECK_ERROR,
            evidence={"command": " ".join(cmd), "timeout_s": ctx.test_timeout},
        )
    except OSError as exc:
        return RawCheck(
            "unable", reason=model.R_CHECK_ERROR, evidence={"error": str(exc)}
        )
    tests_pass = exit_code == 0
    ok = tests_pass == (expected == "pass")
    test_targets = [
        str(p.relative_to(ctx.repo))
        for p in list(ctx.repo.rglob("test_*.py")) + list(ctx.repo.rglob("*_test.py"))
        if ".git" not in p.parts
    ][:50]
    return RawCheck(
        "pass" if ok else "fail",
        evidence={
            "runner": label,
            "command": " ".join(cmd),
            "exit_code": exit_code,
            "expected": expected,
            "duration_s": round(time.time() - started, 2),
            "output_tail": tail,
        },
        targets=test_targets,
    )


def check_dependency_version(claim: Claim, ctx: CheckContext) -> RawCheck:
    package = _norm_pkg(claim.params["package"])
    claimed = claim.params["version"]
    manifests = read_manifests(ctx.repo)
    hit = manifests.get(package)
    if hit is None:
        return RawCheck(
            "fail",
            evidence={
                "package": package,
                "claimed": claimed,
                "found_in": [],
                "note": "package not present in any manifest or lockfile in the repo",
            },
        )
    ok = version_satisfies(claimed, hit["spec"])
    if ok is None:
        return RawCheck(
            "unable",
            reason=model.R_AMBIGUOUS,
            evidence={"package": package, "claimed": claimed, "spec": hit["spec"]},
        )
    return RawCheck(
        "pass" if ok else "fail",
        evidence={
            "package": package,
            "claimed": claimed,
            "manifest_spec": hit["spec"],
            "manifest_file": hit["file"],
        },
        targets=[hit["file"]],
    )


def _flatten_json(obj: Any, prefix: str = "") -> dict[str, str]:
    out: dict[str, str] = {}
    if isinstance(obj, dict):
        for k, v in obj.items():
            key = f"{prefix}.{k}" if prefix else str(k)
            out.update(_flatten_json(v, key))
    elif isinstance(obj, (str, int, float, bool)):
        out[prefix] = str(obj)
    return out


def _find_config(repo: Path, key: str) -> Optional[tuple[str, str]]:
    """Return (value, filename) for a config key, or None."""
    candidates: list[Path] = []
    for pat in (".env", ".env.*", "*.ini", "*.cfg", "*.toml", "*.json", "*.yaml", "*.yml"):
        candidates.extend(sorted(repo.glob(pat)))
    candidates = [c for c in candidates if c.name not in ("package.json", "package-lock.json")]
    for f in candidates:
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if f.suffix == ".json":
            try:
                flat = _flatten_json(json.loads(text))
            except ValueError:
                continue
            for k, v in flat.items():
                if k == key or k.endswith("." + key) or k.split(".")[-1] == key:
                    return v, f.name
        elif f.suffix == ".toml":
            try:
                flat = _flatten_json(tomllib.loads(text))
            except ValueError:
                continue
            for k, v in flat.items():
                if k == key or k.endswith("." + key) or k.split(".")[-1] == key:
                    return v, f.name
        else:
            for line in text.splitlines():
                m = re.match(r"\s*" + re.escape(key) + r"\s*[:=]\s*\"?([^\"\s#]+)\"?", line)
                if m:
                    return m.group(1), f.name
    return None


def check_config_value(claim: Claim, ctx: CheckContext) -> RawCheck:
    key = claim.params["key"]
    claimed = str(claim.params["value"])
    found = _find_config(ctx.repo, key)
    if found is None:
        return RawCheck(
            "unable",
            reason=model.R_KEY_NOT_FOUND,
            evidence={
                "key": key,
                "claimed": claimed,
                "note": "no config file in the repo defines this key; "
                "absence is not proof (values may come from the environment)",
            },
        )
    actual, fname = found
    ok = actual == claimed
    if not ok:
        try:
            ok = float(actual) == float(claimed)
        except ValueError:
            ok = False
    return RawCheck(
        "pass" if ok else "fail",
        evidence={"key": key, "claimed": claimed, "actual": actual, "file": fname},
        targets=[fname],
    )


def _git(repo: Path, *args: str) -> Optional[str]:
    try:
        proc = subprocess.run(
            ["git", *args], cwd=repo, capture_output=True, text=True, timeout=15
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0:
        return None
    return proc.stdout.strip()


def check_git_state(claim: Claim, ctx: CheckContext) -> RawCheck:
    if _git(ctx.repo, "rev-parse", "--git-dir") is None:
        return RawCheck("unable", reason=model.R_NOT_A_GIT_REPO)
    kind = claim.params["kind"]
    expected = claim.params["expected"]
    if kind == "branch":
        actual = _git(ctx.repo, "branch", "--show-current") or ""
    elif kind == "head":
        actual_full = _git(ctx.repo, "rev-parse", "HEAD") or ""
        actual = actual_full.lower()
        ok = actual.startswith(expected)
        return RawCheck(
            "pass" if ok else "fail",
            evidence={"kind": kind, "expected": expected, "actual": actual_full},
        )
    elif kind == "worktree":
        status = _git(ctx.repo, "status", "--porcelain")
        actual = "clean" if status == "" else "dirty"
    else:
        return RawCheck("unable", reason=model.R_AMBIGUOUS)
    return RawCheck(
        "pass" if actual == expected else "fail",
        evidence={"kind": kind, "expected": expected, "actual": actual},
    )


def check_command_outcome(claim: Claim, ctx: CheckContext) -> RawCheck:
    command = claim.params["command"]
    if not ctx.run_commands:
        return RawCheck(
            "unable",
            reason=model.R_COMMANDS_DISABLED,
            evidence={
                "command": command,
                "note": "memreckon does not execute commands named by memories "
                "unless the operator passes --run-commands",
            },
        )
    expected_exit = claim.params.get("expected_exit", 0)
    try:
        proc = subprocess.run(
            command,
            cwd=ctx.repo,
            shell=True,
            capture_output=True,
            text=True,
            timeout=ctx.test_timeout,
        )
    except subprocess.TimeoutExpired:
        return RawCheck(
            "unable",
            reason=model.R_CHECK_ERROR,
            evidence={"command": command, "timeout_s": ctx.test_timeout},
        )
    ok = proc.returncode == expected_exit
    return RawCheck(
        "pass" if ok else "fail",
        evidence={
            "command": command,
            "exit_code": proc.returncode,
            "expected_exit": expected_exit,
            "output_tail": (proc.stdout + proc.stderr)[-800:],
        },
    )


CHECKERS = {
    model.FILE_EXISTS: check_file_exists,
    model.SYMBOL_EXISTS: check_symbol_exists,
    model.TEST_OUTCOME: check_test_outcome,
    model.DEPENDENCY_VERSION: check_dependency_version,
    model.CONFIG_VALUE: check_config_value,
    model.GIT_STATE: check_git_state,
    model.COMMAND_OUTCOME: check_command_outcome,
}
