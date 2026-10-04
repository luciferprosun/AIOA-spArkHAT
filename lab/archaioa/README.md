# NEBIUS ArchAIOA PRE-01: PCAF pure contracts lab

CONTRACT / FIXTURE evidence only. These objects do not grant production
permission. MODEL != AUTHORITY; UNKNOWN != SUCCESS != FAILURE.

This portable, standard-library-only package has no runtime imports, I/O,
provider calls, signing, ledger, scheduler, memory engine or effect executor.
It is intentionally excluded from the production distribution.

## Design and execution plan

The supplied PRE-01 specification and ten-task test-first plan are binding.
1. Create this isolated package and unittest discovery directory.
2. Test then implement immutable EvidenceRef and Applied/NotApplied/Unknown.
3. Test then implement shared strict canonical JSON and domain-separated SHA-256.
4. Test then implement dependency sets and their deterministic root.
5. Test then implement AuthorityScope and explicit Money/RiskLevel schemas.
6. Test then implement EffectWarrant binding and reservation validation.
7. Test then implement LiabilityRecord state consistency.
8. Test cross-contract round trips, fixed vectors, import isolation and process stability.
9. Compile, whitespace-check, scan changed files and check allowed paths locally.
10. Review, commit once, verify frozen main refs and a clean worktree; stop.

## Schema policies

All dataclasses are frozen. Collections are defensively copied into tuples;
set-valued collections are sorted and exact duplicates removed. Evidence with
the same evidence_id but differing content is rejected in a dependency set.
An empty dependency set is valid and explicitly domain-separated. It carries
no approval. Evidence source_version is required; changing any evidence field
changes the dependency root. No entire HAT/task state is hashed.

Wire objects include contract_type and schema_version (integer 1). Unknown,
missing, duplicate JSON fields, unsupported versions and noncanonical input
types are rejected with ContractValidationError and stable field/code metadata.
Identifiers are nonblank strings without surrounding whitespace. Digests are
lowercase sha256:<64 hex characters>; only this algorithm is supported in v1.
All timestamps must be timezone-aware with UTC offset zero; accepted values
are copied to immutable timezone.utc. They are serialized with
six fractional digits and Z. No clock or random values are read.
Money uses finite, nonnegative Decimal and an uppercase three-letter currency.
Canonical decimal strings have no redundant trailing zeros or negative zero.
Floats are rejected everywhere by canonical serialization, including money.
RiskLevel is an explicit enum: LOW, MODERATE, HIGH, CRITICAL.
Targets and owner/task scopes are exact identifiers; no glob matching in v1.

Outcome boolean coercion always raises TypeError, including Applied. Inspect
the variant explicitly. Unknown requires liability_id; evidence_refs refer to
metadata, never provider payloads. SHA-256 is a fixture digest, not a signature.
Hashes use UTF-8 bytes of PCAF/<contract_type>/v1 followed by NUL and compact
sorted-key JSON. SHA-256 inputs never include Python process hashes.
Contract equality uses frozen value semantics. hash() uses a deterministic
31-bit truncation of the canonical digest, independent of PYTHONHASHSEED.
Use contract_digest() for full wire identity; hash collisions remain possible.
EvidenceRef.digest is the referenced evidence digest, not a method;
contract_digest() uniformly hashes the reference object itself.

Warrants must fit their authority owner/task and validity window. A nullable
target revision requires explicit ALLOW_UNVERSIONED policy; otherwise REQUIRE.
Reservations use the explicit NONE fixture marker iff the associated money
ceiling is zero / risk ceiling is LOW. Other reservations require an ID.
These checks are schema consistency, not production authorization or minting.
OPEN and ESCALATED liabilities have no closure time or resolution; CLOSED
requires both and a time at or after opened_at. Dependency refs are EvidenceRef
metadata, not a durable dependency ledger. PRE-02 may add that ledger and taint
semantics; PRE-03 may build attenuation properties. Neither is implemented here.

## Local verification

From the repository root:

    PYTHONPATH=. python3 -B -m unittest discover -s tests/lab_archaioa -v

Final verification uses env -i, a temporary HOME, and an explicit PYTHONPATH.
Fixed synthetic fixtures in fixtures.py contain no private prompts or secrets.

## Execution / review record

- Tasks 1–3: skeleton, schema policies, Outcome/Evidence and canonical engine;
  missing implementation observed in RED, then 15 tests GREEN.
- Tasks 4–5: dependency root and authority schema; 10 new tests observed RED,
  then 25 tests GREEN.
- Tasks 6–7: warrant and liability schemas; 12 new tests observed RED,
  then 37 tests GREEN.
- Task 8: composable fixed bundle, independent literal-wire JSON/SHA-256
  vectors, import isolation and seed-independent serialization; 6 new tests
  observed RED, then 43 tests GREEN.
- Independent read-only review found four important issues: salted Python
  hashes, raw errors on overlong JSON integers, incomplete UTF-8 validation,
  and retained mutable tzinfo. Four regression test methods reproduced these
  issues in RED. Fixes produce 47 tests GREEN; the existing vectors are intact.
- Ruling: valid deeply nested JSON need not be rejected by the parser; if
  encoding exceeds interpreter nesting capacity it produces a typed error.
  No arbitrary payload/Decimal limit is introduced in PRE-01.
- Ruling: only focused lab tests run. The supplied phase forbids production
  imports in lab tests and unnecessary runtime/services; broader production
  testing belongs to later integration. No production behavior is claimed.
- Deferred review subjects: production authority, signing, storage, taint and
  full attenuation campaigns are deliberately PRE-02/PRE-03 or later work.
  Fixed vectors are synthetic evidence only. Packaging configuration remains
  unchanged; its explicit package allowlist excludes lab.
