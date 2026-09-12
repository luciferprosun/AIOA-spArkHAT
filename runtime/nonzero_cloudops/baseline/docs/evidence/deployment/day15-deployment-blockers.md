# Day 15 interrupted-session deployment blocker report

- Status: `BLOCKED`
- Decision: `DO_NOT_DEPLOY`
- Ready for deployment: `NO`
- AWS state changed: `NO`

The recovered Day 15 runtime and release candidate is locally complete. The final ten-gate run
returned nine `PASS`, one `BLOCKED`, and zero `FAIL` or `PARTIAL`. Only D15-G10 remains blocked:
the candidate has neither a completed deployment-contract selection nor a candidate-bound,
authenticated external preflight receipt. No change set or stack deployment was attempted.

## Recovered candidate

- Recovery baseline: `aa941a989a8b8cd0e40367bb130472e9f3c082a7`.
- Preserved M1: `17d5f4637dbd69a33eff1cbb46282c36b19ce6ad`.
- Preserved M2: `8e4583ac9341cb7b66de47cf0e7b2a442ac67b32`.
- Preserved initial M3 blocker: `30c2a30cda0ac6d6e2003166daf6c29bf2c764f0`.
- Recovered M1 closure: `f2ee79c09ba174ba72cb527b70c095f412151758`.
- Final M2 candidate: `36fd17df981dfa593d4e63f6a143410317410763`.
- Deterministic Lambda ZIP SHA-256:
  `399fce019af3ee8a596ffb05ab37ad7f0ac5266bfed32363c2b5c6f8e66846cf`.
- Artifact manifest SHA-256:
  `c2045cfd66ad05b512def07ecbb0165af2b3831eedb240666cb929b198067ea9`.
- Passing dependency scan SHA-256:
  `f4f7831f77bc9826ece9a93fcd16b4fbaca3f579f524a2760fe94e9006e719c7`.
- Rendered template SHA-256:
  `b36b749d1913362142fe2ddaedec52fa105bf11cd4b2ffda1560cd00af4891d2`.
- Render provenance SHA-256:
  `3452fa1402a653cc2a4940268f876350f40dbbd2a205c7b30d00b8f693a38acc`.
- Lambda configuration SHA-256:
  `67afd13d45f19b62993a78bd8a1ae61a6b67364370791533615ed53a2ebe830f`.
- Frozen deployment-contract SHA-256:
  `cc4dc67a4a2db65efd62d9dd81d021f2ee2f3ca583f783aea07a13a886b5211c`.

The canonical local-gate evidence at `docs/evidence/deployment/day15-local-gate-m2.json` has
SHA-256 `802b1521f3166aa719c7ace6dc5e8a79a9e81f0bd310c479323a00f499cf32a3`.
D15-G01 through D15-G09 are `PASS`. D15-G10 is `BLOCKED` with exactly
`DEPLOYMENT_CONTRACT_SELECTION_REQUIRED` and `EXTERNAL_PREFLIGHT_RECEIPT_REQUIRED`.

## Missing or unproven external prerequisites

The following external facts remain `UNPROVEN` for this candidate:

- an authorized AWS deployment profile and role;
- the correct hackathon AWS account;
- deployment in `eu-central-1`;
- an encrypted, public-blocked, TLS-only, versioned, short-lifecycle packaging bucket and path;
- create-and-read authority for a dedicated judge-token secret;
- a pre-existing, operator-selected sandbox EC2 target;
- the exact sandbox tag `AIOACloudOpsSandbox=true`;
- the sandbox target being in `eu-central-1`;
- sufficient read-only CloudWatch data;
- Nova 2 EU inference-profile access; and
- ownership of any required budget notifications.

The exact deployment profile frozen by the contract is not configured locally. A recovered,
earlier safe identity-read attempt returned no authorized identity. No AWS API call was made for
the final M2 candidate. These facts are evidence gaps; they do not assert that any external
resource is absent.

## Safety outcome

- AWS writes or state changes: `NO`.
- Change set creation or stack deployment: `NO`.
- Function URL or public route creation: `NO`.
- Orchestrator, private executor, durable table, judge secret, or telemetry-resource creation:
  `NO`.
- `StopInstances`, including DryRun: `NO`.
- `StartInstances`, `TerminateInstances`, or `RebootInstances`: `NO`.
- Tag mutation: `NO`.
- Public approval or mutation route: `NO`.

Run the local-only validator with:

```bash
.venv/bin/python scripts/day15/validate_blocker_report.py --json
```

This is a historical M2 snapshot. The default command verifies its frozen digests and recovered
commit ancestry without comparing them to a later working tree. Add
`--validate-current-candidate` (or pass explicit candidate paths) only when validating the current
candidate bytes; expected drift then fails closed. Both modes require the exact
nine-pass/one-blocked result and full external blocker set, reject identity-sensitive values, and
require every deployment and mutation indicator to remain false. A validator `PASS` authenticates
this truthful historical `BLOCKED` report; it never authorizes deployment.

The next boundary is an authorized operator supplying the separately reviewed contract bindings
and candidate-bound external receipt. Until D15-G10 also passes, partial deployment remains
forbidden.
