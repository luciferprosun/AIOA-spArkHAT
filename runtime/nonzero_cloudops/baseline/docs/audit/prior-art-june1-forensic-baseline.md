# Prior-art forensic baseline at the 1 June 2026 boundary

## Scope and cutoff

This is a provenance audit, not a claim that historical AOIA implementation belongs to the
current AWS hackathon project. The user-facing cutoff is the end of 1 June 2026 in
`Europe/Berlin` (`2026-06-02T00:00:00+02:00` exclusive). Original Git timestamps and offsets
are preserved below. Timestamp alone does not establish submission reachability.

The public submission baseline is the tree reachable from the verified AOIA-Core submission
ref `d7e3448afa4e33d58be8babbfcc615b13dff533f`. A fresh clone of the public repository still
resolves `main` to that commit, and the annotated tag `nlnet-safe-d7e3448` resolves to the same
commit. No later branch, tag, reflog entry, archive, or similarly named directory is allowed to
retroactively enlarge that tree.

## Verified anchors

| Repository or anchor | Exact evidence | Forensic treatment |
| --- | --- | --- |
| `luciferprosun/AOIA-Core` public baseline | `d7e3448afa4e33d58be8babbfcc615b13dff533f`; author and committer `2026-05-31T13:37:44+02:00` (`11:37:44Z`); subject `docs: clarify scope boundaries before submission` | `PUBLIC_BY_JUNE1`; 38 commits are reachable from this ref. |
| AOIA-Core feature savepoint | `78ab53851ac8f2e70bc48cead44582aa05c9bfe3`; `2026-05-31T10:00:36+02:00`; subject `feat: add model selector and xAI provider option` | Reachable from `d7e3448`; public-baseline feature evidence. |
| AOIA-Core status register | `docs/governance/IMPLEMENTED_CAPABILITIES.md`, committed in the reachable tree and dated 30 May 2026 | Strong contemporaneous claim register, checked against code and tests rather than accepted alone. |
| AOIA-Core future compatibility note | `docs/audit/AOIA_FUTURE_COMPATIBILITY_NOTES.md`, dated 28 May 2026; explicitly `Scope: notes only; no implementation` | MCP is documentation-only at the public baseline. |
| HackVerse boundary | First commit `c39255f8a091825ddc7c1e563fba3a3f66106a50`; author and committer `2026-07-22T19:32:51+02:00`; subject `feat: prepare AOIA HackVerse 2026 reviewer pack` | `POST_JUNE1`; it cannot prove a June submission capability. |
| Current AWS project at audit start | `2a4f4cd728aa36eb85ab550620638a3f7e72f1aa`; `2026-08-24T04:36:27+02:00` | `AWS_HACKATHON_NEW_WORK`; independent history and newly authored implementation. |

The `d7e3448` change itself was documentation-only: eight reviewer/governance files changed.
The preceding `78ab538` feature savepoint changed provider configuration, model-selection UI,
and `tests/test_main.py`. `git merge-base --is-ancestor 78ab538 d7e3448` succeeds.

## What a reviewer could have seen on 1 June

The following is the conservative public picture at `d7e3448`, not the later AOIA roadmap:

| Capability family | Contemporaneous claim | Verified public evidence | Reviewer-safe conclusion |
| --- | --- | --- | --- |
| Evidence write boundary | Partial | `5b7e6da8`; `runtime/tools/memory.py::MemoryStore.append_evidence`; `tests/test_evidence_boundary.py`; `tests/test_evidence_write_contract.py` | Runtime-enforced narrow allowlist, but not a complete immutable evidence store. |
| Append-only provenance | Implemented in the external register | `8c2e9e0a`; `runtime/tools/provenance.py::AppendOnlyProvenanceStore`; `tests/test_append_only_provenance.py` | Implemented and tested local hash-linked provenance skeleton; scope remained local and narrow. |
| Provenance verification/readout | Partial in the external register | `4f2bffec` and `b059fcc9`; `verify_provenance_chain`; `runtime/tools/provenance_readout.py`; verification/readout tests | Implemented local lineage/integrity verification, not truth or source-authenticity verification. |
| Deterministic local retrieval and epistemic gating | Partial | `AOIAEpistemicKernel`, `retrieve_linux_knowledge`, RHCSA retrieval and routing-boundary tests | Useful prior-art concept with partial runtime enforcement. |
| Provider switching | Implemented | `78ab538`; `runtime/providers/config.py`; `runtime/commands/local_commands.py`; provider-switch tests in `tests/test_main.py` | Convenience feature only; provider output remained non-authoritative. |
| Human approval gates | Partial | `runtime/tools/executor.py::ExecutionEngine.execute` and `_request_approval`; TUI approval path; `tests/test_main.py` and `tests/test_tui_phase2.py` | In-process prompt existed, but not durable, proposal-hash-bound, nonce-bound, or complete across every action. |
| Runtime safety contracts | Partial | `runtime/tools/validator.py`, executor containment tests, authority/governance docs | Useful controls existed, but the public register expressly disclaimed complete production enforcement. |
| Replay verification | Partial in `IMPLEMENTED_CAPABILITIES.md` | `docs/governance/GOVERNANCE_IMPLEMENTATION_STATUS.md` says `NOT_STARTED`, `No replay verifier exists` | The two contemporaneous documents conflict. No executable replay verifier was found, so the forensic result is documentation/design only. |
| Contradiction registry | Partial | `runtime/tools/epistemic_registry.py::build_contradiction_registry`; registry/kernel tests | Contradictions were recorded/reported; no formal blocking or automatic resolution. |
| MCP adapter | Not claimed as implementation | 28 May future-compatibility note, `Scope: notes only; no implementation` | `DOCUMENTED_ONLY`; no public-baseline MCP runtime. |
| GUI/TUI | Documentation only in the external register | TUI/web files and focused tests coexist with that conservative label | Operator surface existed, but it was not the core authority or a production-readiness claim. |

The public register therefore explicitly marked human approval gates, replay verification, and
runtime safety contracts as **Partial**. The code inspection narrows the replay claim further:
the more detailed governance status says it had not started, and no replay verifier was found.
This disagreement is preserved rather than normalized upward.

## Public, side-history, local-only, and post-June separation

### Public submission tree

Only commits reachable from `d7e3448` are classified `PUBLIC_BY_JUNE1`. That includes the
feature savepoint `78ab538`, the 26 May evidence/provenance work, and the conservative 30 May
reviewer status register.

### Cutoff-era side history

The repository currently exposes other refs containing commits dated after `d7e3448` but before
the end-of-day cutoff. Examples include the RHCSA grammar series beginning at
`8da0521784b8efbb4e71e7cbc90d00051836cb53` on 31 May and the Memory Hats series beginning at
`c1af37b1c2967df73c7f30a28eb3c85230857d76` on 1 June. Later tags also point to post-NLnet
checkpoints such as `2f859cadbbdc85f5b95ad92d04aa55d180dc6c1a` and
`9efefb1ab73501609c67ec1f68f8c4b5a5b2b0a9`.

None of those commits is reachable from the verified submission ref. Git commit and tag creator
dates do not reveal when a ref was pushed or whether it was part of the actual submission.
Accordingly they are **cutoff-era non-baseline side history**, not public submission evidence.
They are also not labeled `LOCAL_ONLY_UNPUBLISHED` without proof of their publication state at
the cutoff.

### Local clone/archive review

Read-only inspection covered multiple AOIA-Core clones and preserved worktrees whose remotes
identify `https://github.com/luciferprosun/AOIA-Core.git`. They reproduce later branches and the
same `main = d7e3448`; one preserved July worktree is dirty and was not touched. Available
reflogs did not provide cutoff-time publication evidence. No notebook capability 12–54 was
proven by a local-only commit created by the cutoff. Therefore:

`LOCAL_ONLY_BY_JUNE1 = NONE_PROVEN`

This does not assert that no local experiment ever existed. It says the inspected evidence is
insufficient to promote one into the June public baseline or into a proven unpublished result.

### Post-June AOIA evolution

The exact roadmap sequence appears later in AOIA-Core history. Capability 12 begins at
`1bc059ff` on 26 June; capabilities 13–26 follow through 27 June; Git-related capabilities begin
on 27 June; provider, package, browser, integration, orchestration, and agent-loop boundaries
continue through `62107bc6` on 6 July. Forty-two capability-shaped entries have post-June
code/test evidence; notebook item 27 is a section marker rather than a runtime capability.

Later hardening is also separate. In particular, static capability enforcement, the write
kill-switch, workspace identity/TOCTOU enforcement, and the full-chain integration suite were
hardened at `47fcf394`, `5b66890a`, `ba9d00e4`, and `849b4e82` in July. The HackVerse repository
starts on 22 July and explicitly describes itself as a focused prototype that does not copy the
AOIA production tree.

## Current AWS baseline verification

At audit start the current repository was clean on `main`, and local `HEAD` equaled
`origin/main` at `2a4f4cd728aa36eb85ab550620638a3f7e72f1aa`. The existing project environment produced:

- `519 passed` with zero failed and zero skipped;
- `ruff check .` passed;
- dependency consistency passed;
- `git diff --check` passed.

No AWS call was made. The Phase 1 tag and all historical repositories remained unchanged.

## Integrity conclusion

Old AOIA is useful conceptual and historical prior art. The current repository is not a
continuation of the AOIA submission tree: it has an independent root, a disclosed clean-room
boundary, and newly authored Strands/AWS/Non-Zero mechanisms. Later AOIA work may reveal useful
guard patterns, but it cannot be described as public-by-1-June implementation and must not be
copied, cherry-picked, or used to rewrite the old submission narrative.
