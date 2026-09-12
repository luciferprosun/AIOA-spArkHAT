# ADR NZ-001 — frozen subtree and operator-only adapter

Status: HISTORICAL PHASE 2; superseded by native Phase 3 and Phase 4 retirement.
The architecture, dependencies and source-tree test setup below describe the
former integration, not current launch/install instructions. There is no active
embedded project or separate credential now. Use [native operation](../NONZERO_CORE_INTEGRATION.md)
and the [one-system retirement record](../integration/NONZERO_ONE_SYSTEM_RETIREMENT.md).

## Established interfaces and import

AIOA spArkHAT (GitHub repository ID `1247349659`) already has `AgentRuntime`,
a slash-command registry, `WebRuntimeService` and `AppendOnlyProvenanceStore`.
There is no separate generic plugin registry. Following CPL's existing pattern,
`AgentRuntime.nonzero_cloudops` owns one lazy service, registered as `/nonzero`
and `/api/nonzero/*`. No second server, provider router or tool framework is added.

The private sandbox's complete frozen tree is imported at
`runtime/nonzero_cloudops/baseline` by **git subtree without squash**. The exact
import's second parent preserves all 84 commits reachable from the frozen SHA;
other historical branches remain preserved separately in the sandbox. The
subtree contains 412 unchanged files, including source, tests, scripts, infra
specifications, docs, assets, MIT license and prior-art attribution. No Core
files are deleted. See the [Git subtree documentation](https://github.com/git/git/blob/master/contrib/subtree/git-subtree.adoc).

The adapter delegates to the original `LocalApiApplication` and
`create_local_hitl_runtime`. Approval challenges, exact proposal/evidence
bindings, separate execution confirmation, durable receipts, independent
verification and replay/restart handling are not reimplemented. Preserving
deployment scripts does not grant authority to run them.

## Dependency conflict matrix

| Area | Core baseline | Frozen module | Decision |
|---|---|---|---|
| Python | >=3.11 | >=3.12, certified 3.12.3 | Core minimum unchanged; module refuses <3.12 |
| Default dependencies | none | Pydantic 2.13.4, Strands[otel] 1.53.0, uuid6 2025.0.1 | Explicit `[nonzero]` extra in a separate >=3.12 venv |
| Optional desktop/browser stack | `runtime/requirements.txt` | unnecessary | No upgrades or environment merge |
| Build tools | setuptools>=65, wheel | setuptools>=75 | Preserve both manifests and module lockfiles |
| Tests | unittest, optional UI | pytest/Ruff and dev extra | Separate native suites plus Core contracts |
| Distribution | runtime package/web assets | src package/scripts/docs/assets | Bundle exact subtree as data, exclude it from Core namespace discovery |
| Credentials | optional provider configuration | live AWS/Bedrock code exists | Explicit portable/mock constructors only; no live environment opt-in |

This does not claim compatibility of every optional desktop/provider package.
The pinned module environment and ordinary dependency-free Core are certified
separately. No broad upgrades or root manifest replacement is performed.

## Authority, state and evidence

Core's loopback Host/Origin/session-token checks remain in force. Writes also
require `X-AIOA-Intent: nonzero-operator-v1`. Generic Assistant requests reject
`/nonzero`; it is not a model tool. JSON `operator` or `approved` assertions grant
no authority. Only fixed local API routes are mapped: no shell command, URL,
state path, credentials or live-mode selector can be supplied. The Core kill
switch blocks module writes.

A source-issued, expiring nonce binds the exact human decision. Execution is a
separate confirmed action. Durable truth, mock inventory, a private local
operator credential and provenance live in the existing `AOIA_HOME` namespace,
outside the source tree/retrieval corpus. An exclusive lease prevents competing
owners. The stable private credential preserves original ownership/replay checks
across restart; it is never committed or returned through the API.

Core's append-only provenance implementation is reused with a module-specific
ledger, avoiding an unsynchronized shared writer. Request bodies/raw nonces are
not logged. Sanitized results link run/trace IDs, proposals, evidence and receipts.
Hashes establish integrity/linkage, **not factual truth**.

## Historical Git-aware reference certification (Phase 2/3 only)

The original source gates assumed their own repository root, frozen HEAD and historical tags.
Using the enclosing Core HEAD would test the wrong Git context. Certification
creates external Git metadata from imported Core objects at the frozen parent
and proves complete tree equality. Each tracked top-level file/directory is
then bind-mounted read-only from the actual Core subtree over that context.
No `.git`, venv or cache is copied into Core.

Native P1 may perform its original read-only public clean-clone proof and package
download. The Core import itself uses only the private sandbox. Other runtime
checks use isolated loopback networking and hidden host credentials. Phase 1's
environment is reused read-only: Python 3.12.3, pip 26.2.1, AWS CLI 2.36.11
(`--version` only). OpenTelemetry remains enabled for in-memory spans; network
exporters are disabled.

The existing CLI/API supplies the operator surface. A dedicated visual operator
pane, public multi-user hosting, live AWS/provider calls, main merge and deployment
are future approval gates, not implied by this integration.
