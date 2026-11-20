# NZ13-A: portable CloudOps contract deltas

This local candidate adapts W7A commit
`392487849eddc7444f5159994b66b72e73f15934` under the existing
[MIT notice](../../runtime/nonzero_cloudops/LICENSE-NONZERO.txt).
It does not certify the complete standalone application or LIVE operations.

New execution intents use `local-exec:<run_id>:<proposal_hash>`. Checkpoint
validation and the existing portable inventory continue to accept historical
keys, only with all original run, evidence, proposal and approval bindings.
Restart/readback never creates a second mutation.

Starting an investigation in the portable CLI leaves previously released
inventory intact. A request for an absent released demo resource returns
`NONZERO_DEMO_REARM_REQUIRES_CORE`. Existing runs and their receipts remain
available for readback.

Restoring a managed demo resource is a separate Core REARM operation with an
owner warrant. Core binds the complete release history, the target revision,
and the durable intent before applying the change. The managed path checks
STOP and verifies the outcome independently. Its qualified scope is synthetic
inventory.

Redaction covers GitHub `ghp`, `gho`, `ghu`, `ghs`, `ghr` and `github_pat`
families, including Unicode adjacency and complete stateless installation token
segments. Public Core evidence projections also filter credential-bearing keys
and redact nested strings. Token values never enter receipts or error messages.
GitHub documents the current families in
[authentication guidance](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/about-authentication-to-github#githubs-token-formats)
and the 2026 stateless installation token rollout in its
[October 2 changelog](https://github.blog/changelog/2026-10-02-stateless-github-app-installation-tokens-rolled-out/).
Detection is conservative; it is not a universal secret scanner.

`test_nz13_cloudops_contracts.py` exercises the actual Core-owned domain service,
durable stores, restart, readback and refusals through an explicit trusted fixture
port. It does not claim public HTTP mutation admission. Existing public effect
routes remain denied. No second Core, authority store or executor is added.

The original `nonzero_parity_v1.json` is preserved byte-for-byte and still checks
all historical hashes using a legacy-format input intent. Separate fixed W7A
vectors check current production intent creation. Their provenance records v1
golden validation followed by original W7A **pure contract** transformations;
neither the historical server nor an agent is launched to generate them.
Normal build/tests need no checkout or network access to the original repository.
The no-extra discovery regression also runs with `-I -S`, exposing only project
packages so installed third-party dependencies cannot hide an unconditional
import. Domain cases skip cleanly when the optional extra is unavailable.

The NZ12 inventory retains its historical role assessments and qualification
claims. Target blob/AST bindings are refreshed for this candidate and verified by
the existing source policy; this refresh does not upgrade historical rows to full
functional parity. Capsule/verification semantics (#13/#67) still depend on the
GitHub DTO and setup/render work in subsequent NZ13 waves. Model inference,
production deployment, GitHub WRITE and source retirement remain separate gates.
