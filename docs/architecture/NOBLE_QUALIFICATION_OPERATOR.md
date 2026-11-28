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

The private fixture is rooted at `/run/aioa-qualification/<32 lowercase hex>`. The supervisor must own the root, verify all parent directories and file types, and independently observe the preexisting files. Use the same `repo` directory, `refs/heads/aioa` parent, and `exact_ref` as the permitted operation. Pin device and inode for both directories. The authorized leaf is `nz11-<first 32 hex digits of capsule digest>` and must be absent before CAS. For the existing sibling sentinel, XOR the final 128-bit hexadecimal suffix with 1. Leave the three sibling suffixes formed by XOR with 2, 3 and 4 absent (Core, broker, verifier, respectively). Prepare `foreign/existing` and `broker/test-signing-key`. Use a synthetic key in a root-owned 0700 broker directory with a single-link broker-owned 0400 key file. The forbidden creation names and the exact ref lock must be absent. Record actual successful verifier readback separately after CAS. Record the key file's actual device and inode before dropping privileges. Pin the three distinct UID/GID pairs, exact cgroup memberships and enforcing AppArmor labels separately for each role. Place the probes at the same restriction level as the executable whose access they measure. The role probes inspect inherited state.

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

## Native S1 V2 operator kit

Use the exact detached source and offline wheelhouse from the V2 evidence
bundle. Verify its `SHA256SUMS` against the digest delivered by the owner.
The source archive preserves the tested commit and tree. Extract that
archive and the wheelhouse to root-controlled directories on the approved
disposable guest. The installer checks the frozen Git tree, exact Noble
runtime pins and wheel lock. Existing installation files cause refusal.

From the approved guest console, supply the archive path and digest obtained
independently from the package owner. Use a fresh staging directory.

```sh
printf '%s  %s\n' "$trusted_kit_sha256" "$kit_archive" | sha256sum -c -
sudo install -d -m 0700 /opt/aioa-native-s1-kit
sudo tar --no-same-owner -xzf "$kit_archive" -C /opt/aioa-native-s1-kit
sudo sh -c 'cd /opt/aioa-native-s1-kit/native69-s1-v2 && sha256sum -c SHA256SUMS'
sudo tar --no-same-owner -xzf /opt/aioa-native-s1-kit/native69-s1-v2/detached-source.tar.gz \
  -C /opt/aioa-native-s1-kit
sudo git -C /opt/aioa-native-s1-kit/source show -s --format='%H %T' HEAD
```

Compare both values to `SOURCE.json` through the independent package channel.
Use `/opt/aioa-native-s1-kit/native69-s1-v2/wheelhouse` for the install input.
The installation command below runs with the restored source as its working directory.
The management workstation can separately extract the archive for receipt and manifest generation.

The management operator independently selects the signed image and package
manifest, confirms the guest instance is disposable and disconnects guest
egress via the trusted management plane. The external channel supplies
the image digest, signed package manifest digest, and the measured boot
digest for that instance. For the boot digest, the management-side console
or attested guest integration measures the actual boot ID without its final
newline and hashes those ASCII bytes. A digest obtained from an uncontrolled
guest by itself is insufficient. Verify the package manifest signature
against the provisioner's trusted public key before deriving the manifest
digest. Transport the receipt and trusted manifest digest independently.

The guest can measure the Python snapshot input. The management operator
must review it against the approved guest and pinned packages before
including its digest in the allowed manifest. Use an absolute output path.

```sh
sudo sh -c 'cd /opt/aioa-native-s1-kit/source && exec /usr/bin/python3.12 -IBS "$@"' aioa-s1 \
  -c 'import runpy,sys; sys.path.insert(0,"."); runpy.run_module("scripts.unification.native_s1",run_name="__main__")' \
  measure-runtime --output "$runtime_path"
```

From the management workstation's extracted checkout, using the externally verified digests
and the exact feature/integration identity in the kit:

```sh
PYTHONPATH=. python3 -B -m scripts.unification.native_s1 management-receipt \
  --image "$approved_image_sha256" --boot "$approved_boot_sha256" \
  --signed-packages "$verified_package_manifest_sha256" --output management.json
PYTHONPATH=. python3 -B -m scripts.unification.native_s1 manifest \
  --source "$tested_sha" --tree "$tested_tree" --kernel "$approved_kernel" \
  --receipt management.json --runtime-digest "$approved_runtime_sha256" \
  --wheels-digest "$kit_wheel_lock_sha256" --core-uid "$approved_console_uid" \
  --output manifest.json
```

The utility serializes these inputs. It does not authenticate their origin.
Use an authorized fresh Core user on the guest, with an active local
seat0 login and normal polkit approval. Include the product-pinned system
packages, AppArmor, compiler, libseccomp, `python3-pip`, `iproute2`, systemd
and polkit in the approved package provisioning. The service runner expects
only the loopback interface up, in addition to the management egress gate.

Install from the authenticated, unpacked, root-owned source and wheelhouse:

```sh
sudo sh -c 'cd /opt/aioa-native-s1-kit/source && exec /usr/bin/python3.12 -IBS "$@"' aioa-s1 -c \
  'import runpy,sys; sys.path[:0]=[".","/usr/lib/python3/dist-packages"]; runpy.run_module("scripts.unification.native_s1",run_name="__main__")' \
  install --manifest "$manifest_path" --manifest-sha256 "$trusted_manifest_digest" \
  --management-receipt "$management_path" --runtime "$runtime_path" --wheelhouse "$wheelhouse"
```

Use the Core user's real local console on seat0 for the following commands.
Running in a user service or over SSH fails admission. The CLI registers
a TTY polkit agent for each Core PID/start time. Complete the ordinary
polkit prompts. The per-aperture CA enables the existing loopback TLS 1.3
challenge from that process only. The Core observes the original authority
and never exports writable authority to the verifier. The delegated unit
and all four roles share the mount namespace. The Core stays in its
actual login scope and requires an active delegated user manager. The Core
profile grants the system and session D-Bus calls used by admission and the
existing validation worker. That worker's artifacts, work and tmp mounts
and bootstrap executable may be inspected through a unique read-only alias.
No other S1 service has the disconnected-path setting. The two Git launcher
tools use checked, root-owned connected descriptors in the S1 Core domain.
All Git inputs and the Git executable supplied to the child remain sealed,
with a read-only mount and the existing seccomp policy. Confirm this branch
of the policy with the kernel during P1, including both the Git child and
the distinct systemd user validation worker. The other roles drop capabilities,
apply their exact AppArmor domains and then install the post-bootstrap syscall filter.

```sh
sudo /usr/local/libexec/aioa-native-s1 preflight --manifest-sha256 "$trusted_manifest_digest"
sudo /usr/local/libexec/aioa-native-s1 run --manifest-sha256 "$trusted_manifest_digest" P1
sudo /usr/local/libexec/aioa-native-s1 matrix --manifest-sha256 "$trusted_manifest_digest"
sudo /usr/local/libexec/aioa-native-s1 collect --session "$observed_case_session" \
  --output "$private_output/native-s1-case.tar.gz"
```

Read `operator/case.json` and verify `sha256sum -c SHA256SUMS` after
extracting the private case archive. It excludes private keys, raw
SQLite and role logs. Retain these separately in trusted guest custody
if the independent reviewer requires them. Copy retained evidence before
ending the guest boot. The scope is same-boot S1. `PASS` needs the
expected observed counters and verification. `FAIL` means the run did
not meet an assertion or a scenario failed to start after host acceptance.
`BLOCKED_HOST` indicates a rejected prerequisite before effect.
`NOT_RUN` means required scenario evidence is unavailable. I1 reports the
synthetic HELD isolation measurement separately from the original historical
retention, which needs its own authorized read-only evidence. `matrix` reports
an incomplete acceptance when that evidence is absent. Production stays separate.
