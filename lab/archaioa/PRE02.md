# PRE-02: typed UNKNOWN and liability semantics

Pure CONTRACT / FIXTURE lab, Python standard library only. No production
behavior or external truth verification is claimed. Inputs are immutable
metadata references; never put private content into identifier fields.

`FaultTrace` has a closed four-value `FaultKind`, opaque task/request references
(ASCII letters, digits, underscore or hyphen, 1–128 characters), and an operation
SHA-256 digest. There is no payload, prompt, response, error-text or retry field.
Each trace classifies as `Unknown`, never Applied/NotApplied. All Outcome
variants reject boolean coercion, preserving PRE-01 unchanged.

The liability identity is a domain-separated canonical digest of task, request
and operation digest. Fault kind is deliberately excluded: lost acknowledgment
and inconclusive readback of the same operation reference the same liability.
Callers must preserve operation identity. `open_liability` returns an OPEN
record or verifies an existing OPEN record with the exact binding. Conflicting,
escalated or closed existing records are rejected; there is no automatic
reopening or retry. Repeated observations must pass the existing record and
its original opening timestamp; the helper reads no clock or ledger.
`ambiguity_liability` validates exactly one OPEN reference; duplicate identical
records normalize, conflicting records fail closed. Applied/NotApplied have
no ambiguity reference and create no records.

`is_blocking` includes OPEN and ESCALATED. `resolve_liability` explicitly
requires an EvidenceRef and caller-supplied UTC closing time at/after opening.
It returns a new CLOSED record with resolution_ref and evidence metadata.
CLOSED is the PRE-01 representation of resolved state; there is no additional
RESOLVED enum or automatic closure. The contract checks metadata consistency,
not evidence truth, human approval or ServiceGuard authority. PRE-01 wire
schemas and independent canonical vectors are unchanged.

`DependencyGraph` binds nodes to one task. Nodes describe required dependencies
and liability references, including operation/evidence, claim, proposal and
completion candidate roles. Node/dependency/liability collections copy inputs,
sort and normalize exact duplicates. Conflicting duplicate IDs, absent edges,
self-loops and cycles produce sanitized ContractValidationError metadata.
Cycle detection and propagation use iterative Kahn traversal, including deep
DAGs. Every referenced liability in the supplied graph must exist and match
its task; incomplete graph snapshots fail closed even on disconnected nodes.
Unreferenced records do not contribute taint.

`propagate_taint` returns immutable node-ID-sorted NodeTaint contracts containing
the union of blocking liability IDs in each node's required ancestor closure,
including direct references. `state` derives TAINTED_BY_LIABILITY or CLEAR from
this set, so serialized IDs cannot disagree with status. CLOSED references stay
in the graph but no longer contribute taint when results are recomputed. Old
results remain immutable. Closing an unrelated liability clears nothing else.

`check_completion` accepts only a completion candidate and recomputes from the
entire graph/current records; it cannot use a stale taint cache. A blocking
required ancestor returns BLOCKED with all blocking IDs. Only an empty blocking
set permits COMPLETED. Unrelated open branches do not block the candidate if
their references are supplied and valid. CompletionDecision also rejects bool
coercion. The decision is data, not a task mutation or effect executor.

Synthetic `pre02_fixtures.fault_story(kind)` builds each of the four ambiguous
stories: trace -> UNKNOWN/OPEN -> operation -> claim -> proposal -> candidate.
`resolution_evidence()` supplies synthetic metadata for explicit resolution.
All new contracts use PRE-01 canonical versioned JSON, domain-separated hashes
and process-independent Python value hashes. Unknown wire fields/versions and
malformed values are rejected without echoing their content.

Validation covers all four fault stories, 27 combinations of three liability
states in a diamond/disconnected graph, permutations, duplicates, invalid
references, partial closure, escalated closure, a 1,500-node graph, wire round
trips, import blocking, and three process hash seeds. PRE-01's 47 tests remain.
Tests were added before implementation and failed for the missing modules.

Run from the repository root with a fresh temporary HOME:

```bash
env HOME=/tmp/archaioa-pre02-final PYTHONPATH=. \
python3 -m unittest discover -s tests/lab_archaioa -p 'test_*.py' -v
```

PRE-03 should treat these as fixture contracts: stable operation identities,
complete required-dependency snapshots, one authoritative record per liability,
caller-supplied UTC timestamps, and externally established resolution evidence.
No authority attenuation, provider integration, scheduler, ledger or executor
is introduced in PRE-02.
