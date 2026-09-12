# AIOA — PORTABLE B4
# RELIABILITY + SECURITY + EVIDENCE HARDENING

## Identity

PROJECT=AIOA / AIOA-NonZero-CloudOps-Agent
REPO=/media/l/LSC_DATA/AWS_HACKATHON/AIOA-NonZero-CloudOps-Agent
BRANCH=codex/portable-b4-reliability-security-evidence
HEAD_BEFORE=99bad78c7a2b35132094ccbd7b8bb8a7eb7d83f1
HEAD_AFTER=0cb0fe15f245e9df6f46d937a69b5a8305e4f3bf
WORKTREE=CLEAN
RUN_DATE=2026-09-01
TIMEZONE=Europe/Berlin
AUDITED_AT=2026-09-01T13:28:07+02:00

`HEAD_AFTER` is the exact implementation and evidence head used for the final 1409-test regression,
P0, P1 clean-clone proof, B4 attack gate, package build, security checks, portable demo, and manual
loopback API exercise. A documentation-only commit containing this report and the B5 preflight
follows that audited head; this avoids an impossible self-referential report commit hash.

## Previous Gate

B3_CONFIRMED=PASS
BASELINE_TESTS=1328/1328 PASS; 0 failed; 0 skipped; 0 xfailed; 1239.46s

The reported B3 state was not trusted blindly. The branch, clean worktree, remote, toolchain,
architecture, prior audits, and all 1328 baseline tests were re-attested before B4 changes.

## Reliability

STATE_MACHINE_HARDENING=PASS
CRASH_RECOVERY=PASS
PARTIAL_WRITE_PROTECTION=PASS
IDEMPOTENCY=PASS
REPLAY_PROTECTION=PASS
CONCURRENCY_DUPLICATE_PROTECTION=PASS

- Invalid workflow transitions remain typed and fail closed. Tests cover denied-to-executing,
  failed-to-verified, verified-to-executing, and exact approved-action binding.
- Critical local truth and sandbox inventory use separate typed, versioned SHA-256 envelopes. Reads
  reject duplicate keys, non-finite JSON values, unknown envelopes, truncation, oversized files,
  unsafe permissions, hard-link aliases, and symlinked files or parents.
- Writes use an owner-only temporary file, flush, `fsync`, atomic replace, and parent-directory
  `fsync`, under a file lock. State plus checkpoint/audit/mutation-count reads use one locked
  snapshot rather than a torn multi-read sequence.
- Controlled interruptions were exercised before and after proposal/approval/mutation/verification
  boundaries. A lost receipt immediately after mutation leaves `EXECUTING`; restart reconciles the
  durable inventory receipt without issuing a second mutation.
- Sixteen simultaneous identical resume requests produced at most one authorized sandbox mutation.
- In-memory run/event/restore sizes, HTTP request bodies and headers, request concurrency, and
  provider test behavior are bounded; no retry loop was made unbounded.

## Human Authority

APPROVAL_BINDING=PASS
APPROVAL_TAMPER_PROTECTION=PASS
STALE_APPROVAL_PROTECTION=PASS
CROSS_RUN_APPROVAL_PROTECTION=PASS
DENY_ZERO_MUTATION=PASS

Approval remains bound to the exact run, proposal, proposal version, proposal hash, evidence hash,
decision request, action, resource type, resource identifier, and idempotency key. Missing,
malformed, expired, unknown, replayed, cross-run, cross-proposal, changed-target, changed-action,
and changed-argument decisions fail closed. Provider/model output still has no execution authority.

## Evidence

EVIDENCE_SCHEMA=PASS
EVIDENCE_INTEGRITY=PASS
TAMPER_DETECTION=PASS
SECRET_REDACTION=PASS
TRACE_LINKAGE=PASS
JUDGE_TIMELINE=PASS

- Judge evidence uses an explicit versioned view, stable ordering, snapshot digest, total/truncated
  event accounting, run/proposal/approval/action/verification references, final state, and mutation
  count.
- Proposal, approval, result, deletion, reordering, resource state, verification, envelope, and
  hash-linked-content tampering are rejected by schema or integrity validation.
- Run, trace, correlation, proposal, checkpoint, decision, receipt, and verification linkage is
  preserved through restart and recovery.
- Judge events distinguish `FACT`, `AGENT_INFERENCE`, `POLICY_DECISION`, `HUMAN_DECISION`, `ACTION`,
  `VERIFICATION`, and `RECOVERY` without hiding the raw bounded audit evidence.
- Evidence and judge-facing outputs redact AWS/OpenAI/GitHub-like keys, bearer and authorization
  values, passwords, tokens, secrets, cookies, credential-bearing URLs, private-key material, and
  sensitive local path values. The final repository scan examined 363 files and emitted zero findings or
  secret values.

## Provider Safety

PROVIDER_TIMEOUT_SAFE=PASS
PROVIDER_ERROR_SAFE=PASS
MALFORMED_OUTPUT_SAFE=PASS
MODEL_HAS_MUTATION_AUTHORITY=NO

The deterministic provider matrix covers timeout, connection failure, rate limit, unavailable
model, configuration failure, exception, empty/truncated output, malformed output, and invalid
structured output. Each path is explicit, creates no proposal authority, and cannot reach the
mutation boundary.

## Input / Configuration Security

INPUT_VALIDATION=PASS
PATH_TRAVERSAL_PROTECTION=PASS
CONFIG_VALIDATION=PASS
SECRET_HANDLING=PASS

The loopback API rejects query ambiguity, unknown routes and methods, malformed JSON, invalid UUIDs,
unknown enums/fields, oversized bodies/headers, and unsafe decisions. Runtime mode, provider, local
mode, numeric limits, TTL, and persistence paths are validated. State, inventory, token, and receipt
paths reject traversal outside their configured root where applicable, symlinked ancestors,
non-regular files, unsafe modes, and state/inventory aliases. Portable deterministic startup still
requires no paid-provider credential.

## Portable Safety

AWS_CALLS=0
AWS_MUTATIONS=0
EXTERNAL_NETWORK_CALLS=0
EXTERNAL_DEPLOYMENTS=0
REMOTE_PUSHES=0

All B4 proof subprocesses ran with AWS credential selectors removed and a fail-closed socket guard
that permits only loopback and Unix-domain traffic. The canonical deterministic demo and the actual
loopback product interface both reported zero provider/AWS/external-network calls.

## Golden Scenarios

APPROVE_NORMAL=PASS
DENY_NORMAL=PASS
RECOVERY_AFTER_INTERRUPTION=PASS
REPLAY_REJECTED=PASS
APPROVAL_TAMPER_REJECTED=PASS
EVIDENCE_TAMPER_DETECTED=PASS
PROVIDER_FAILURE_SAFE=PASS
INVALID_INPUT_REJECTED=PASS
CORRUPTED_STATE_SAFE_FAILURE=PASS
SECRET_REDACTION_PASS=PASS
NETWORK_EGRESS_ZERO=PASS

`scripts/run_b4_hardening_gate.py` passed 11/11 scenarios and 43 focused proof cases at
`HEAD_AFTER`. Its private owner-only receipt is stored under `.local/b4/` and is intentionally not
committed. Receipt content digest: `936d3996f4670502f3d5a137ff331576e04425e6e71177f727ce07c71a602d1d`.

## Regression

TEST_TOTAL=1409
TEST_PASS=1409
TEST_FAIL=0
TEST_SKIP=0
TEST_XFAIL=0
TEST_DURATION=723.04s
BASELINE_COMPARISON=+81 passing tests; no test removed, skipped, or converted to xfail

P0=PASS 15/15 gates; 136 proof tests; 0 skipped
P1=PASS 6/6 gates; 93 proof tests; 0 skipped; clean clone PASS

LINT=PASS (`ruff check .`)
FORMAT_CHECK=NO_REPOSITORY_FORMATTER_CONFIG; Ruff and `git diff --check` PASS
PACKAGE_CHECK=PASS (`aioa_nonzero_cloudops_agent-0.2.0rc1-py3-none-any.whl`)
PACKAGE_SHA256=0d4f0b33e9fe9461d70f446b494277f8de690147dc907aea0ed8fcec10189560
PIP_CHECK=PASS (no broken requirements)
SECRET_SCAN=PASS (363 files; 0 findings; no secret values emitted)
TYPECHECK=NOT_CONFIGURED (no mypy/pyright dependency or repository configuration)
GIT_DIFF_CHECK=PASS
JS_SYNTAX_CHECK=PASS (`node --check` on the embedded judge script)
GENERATED_EVIDENCE_CHECK=PASS (28 claims; 0 live receipts)
FINAL_DOC_SENSITIVE_CHECK=PASS (135/135 tests; 996.44s)
B4_ATTACK_GATE=PASS (11/11 scenarios; 43 proof tests)
PORTABLE_E2E=PASS
MANUAL_LOCAL_API=PASS (`scripts/run_local_hitl_api.py`; health/readiness, approve, deny, replay)

The first post-change full regression produced 1402 passes and seven failures. They exposed only
proof-artifact alignment defects: synthetic redaction fixtures were visible to the repository
scanner, two historical proof labels had drifted, and the offline verifier receipt still used the
pre-integrity-envelope digest. The fixtures were assembled at runtime without weakening the scan,
historical labels were preserved, and the verifier receipt was regenerated through its hardened
private writer. A targeted 33-test rerun and then the complete 1409-test suite passed.

## Files

FILES_ADDED=9 (7 at audited `HEAD_AFTER`, plus this audit and the B5 preflight in the final docs-only commit)
FILES_MODIFIED=42

The audited implementation changed 49 files: 7 added and 42 modified, with 2296 insertions and 256
deletions. No dependency declaration, lock input, workflow, remote URL, or deployment configuration
was changed.

## Commits

COMMITS=

- `7c7bb6d25c2ec600926340ebd740fc7c9c7e900e` — `feat(reliability): harden local recovery and authority`
- `29c6e6de9dacc9eb815817360391008c0894607e` — `feat(security): harden judge API and evidence surface`
- `a455379eb3de73bf6c1780b3c4726b0778873dd4` — `test(hardening): add deterministic B4 attack gate`
- `38cb8990302777c8e544dce579d9a961ef80a8b9` — `docs(evidence): reanchor B4 hardening proofs`
- `dfcea99c893b102d63208566d4ac8a84a60fe5fc` — `test(hardening): enforce zero egress across B4 gate`
- `4f4bf62087236777da1bbe6a2b3de7c212c7995d` — `docs(security): document portable B4 hardening`
- `0cb0fe15f245e9df6f46d937a69b5a8305e4f3bf` — `fix(hardening): align scanners and verifier evidence`

The final documentation-only attestation commit follows the audited implementation head and is not
listed by hash inside itself.

## Known Limitations

- Local SHA-256 envelopes detect corruption and uncoordinated tampering, but they are not keyed
  signatures or an externally anchored ledger. A host-privileged attacker able to rewrite both data
  and digest remains outside this local judge-mode threat model.
- Pre-B4 unsealed local truth/inventory files intentionally fail closed rather than being silently
  migrated. Operators must select fresh paths; the old files are preserved.
- The product is a loopback, single-operator judge runtime, not a public multi-tenant service.
- No static type checker or repository-wide formatter is configured. B4 did not add dependency
  churn solely for those checks.
- Container freeze and clean-container execution are deliberately deferred to B5. Neither Docker
  nor Podman is currently available on this host, so B5 will require an authorized local container
  engine before its build gate can pass.

## Final Gate

B4=PASS

The final diff audit found no new broad exception swallowing, silent `None` success, unbounded retry,
model-to-mutation path, approval bypass, replay bypass, unsafe shell execution, dependency addition,
credential, AWS coupling, remote change, deployment action, or debug artifact.

## Next Step

B5 — BUILD-COMPLETE PORTABLE RELEASE CANDIDATE

Freeze and prove one platform-neutral, non-root container artifact from a clean clone. Do not deploy,
publish, or push before `BUILD_COMPLETE=PASS`.
