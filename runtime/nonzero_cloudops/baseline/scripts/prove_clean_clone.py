#!/usr/bin/env python3
"""Prove a fresh clone can install and run the public deterministic safety checks."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PUBLIC_REPOSITORY_URL = (
    "https://github.com/luciferprosun/AIOA-NonZero-CloudOps-Agent.git"
)
PHASE1_TAG = "phase1-foundation-green"
EXPECTED_PHASE1_TAG_COMMIT = "ced6e2a180dd50a1f43d4037bb8db5f4dc792657"
README_REQUIRED_COMMANDS = (
    f"git clone {PUBLIC_REPOSITORY_URL}",
    "cd AIOA-NonZero-CloudOps-Agent",
    "python3.12 -m venv .venv",
    '.venv/bin/python -m pip install ".[dev]"',
    ".venv/bin/python -m pytest -q",
    ".venv/bin/python scripts/run_p0_gate.py",
    ".venv/bin/python scripts/run_p1_gate.py",
    ".venv/bin/python scripts/build_reviewer_evidence_manifest.py --check",
    ".venv/bin/python scripts/validate_reviewer_evidence_manifest.py",
    ".venv/bin/python scripts/prove_clean_clone.py --mode auto",
    "python -m virtualenv",
)
SAFE_SMOKE_CHECKS = (
    "package_import",
    "p0_validate_only",
    "p1_validate_only",
    "evidence_manifest_build_check",
    "evidence_manifest_validation",
    "mocked_approved_e2e",
)
DEV_INSTALL_TIMEOUT_SECONDS = 900
_SHA_PATTERN = re.compile(r"[0-9a-f]{40}\Z")
_SCRUBBED_PREFIXES = (
    "AIOA_",
    "BEDROCK_",
    "GIT_",
    "IDLE_",
    "MODEL_",
    "PIP_",
    "PYTHON",
    "SANDBOX_",
    "SSH_",
)
_SCRUBBED_HOST_STATE = frozenset(
    {
        "BOTO_CONFIG",
        "APP_STAGE",
        "HOME",
        "NETRC",
        "PYTHONHOME",
        "PYTHONPATH",
        "STATE_TABLE_NAME",
        "VIRTUAL_ENV",
        "XDG_CONFIG_HOME",
    }
)


@dataclass(frozen=True, slots=True)
class ReproResult:
    status: str
    mode: str
    commit: str
    checks: tuple[str, ...]
    reasons: tuple[str, ...] = ()


class ReproFailure(RuntimeError):
    """Fixed-detail harness failure that never exposes a temporary local path."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


def _run(
    args: Sequence[str],
    *,
    cwd: Path,
    env: Mapping[str, str] | None = None,
    timeout_seconds: int = 300,
) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            list(args),
            cwd=cwd,
            env=None if env is None else dict(env),
            check=False,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(list(args), 124, stdout="", stderr="")
    except OSError:
        return subprocess.CompletedProcess(list(args), 126, stdout="", stderr="")


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return _run(("git", *args), cwd=root, timeout_seconds=30)


def current_commit(root: Path = ROOT) -> str:
    result = _git(root, "rev-parse", "HEAD")
    commit = result.stdout.strip()
    if result.returncode != 0 or _SHA_PATTERN.fullmatch(commit) is None:
        raise ReproFailure("HEAD_UNAVAILABLE")
    return commit


def validate_readme_contract(root: Path = ROOT) -> tuple[str, ...]:
    """Require every public setup/proof step used by the harness."""

    try:
        readme = (root / "README.md").read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return ("README_UNAVAILABLE",)
    reasons = [
        f"README_STEP_MISSING:{index}"
        for index, command in enumerate(README_REQUIRED_COMMANDS, start=1)
        if command not in readme
    ]
    positions = [readme.find(command) for command in README_REQUIRED_COMMANDS]
    if all(position >= 0 for position in positions) and positions != sorted(positions):
        reasons.append("README_STEP_ORDER_INVALID")
    lowered = readme.casefold()
    if "no aws credentials are required" not in lowered:
        reasons.append("README_NO_CREDENTIALS_SAFETY_MISSING")
    if "aws writes remain disabled" not in lowered:
        reasons.append("README_WRITES_DISABLED_SAFETY_MISSING")
    return tuple(reasons)


def sanitized_environment(base: Mapping[str, str]) -> dict[str, str]:
    """Remove AWS/provider/project authority inputs from clone smoke commands."""

    result = {
        key: value
        for key, value in base.items()
        if not key.startswith("AWS_")
        and key not in _SCRUBBED_HOST_STATE
        and not any(key.startswith(prefix) for prefix in _SCRUBBED_PREFIXES)
    }
    result["AWS_EC2_METADATA_DISABLED"] = "true"
    result["AWS_CONFIG_FILE"] = os.devnull
    result["AWS_SHARED_CREDENTIALS_FILE"] = os.devnull
    result["GIT_TERMINAL_PROMPT"] = "0"
    result["GIT_CONFIG_GLOBAL"] = os.devnull
    result["GIT_CONFIG_NOSYSTEM"] = "1"
    result["GIT_CONFIG_SYSTEM"] = os.devnull
    result["PIP_DISABLE_PIP_VERSION_CHECK"] = "1"
    result["PIP_CONFIG_FILE"] = os.devnull
    result["PIP_NO_CACHE_DIR"] = "1"
    result["PYTHONNOUSERSITE"] = "1"
    return result


def clone_command(mode: str, destination: Path, root: Path = ROOT) -> tuple[str, ...]:
    """Build a full-history clone command without collapsing a local feature HEAD to main."""

    if mode == "local-no-local":
        return ("git", "clone", "--quiet", "--no-local", str(root), str(destination))
    if mode == "remote-public":
        return (
            "git",
            "clone",
            "--quiet",
            "--branch",
            "main",
            "--single-branch",
            PUBLIC_REPOSITORY_URL,
            str(destination),
        )
    raise ValueError("mode must be local-no-local or remote-public")


def install_command(venv_python: Path) -> tuple[str, ...]:
    """Install the project and dev extra normally, never through editable local state."""

    return (str(venv_python), "-m", "pip", "install", ".[dev]")


def create_fresh_venv(
    destination: Path,
    *,
    cwd: Path,
    environment: Mapping[str, str],
) -> bool:
    """Create a fresh environment with stdlib venv or a bootstrap virtualenv fallback."""

    standard = _run(
        (sys.executable, "-m", "venv", str(destination)),
        cwd=cwd,
        env=environment,
    )
    if standard.returncode == 0:
        return True
    fallback = _run(
        (sys.executable, "-m", "virtualenv", str(destination)),
        cwd=cwd,
        env=environment,
    )
    return fallback.returncode == 0


def smoke_commands(venv_python: Path) -> tuple[tuple[str, ...], ...]:
    """Return only offline/deterministic project checks; P1 validate-only avoids recursion."""

    python = str(venv_python)
    return (
        (
            python,
            "-c",
            "import importlib.metadata; import aioa_cloudops_agent; "
            "assert importlib.metadata.version('strands-agents') == '1.53.0'",
        ),
        (python, "scripts/run_p0_gate.py", "--validate-only", "--json"),
        (python, "scripts/run_p1_gate.py", "--validate-only", "--json"),
        (python, "scripts/build_reviewer_evidence_manifest.py", "--check"),
        (python, "scripts/validate_reviewer_evidence_manifest.py"),
        (
            python,
            "-m",
            "pytest",
            "-q",
            "tests/integration/test_human_approved_remediation_e2e.py::"
            "test_full_mocked_approved_e2e_closes_only_with_independent_durable_evidence",
        ),
    )


def _select_mode(
    root: Path,
    requested: str,
    commit: str,
    environment: Mapping[str, str],
) -> str:
    if requested != "auto":
        return requested
    remote = _run(
        ("git", "ls-remote", PUBLIC_REPOSITORY_URL, "refs/heads/main"),
        cwd=root,
        env=environment,
        timeout_seconds=30,
    )
    remote_commit = remote.stdout.split(maxsplit=1)[0] if remote.stdout.strip() else ""
    if remote.returncode == 0 and remote_commit == commit:
        return "remote-public"
    return "local-no-local"


def validation_payload(root: Path = ROOT, *, requested_mode: str = "auto") -> ReproResult:
    reasons = list(validate_readme_contract(root))
    try:
        commit = current_commit(root)
    except ReproFailure as error:
        reasons.append(error.reason)
        commit = "0" * 40
    if requested_mode not in {"auto", "local-no-local", "remote-public"}:
        reasons.append("MODE_INVALID")
    return ReproResult(
        status="PASS" if not reasons else "FAIL",
        mode=requested_mode,
        commit=commit,
        checks=SAFE_SMOKE_CHECKS,
        reasons=tuple(sorted(set(reasons))),
    )


def prove_clean_clone(
    *,
    root: Path = ROOT,
    requested_mode: str = "auto",
    expected_commit: str | None = None,
) -> ReproResult:
    """Clone committed history outside the worktree, install, and run safe proof."""

    preflight = validation_payload(root, requested_mode=requested_mode)
    if preflight.status != "PASS":
        return preflight
    commit = preflight.commit
    if expected_commit is not None and (
        _SHA_PATTERN.fullmatch(expected_commit) is None or expected_commit != commit
    ):
        return ReproResult(
            status="FAIL",
            mode=requested_mode,
            commit=commit,
            checks=SAFE_SMOKE_CHECKS,
            reasons=("EXPECTED_COMMIT_MISMATCH",),
        )
    status = _git(root, "status", "--porcelain")
    if status.returncode != 0 or status.stdout:
        return ReproResult(
            status="FAIL",
            mode=requested_mode,
            commit=commit,
            checks=SAFE_SMOKE_CHECKS,
            reasons=("SOURCE_WORKTREE_NOT_CLEAN",),
        )
    environment = sanitized_environment(os.environ)
    with tempfile.TemporaryDirectory(prefix="aioa-clean-clone-") as temporary:
        temporary_root = Path(temporary)
        if temporary_root == root or root in temporary_root.parents:
            raise ReproFailure("TEMPORARY_ROOT_UNSAFE")
        isolated_home = temporary_root / "home"
        isolated_home.mkdir()
        environment["HOME"] = str(isolated_home)
        environment["XDG_CONFIG_HOME"] = str(isolated_home / ".config")
        mode = _select_mode(root, requested_mode, commit, environment)
        clone_root = temporary_root / "repo"
        clone = _run(clone_command(mode, clone_root, root), cwd=temporary_root, env=environment)
        if clone.returncode != 0:
            raise ReproFailure("CLONE_FAILED")
        if mode == "local-no-local":
            checkout = _git(clone_root, "checkout", "--quiet", "--detach", commit)
            if checkout.returncode != 0:
                raise ReproFailure("CLONED_COMMIT_MISMATCH")
        cloned_commit = current_commit(clone_root)
        if cloned_commit != commit:
            raise ReproFailure("CLONED_COMMIT_MISMATCH")
        shallow = _git(clone_root, "rev-parse", "--is-shallow-repository")
        if shallow.returncode != 0 or shallow.stdout.strip() != "false":
            raise ReproFailure("CLONE_HISTORY_SHALLOW")
        phase1_tag = _git(clone_root, "rev-parse", f"{PHASE1_TAG}^{{}}")
        if (
            phase1_tag.returncode != 0
            or phase1_tag.stdout.strip() != EXPECTED_PHASE1_TAG_COMMIT
        ):
            raise ReproFailure("PHASE1_TAG_DRIFT")
        clean = _git(clone_root, "status", "--porcelain")
        if clean.returncode != 0 or clean.stdout:
            raise ReproFailure("CLONED_WORKTREE_NOT_CLEAN")
        venv_root = temporary_root / "venv"
        created = create_fresh_venv(
            venv_root,
            cwd=temporary_root,
            environment=environment,
        )
        if not created:
            raise ReproFailure("VENV_CREATE_FAILED")
        venv_python = venv_root / "bin" / "python"
        installed = _run(
            install_command(venv_python),
            cwd=clone_root,
            env=environment,
            timeout_seconds=DEV_INSTALL_TIMEOUT_SECONDS,
        )
        if installed.returncode != 0:
            raise ReproFailure("DEV_INSTALL_FAILED")
        for index, command in enumerate(smoke_commands(venv_python), start=1):
            proof = _run(command, cwd=clone_root, env=environment)
            if proof.returncode != 0:
                raise ReproFailure(f"SAFE_SMOKE_{index}_FAILED")
    return ReproResult(
        status="PASS",
        mode=mode,
        commit=commit,
        checks=SAFE_SMOKE_CHECKS,
    )


def _emit(result: ReproResult, *, as_json: bool) -> None:
    payload = asdict(result)
    if as_json:
        print(json.dumps(payload, sort_keys=True, separators=(",", ":")))
        return
    reasons = ",".join(result.reasons) if result.reasons else "-"
    print(
        f"CLEAN_CLONE {result.status} mode={result.mode} commit={result.commit} "
        f"checks={len(result.checks)} reasons={reasons}"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--mode",
        choices=("auto", "local-no-local", "remote-public"),
        default="auto",
    )
    parser.add_argument("--expected-commit")
    parser.add_argument("--validate-only", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    try:
        result = (
            validation_payload(requested_mode=args.mode)
            if args.validate_only
            else prove_clean_clone(
                requested_mode=args.mode,
                expected_commit=args.expected_commit,
            )
        )
    except ReproFailure as error:
        result = ReproResult(
            status="FAIL",
            mode=args.mode,
            commit="0" * 40,
            checks=SAFE_SMOKE_CHECKS,
            reasons=(error.reason,),
        )
    _emit(result, as_json=args.json)
    return 0 if result.status == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
