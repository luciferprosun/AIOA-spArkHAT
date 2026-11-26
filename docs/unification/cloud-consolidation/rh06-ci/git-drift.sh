#!/usr/bin/env bash
# Use only on a disposable test checkout. ROOT is a clean base or PR checkout.
set -euo pipefail
umask 077
root=$(realpath "${1:?supply checkout}")
scratch=$(mktemp -d)
trap 'rm -rf -- "$scratch"' EXIT
# An ELF executable still runs with an extra trailing byte. Only the private
# mount namespace observes these different bytes at the fixed broker path.
cp /usr/bin/git "$scratch/git"
printf '\0' >> "$scratch/git"
chmod 0555 "$scratch/git"
sha256sum /usr/bin/git "$scratch/git"
bwrap --unshare-all --die-with-parent --new-session --cap-drop ALL --clearenv \
  --setenv PATH /usr/bin:/bin --setenv HOME /tmp --setenv LANG C.UTF-8 \
  --setenv PYTHONPATH /app:/app/tests --setenv PYTHONDONTWRITEBYTECODE 1 \
  --setenv GIT_CONFIG_NOSYSTEM 1 --setenv GIT_CONFIG_GLOBAL /dev/null \
  --ro-bind /usr /usr --symlink usr/bin /bin --symlink usr/lib /lib --symlink usr/lib64 /lib64 \
  --ro-bind /etc/ld.so.cache /etc/ld.so.cache --dev /dev --proc /proc --tmpfs /tmp \
  --dir /app --ro-bind "$root/lab" /app/lab --ro-bind "$root/runtime" /app/runtime --ro-bind "$root/tests" /app/tests \
  --ro-bind "$scratch/git" /usr/bin/git --chdir /app -- /usr/bin/python3 -B - <<'PY'
import hashlib
import os
from pathlib import Path
import subprocess
import tempfile
from runtime.mission.git_publish import LOCAL_GIT_SHA256
from runtime.mission.sandbox_linux import LinuxSandboxBroker
from runtime.mission.warrant import WarrantError

actual = hashlib.sha256(Path("/usr/bin/git").read_bytes()).hexdigest()
assert actual != LOCAL_GIT_SHA256
with tempfile.TemporaryDirectory() as repo:
    subprocess.run(["/usr/bin/git", "init", "--bare", "--template=", "--quiet", repo], check=True)
    fd = os.open(repo, os.O_RDONLY | os.O_DIRECTORY)
    try:
        LinuxSandboxBroker._git_plumbing(fd, ("rev-parse", "--is-bare-repository"), git_sha256=LOCAL_GIT_SHA256)
    except WarrantError as exc:
        if str(exc) != "GIT_RUNTIME_CHANGED":
            raise
        print("PASS GIT_RUNTIME_CHANGED", "expected", LOCAL_GIT_SHA256, "actual", actual)
    else:
        raise AssertionError("Changed runtime accepted")
    finally:
        os.close(fd)

# Capture the unmodified RH-04 tests' actual outcomes in the mismatched view.
# These two outcomes are failures of the lock tests, even though the guard worked.
import unittest
prefix = "test_redhat_rh04_native_task_gate.RedHatRH04Tests."
parent = prefix + "test_git_plumbing_parent_replacement_is_rejected_before_lock_creation"
cleanup = prefix + "test_git_plumbing_v3_ref_link_ack_cleans_both_git_locks"
suite = unittest.defaultTestLoader.loadTestsFromNames([parent, cleanup])
result = unittest.TestResult()
suite.run(result)
for test, trace in result.failures + result.errors:
    print(test.id(), trace)
assert [test.id() for test, trace in result.failures] == [parent]
assert [test.id() for test, trace in result.errors] == [cleanup]
assert '"GIT_STORAGE_CHANGED" does not match "GIT_RUNTIME_CHANGED"' in result.failures[0][1]
assert result.errors[0][1].rstrip().endswith("WarrantError: GIT_RUNTIME_CHANGED")
print("mismatched RH-04 tests: 0 PASS, 1 FAIL, 1 ERROR, 0 SKIP")

PY
