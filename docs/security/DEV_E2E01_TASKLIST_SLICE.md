# DEV-E2E01: fixed task-list CLI through the existing Core

This extends U08/PC05, U07/PC04 and U11/PC08. It is a small offline useful-app
demo, not another master U stage, the U14 PKG audit, an autonomous coding agent
or the complete PDF p12 web/browser/GitHub acceptance workflow.

The supported request selects `aioa-tasklist-cli-v1`, a title and 1–8 task
labels captured by the trusted host from the owner. Titles and labels are
untrusted data, each limited to 128 UTF-8 bytes and printable characters.
`TaskListRequest.parse` accepts exactly those three fields. Code, imports,
commands, paths, URLs, environment, tests, approval and budget fields are
rejected. The existing advisory parser still accepts only an opaque registered
recipe/step proposal or non-authoritative final text. It cannot construct or
change the host's plan, seed, registry, grant or warrant.

`TaskListPlan` is immutable and permits only a fresh `fixture:` project,
revision zero and null preimage. The trusted `ProjectSeed` remains independent.
The exact reviewed template, test harness and standalone worker are pinned by
explicit SHA256 identities and copied verbatim. The unchanged arithmetic
`validate_program` does not accept this source; this is a separate versioned
contract. No arbitrary code strings or `runpy` are executed.

The CLI has fixed `init`, `add`, `complete` and `list` commands. It stores
canonical JSON at `data/tasks.json` under its fresh cwd. IDs increase from 1
and stay stable even when labels repeat. Completing ID 1 again preserves the
data. Directory/file opens use trusted directory descriptors and no-follow;
regular files must have one link. Writes use exclusive temporary files, fsync
and rename. This is a fresh single-writer sandbox, not concurrent host-file CAS.
Existing files, host projects, custom config and arbitrary paths are unsupported.

Explicit `prepare_tasklist_sandbox` uses the accepted U06 preparation helper,
fixed Python 3.12 argv and registry. It selects the already allowed 20-second
timeout for the template's CLI checks; the 5-second arithmetic profile stays
unchanged. Output is capped at 4096 bytes, memory at 512 MiB, CPU at one CPU,
PIDs at 16, work/tmp/artifacts at 32/16/8 MiB. Syscalls, seven namespaces,
read-only runtime/inputs, hidden HOME/source and network OFF remain U06's
existing policy. Missing bwrap/systemd or kernel proof fails closed.

The trusted caller supplies the existing owner-scoped Core principal, task,
step, session grant, completion binding, policy/epoch, reservation and warrant.
Preparation grants no dispatch authority. `CoreAgentBindings` and
`CoreToolRoute` approve and durably journal START before U06 releases code.
The fixed harness executes real CLI subprocesses: initialize, add the selected
labels, list, complete the first ID, list in JSON/text and run 16 acceptance
groups. It also checks bad commands/IDs/labels, idempotency, corrupt/oversize
data, symlink/hardlink refusal, inaccessible host paths, denied sockets and the
actual address-space cap. It restores its own fault fixtures before export.

Eight exact artifacts are expected: app source, fixed tests, plan, final data,
text list, test log, result and manifest. The host-side broker independently
opens the artifact mount after the entire worker cgroup is empty and compares
every byte count/SHA with the trusted plan. A worker-written PASS, provider text
or zero exit alone cannot finish a job. Only the retained Core readback proof
permits DONE. UNKNOWN and a lost ACK confer no new attempt; reconciliation is
readback only. U11 projects the same Core state and provides STOP/reconcile.

For `My tasks` with `Buy milk`, `Read book`, the required text is:

```text
My tasks
1 [x] Buy milk
2 [ ] Read book
```

Kernel acceptance uses the existing native Core with a synthetic owner/signer,
fixed clock and durable transaction fixture. It proves the real local route
and contained CLI, not production authority, Cockroach SQL, paid/LIVE advice,
distributed fencing, clean-host installation or independent user acceptance.
Installed wheel/sdist import smoke and source-based U06 execution are separate
claims unless a single source-hidden installed execution is actually measured.

Evidence, exact source identities, real failures/skips, kernel counts and local
review limits are recorded outside source in `remote-codex-dev-e2e01-20261011`.
Human/other-agent independence must not be inferred from a same-author review.
No optional Git preview is enabled by this contract. Full D3/D4/D6/D8, U14
PKG-03, Nebius LIVE G9/G10 and release/push remain NOT_ACCEPTED. Managed browser,
locked project dependencies and approved GitHub publication require their
separate existing gates; no mock or installer extraction satisfies them.
