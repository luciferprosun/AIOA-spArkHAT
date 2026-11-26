# Disposable Noble qualification

The probes produce distinct receipts for host eligibility, Native role access, and a single G04 render. Only the existing Core admits and reconciles an operation. Retain each raw receipt in its own private 0700 directory under umask 077. Publish digests and outcomes. Each crash scenario that could publish needs a fresh authorized START.

## Host

Use an independently verified disposable x86-64 Noble image with the signed Noble archive snapshot pinned in `.github/workflows/nonzero-pr.yml`. Record the image digest at the hypervisor and retain signature verification and archive package hashes there. After boot, bind the VM instance, running kernel and SHA-256 of the trimmed Linux boot UUID to that observation through the trusted management channel. Obtain the expected source commit and tree independently of the guest. The admission operator and the host administrator must be able to review the complete manifest before executing any qualification action.

Fill a private copy of [the pin template](NOBLE_QUALIFICATION_PINS.json). Export a management receipt of schema `aioa.disposable-host-receipt.v1` with exactly `disposable: true`, `image_sha256`, `boot_sha256` and `signed_package_manifest_sha256` in addition to the schema. Pin its exact byte digest in the manifest. Authenticate the finalized manifest digest over a channel outside the VM. This relies on the operator to authenticate the management-plane export. The CLI performs digest comparison and measures the guest. It cannot verify the origin of a self-authored management receipt.

In a clean, immutable source checkout, run the read-only check as the unprivileged qualification operator. The broker roles should run in separate scoped services.

```sh
umask 077
python3 -B -m scripts.unification.noble_preflight \
  --manifest "$manifest" --manifest-sha256 "$trusted_digest" \
  --management-receipt "$management" > "$private/host.json"
```

A bare invocation without pins inventories the host and exits 2. `HOST_PINS_MATCHED` confirms the measured subset. Preserve the initial boot receipt, supervisor unit policies, package provenance and both host-side and in-cgroup observations alongside it.

## Native access

The private fixture is rooted at `/run/aioa-qualification/<32 lowercase hex>`. The supervisor must own the root, verify all parent directories and file types, and independently observe the preexisting files. Prepare `target.git/refs/heads/{qualification,sibling}`, `foreign/existing` and `broker/test-signing-key`. Use a synthetic key in a root-owned 0700 broker directory with a single-link broker-owned 0400 key file. The forbidden creation names must be absent. Record the key file's actual device and inode before dropping privileges. Pin the three distinct UID/GID pairs, exact cgroup memberships and enforcing AppArmor labels separately for each role. Place the probes at the same restriction level as the executable whose access they measure. The role probes inspect inherited state.

With the privileged supervisor integration installed after review, freeze the complete fresh Git clone at `/opt/aioa/native-qualification/<host.source>`. Require root ownership, read-only source for each role, no ignored files, no symlink substitutions and no group-write bits. Pin the exact source, installed supervisor, probe and preflight SHA-256 values. Place the externally authenticated manifest and management receipt in `/etc/aioa-native-qualification/manifest.json` and `management-receipt.json`. The operator launches each independently confined role unit at most once per session. Keep its stdout private.

```sh
/usr/bin/python3.12 -IBS /usr/local/libexec/aioa-native-role-supervisor.py \
  --role "$role" --manifest-sha256 "$trusted_digest"
```

Inside that unit the supervisor invokes `python3 -B -m scripts.unification.noble_role_probe` with the three host-pin arguments above and `--role core`, `--role broker` or `--role verifier`. Only the broker receives `--signer-fd N`, opened read-only by the trusted supervisor and closed immediately after the metadata check. The probes never read key bytes. Existing-file opens omit truncation. Each successful forbidden create is a failure that leaves its sentinel for review. ENOENT, ELOOP, EEXIST and an unexpected domain all invalidate the attempted observation.

Passing all three probes covers the listed accesses in the measured domains and boot. Capture positive publication separately through the normal Native task against the authorized ref, with independent witness verification, actor UIDs, source and original journal. Check alternate ref update strategies and directory topology when reviewing the actual confinement profile. Inspect both orderings of STOP, post-CAS/pre-witness crash, ACK loss, foreign same-OID attribution and repeated cold read. Verify one settlement for the original intent and zero redispatch only where the corresponding scope and evidence actually exist.

## G04

Prepare the fixed `scripts.unification.g04_qualification.recipe()` using the existing `prepare_html_render_sandbox` on the dedicated host. Review the closed runtime manifest including Python/Chrome, both executable and data files, kernel filters, keeper and profile. Pin `canonical_sha256(config.profile()['runtime'])` and the complete `config.profile_digest`. Authenticate the callback session's enrolled Core SPKI (SHA-256 of DER), original RENDER warrant digest and admitted session ID independently. Capture the prepared digests before the session, with a fresh scratch, journal and sealed source for this run. The historical fixture constructs an in-memory test principal and multiple warrants; keep it in the offline test lane.

Run the existing admitted operator integration under `aioa-g04-<32 lowercase hex>.service` in the delegated user app.slice with `PrivateNetwork=yes`, `NoNewPrivileges=yes` and `RuntimeMaxSec=180`. Enforce containment and cleanup at the supervisor, including the real keeper. The supervisor's 180 seconds cover the whole session. The Core operation and sandbox cap each render at 20 seconds. Keep the host timezone UTC and a single operator window of at most 30 minutes. Bind the fresh state and signing identity in the actual admitted Core session.

The host-side code holding the admitted principal and prepared step calls the existing Core.

```python
from scripts.unification.g04_qualification import execute_admitted

result = execute_admitted(
    validator, principal, step,
    manifest_path=manifest_path, manifest_sha256=trusted_digest,
    management_receipt=management_receipt,
)
```

`execute_admitted` checks host, unit, window, signer, warrant, session, recipe and measured sandbox profile before consuming the create-only local marker. It calls the existing Core `render` once. Preserve the original journal and marker after any uncertain result. A caller needs an actual admitted `PreparedValidationStep` and a durable, isolated Core host. A fixture principal or a JSON permit is insufficient for this operator acceptance. The existing CLI test fixture cannot provide these live inputs.

After the producer has exited, restart the same isolated Core store under the trusted supervisor. Its READ-only controller calls `cold_read(validator, read_principal, original_warrant_digest)` and privately exports the returned record. Keep the original raw broker `receipt.json` and DER SPKI exported as base64 text. The independent checker reads the following files.

```sh
python3 -B -m scripts.unification.g04_qualification \
  --manifest "$manifest" --manifest-sha256 "$trusted_digest" \
  --cold-record "$private/cold.json" --broker-receipt "$private/receipt.json" \
  --public-spki "$private/core.spki.b64"
```

The checker binds the signed Core record, original warrant, operation, session, actual broker receipt bytes, peer, cgroup and namespace evidence. It repeats the DOM/console/PNG oracle on the signed receipt's observation. Its success says nothing about the origin of a file claimed as cold export. Retain independent producer termination, verifier PID, restart and unchanged dispatcher count from the supervisor. A successful render alone cannot establish active STOP. For an admitted STOP scenario use the actual cancellation path while Chrome is active, retain the observed navigation and kernel cleanup receipt, and verify UNKNOWN by cold read with zero replay. Keep that case separate from the successful render. The accepted limit on sessions and warrants applies to both cases; obtain an additional bounded permit if a separate admitted run is needed.

`tests/nz13_render_acceptance.py` remains the multi-case synthetic fixture. The operator harness creates no new credentials, permits, services or AppArmor profiles. The host sponsor supplies a measured disposable Noble instance, authenticated pins and real Core admission. Until those items and the live receipts exist, report Native and G04 as NOT_RUN / BLOCKED_HOST.
