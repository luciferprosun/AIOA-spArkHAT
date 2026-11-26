# RH-07 Noble qualification runbook

**BLOCKED_HOST / NOT_RUN.** Linux Mint fixture results do not qualify Noble.
This is a host-operator packet for an independent review. No privileged
workflow was added or run.

## Owner checklist

- Require the approved STOP contract and independent security/platform review
  before deploying any privileged harness.
- Use a short-lived Ubuntu 24.04 Noble x86_64 VM or dedicated runner with a
  pinned image digest, signed package snapshot and verified approved commit.
  Record expected source SHA, tree, kernel, image identifier, package versions
  and binary digests from a trusted manifest before test launch.
- Use a manual trusted-owner lane only. Use a read-only repository token, no
  persisted checkout credentials, no PR-controlled privileged setup, no
  deployment secrets and no writable production repositories.
- Use disposable Core, broker, verifier and supervisor identities and new
  synthetic keys. Deny network after preflight. Control the sequencer state
  mount, key aperture, signer FD, immutable ref-parent ancestors and verifier
  read-only view. Confirm exact-ref OS policy before granting release.
- Qualify the separate identities and record actual denial codes for Core key
  access and writes to the protected ref, broker writes to sibling and other
  paths, and verifier writes. Establish independently that the approved ref
  can be created under the same policy. Confirm broker enrollment and fresh
  signed verifier response using only public material at Core.

## Safe initial commands on the pre-authorized disposable host

Run manually from the reviewed checkout with pinned tooling. These commands
establish source/host identity and same-UID regression only. The current
fixture broker deliberately rejects a different Core UID. There is no command
here to provision users, enable a privileged workflow or bypass that refusal.

```sh
set -eu
test "$(git rev-parse HEAD)" = "${RH07_APPROVED_SHA:?trusted manifest SHA required}"
test "$(git rev-parse HEAD^{tree})" = "${RH07_APPROVED_TREE:?trusted manifest tree required}"
test -z "$(git status --porcelain)"
. /etc/os-release
test "$ID/$VERSION_ID/${VERSION_CODENAME:-}" = ubuntu/24.04/noble
test "$(uname -m)" = x86_64
test "$(dpkg --print-architecture)" = amd64
uname -r
sha256sum /usr/bin/git /usr/bin/bwrap
dpkg-query -W git bubblewrap python3 libc6 libpcre2-8-0
stat -fc '%T' /sys/fs/cgroup
PYTHONPATH=.:tests python3 -B -m unittest -v test_redhat_rh07_sequence
```

Stop if the observed profile or installed package/binary digests differ from
the reviewed manifest. The command output does not attest the hypervisor
image. The operator supplies its independently verified digest.
After reviewed supervisor/route/policy implementation is available, exercise
the normal Native apply route with one fresh START per trial. Inject STOP
before grant, Core revoke after export and before link, STOP while publisher
owns the slot, broker death before witness, loss of ACK after witness, and a
same-OID foreign inode. Verify cold-process original intent settlement and
revision changes. Record the exact SHA/tree, role UIDs/GIDs, observable
ordering, release/attempt IDs only as digests, one-link/settlement counters,
failures, and sanitized denial evidence. Archive no secrets, raw machine
identity, credentials, or private-key contents.
