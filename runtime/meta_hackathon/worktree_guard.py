"""Read-only Meta checkout gate to keep Muse/Codex off active Nebius work.

This module DOES NOT create a checkout, run an agent, call a model, modify
branches or grant Core capabilities. The owner must provide the exact intended
directory and a previously verified GitHub Meta commit SHA independently of
model output. A dedicated CLONE (not a git worktree) is mandatory.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
import subprocess

META_PROJECT_DISPLAY_NAME = "AIOA METAGuardiansSPARK"
META_PROJECT_BRANCH = "AIOA-METAGuardiansSPARK"
META_CHECKOUT_NAME = "aioa-sparkhat-meta"
ALLOWED_REMOTES = frozenset({
    "https://github.com/luciferprosun/AIOA-spArkHAT",
    "https://github.com/luciferprosun/AIOA-spArkHAT.git",
    "git@github.com:luciferprosun/AIOA-spArkHAT.git",
})
_SHA = re.compile(r"[0-9a-f]{40}\Z")


class MetaIsolationError(ValueError):
    """Constant error; do not echo paths, remote URLs or secrets."""

    def __init__(self) -> None:
        super().__init__("META_CHECKOUT_ISOLATION_DENIED")


@dataclass(frozen=True, slots=True)
class MetaCheckoutProof:
    """Observation only, NOT an owner warrant or execution capability."""

    root: str
    source_sha: str
    branch: str = META_PROJECT_BRANCH
    evidence_level: str = "LOCAL_GIT_READ_ONLY"

    @property
    def dispatch_allowed(self) -> bool:
        return False


def _git(root: Path, *args: str) -> str:
    """Read-only git diagnostics, never fetch/pull/checkout/reset."""
    try:
        result = subprocess.run(
            ["git", "--no-optional-locks", "-c", "core.fsmonitor=false",
             "-c", "core.hooksPath=/dev/null", "-C", str(root), *args],
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        )
        return result.stdout.strip()
    except (OSError, ValueError, subprocess.SubprocessError):
        raise MetaIsolationError() from None


def inspect_meta_checkout(
    requested_path: str | Path,
    *,
    owner_checkout_root: str | Path,
    expected_meta_sha: str,
) -> MetaCheckoutProof:
    """Fail closed unless THIS independent clean checkout is exactly the canonical Meta project branch.

    Must be called by a trusted host using an owner-managed directory and
    GitHub-pinned expected_meta_sha. The model cannot choose these values.
    This is only an isolation precheck, never permission to execute actions.
    """
    if (type(expected_meta_sha) is not str or _SHA.fullmatch(expected_meta_sha) is None
        or not isinstance(requested_path, (str, Path))
        or not isinstance(owner_checkout_root, (str, Path))):
        raise MetaIsolationError()
    try:
        requested = Path(requested_path).expanduser()
        expected = Path(owner_checkout_root).expanduser()
        if requested.is_symlink() or expected.is_symlink():
            raise MetaIsolationError()
        root = requested.resolve(strict=True)
        trusted_root = expected.resolve(strict=True)
    except (OSError, ValueError, RuntimeError):
        raise MetaIsolationError() from None
    if (not root.is_dir() or root != trusted_root
        or root.name.lower() != META_CHECKOUT_NAME
        or not (root / ".git").is_dir()
        or (root / ".git").is_symlink()):
        raise MetaIsolationError()

    if _git(root, "rev-parse", "--show-toplevel") != str(root):
        raise MetaIsolationError()
    if _git(root, "symbolic-ref", "--quiet", "--short", "HEAD") != META_PROJECT_BRANCH:
        raise MetaIsolationError()
    if _git(root, "remote", "get-url", "origin") not in ALLOWED_REMOTES:
        raise MetaIsolationError()
    actual_sha = _git(root, "rev-parse", "--verify", "HEAD")
    if actual_sha != expected_meta_sha:
        raise MetaIsolationError()
    if _git(root, "status", "--porcelain=v1", "--untracked-files=all"):
        raise MetaIsolationError()
    return MetaCheckoutProof(str(root), actual_sha)
