# Consolidation validation — pinned implementation evidence

Frozen main: `2be99da7aa07f7eb5faa9459fe8a78c5d0b6653a`. Current implementation checkpoint: `bb48d7940f1e759adce4ff8b24c9a296819dc461`; source classification and release documentation follow without changing runtime/test code. Results are tied to their exact checkpoints, never promoted to LIVE qualification. Final documentation-only PR HEAD, synthetic merge-tree SHA, zero-file merge comparison and all six checks must be verified in the current PR46 description and the owner's release report before exact owner GO.

## Verified prior baseline

Baseline `41aa47e57e5c8e875f0a67d87108cba62d1d623c` completed **6/6 required jobs PASS**: [Core, packaging and Chrome](https://github.com/luciferprosun/AIOA-spArkHAT/actions/runs/42002378460), [MCP](https://github.com/luciferprosun/AIOA-spArkHAT/actions/runs/42002378459). On each Python 3.11/3.12: Core 2946 cases = 2941 PASS + 5 allowed SKIP; additional NonZero 105 PASS; MCP 99 PASS; JS 48 PASS; isolated Chrome 1 PASS; wheel/sdist PASS. The synthetic merge had zero file differences from that candidate. [CodeQL](https://github.com/luciferprosun/AIOA-spArkHAT/actions/runs/42002378358) was **SKIPPED**, not PASS.

## Final implementation results

Implementation `bb48d7940f1e759adce4ff8b24c9a296819dc461`: **6/6 required jobs PASS**. Required [Core/installed packages/Chrome](https://github.com/luciferprosun/AIOA-spArkHAT/actions/runs/42015109337) and [MCP](https://github.com/luciferprosun/AIOA-spArkHAT/actions/runs/42015109213); [CodeQL](https://github.com/luciferprosun/AIOA-spArkHAT/actions/runs/42015109163) remains **SKIPPED** under the unchanged owner profile. Exact job results and captured log SHA-256 values are in [FINAL_CI_EVIDENCE.json](FINAL_CI_EVIDENCE.json). The tested synthetic merge `598c0871983d4c78dd617db6981f4cfc65078afd` and implementation have the same Git tree `0655749ef3bd87c84ae28a74ce242a636c877497`; GitHub comparison lists zero changed files.

| Required CI scope | Python 3.11 | Python 3.12 |
| --- | --- | --- |
| Full Core | 2953 cases: 2948 PASS + 5 allowed SKIP; 741.778s | 2953 cases: 2948 PASS + 5 allowed SKIP; 759.904s |
| Additional NonZero | 105 PASS; 54.112s | 105 PASS; 53.488s |
| MCP | 99 PASS | 99 PASS |
| JavaScript | 48 PASS | 48 PASS |
| Isolated Chrome + temporary Native/Core | 1 PASS; 17.901s | 1 PASS; 10.657s |
| Installed wheel/sdist + actual Native fixture | Both PASS; 26 source pins each | Both PASS; 26 source pins each |
| Architecture/provenance, configured Ruff scopes, AST/compile, command discovery | PASS | PASS |

The five skips are unchanged: two Playwright-only tests, two optional Textual modules and the opt-in pinned NVIDIA ATIF model validation. No new skip was introduced.

| New or changed local scope | Observed result | Private evidence |
| --- | --- | --- |
| Changed grammar/provider/capability/advisory/flow/chat-session/GitHub tests | 96 PASS, 54.863s, zero skips | `targeted-final-code.log` |
| Chat/console JavaScript | 48 PASS, zero skips | `node-final-code.log` |
| New composite Native flow | 1 PASS, 2.259s; included in the 96 above | `native-flow.log` |
| Advisory input/source/ACK regressions | 15 PASS; overlapping scope, do not add counts | `advisory-edges.log` |
| Installed real Native from wheel and sdist | PASS both, Python 3.12.3; 26 source pins each | `packaging-native.log`, installed `result.json` |
| Official SQLite backup and three source-pinned readers | PASS; same 1200 records, 443 audit/outbox, 16 warrants/witnesses, 2 governor UNKNOWN, 3 CHAT_UNKNOWN; no source writes | `pinned-state-16fcfeed.json`, `pinned-state-41aa47e5.json`, `pinned-state-bb48d794.json` |
| Identity/TLS private consistency | PASS; key/certificate match, validity, stable hashes and 0600/0700 permissions | `private-identity-consistency.json` |
| Architecture/provenance, changed Python AST/compile and changed-secret scan | PASS; scanner 81 files at implementation checkpoint, zero findings | `architecture-final-code.log`, `secrets-final-code.json` |

The composite test uses real temporary Native/Core/SQLite and the actual chat session/provider/receipt code with synthetic HTTPS response bytes. It then exercises fixture READ, actual Muse proposal extraction, denial without App credentials, duplicate request, STOP and signed readback. Socket/process dispatch and credential mint/remote execute are asserted unused. It is not a paid or LIVE model proof.

Installed acceptance constructs the installed Native with its declared native extras, verifies one shared Core/runner/SQLite, denies a second host, verifies signed durable preview receipts and source-byte pins, and reopens the same temporary profile without renewing authority. `chat=False`, OS identity/TLS/source admission are synthetic; binding WebRuntimeService is not a browser roundtrip. Local `--isolate-filesystem` additionally hid the checkout and isolated filesystem/network/PID namespaces. Hosted packaging uses fresh venvs and isolated Python with no PYTHONPATH/checkout imports; it does not claim that additional namespace mode. The separately required Chrome test provides its own network-isolated browser/temp-Native coverage.

State validation never boots Native on owner data, issues no principal and opens no write transaction. Each exported Python file matches its Git blob; 43 project imports resolve inside the correct export. See [STATE_COMPATIBILITY.json](STATE_COMPATIBILITY.json). The old-main reader was intentionally tested against the copy and refused it; production rollback to it is prohibited.

Final documentation secret scan: **PASS**, 84 changed/untracked files, zero findings. [FINAL_LOCAL_EVIDENCE_SHA256.json](FINAL_LOCAL_EVIDENCE_SHA256.json) pins the local logs, reader certificates and validation scripts; it contains no private state bytes.

## Earlier local checkpoint results

Results below are separate runs with overlapping coverage. **Do not add their counts.** All completed targeted runs shown here have zero failures, errors or skips.

| Scope | Result | Evidence file |
| --- | --- | --- |
| Preserved Muse/session Python tests | 95 PASS | `batch1-chat-python.log` |
| Preserved chat/console JavaScript | 41 PASS | `batch1-chat-node.log` |
| Retained GitHub/Core/credential tests, corrected invocation | 63 PASS | `batch2-github-python-corrected.log` |
| Chat/status/preflight regression fixes | 58 Python PASS; 45 JavaScript PASS | `batch3-green-0.log`, `batch3-green-1.log` |
| Historical command/Gmail contracts before Native wiring | 76 PASS | `batch4-source-contracts.log` |
| Integrated advisory and reviewed input handling | 86 PASS | `batch4-advisory-reviewed.log` |
| Launcher contract | 12 PASS | `batch5-desktop.log` |
| Final advisory/grammar/Gmail/source-seal/credential review | 92 PASS | `final-review-python.log` |
| Final GitHub interrupted-source/expiry/refusal/ACK-loss cases | 14 PASS | `final-edges-github.log` |
| Final chat and console, including superseded-read race | 48 PASS | `final-edges-node.log` |
| Isolated headless Chrome → temporary Native/Core → signed preview receipt | 1 PASS, 17.461 seconds | `browser-advisory-e2e-corrected.log` |
| Isolated installed wheel and sdist, Python 3.12.3 | PASS for both, at packaging checkpoint `5e2d6fce` | `packaging-result.json` |
| Python 3.11 AST compatibility and interpreter compilation | PASS, 602 Python files | Coordinator check; repeated in required CI |
| One-system architecture/provenance/ownership checks | PASS | `python3 -B -m runtime.tools.nonzero_architecture --project-root .` |
| Changed-file secret scan against frozen main, including untracked reports | PASS, 78 files, zero findings | `changed-secrets-final.json` (private) |

`LOCAL_EVIDENCE_SHA256.json` records the hashes of original private logs and the package result. Full logs remain in the owner's private consolidation directory; hosted CI provides the publicly inspectable final run. They contain synthetic fixture outputs, not live Muse/remote-effect acceptance.

The browser test uses network-isolated Chrome, synthetic TLS/owner admission and a temporary real Core/SQLite audit. Pairing rows are explicitly presentation fixtures; the two new preview clicks call the real Native dispatcher and independently verify the persisted receipt signatures. It is not physical Android acceptance or production browser/session qualification.

Packaging hides the source checkout, clears PYTHONPATH and isolates network/PID namespaces. Pure recovered grammar/MIME/PKCE contracts import from the installed distribution. Its checkpoint predates the final conservative grammar/input fixes; full CI rebuilds the final candidate. It does not certify installing over the production profile.

## Failures and incomplete runs retained honestly

- The pre-fix regression run reproduced six intended failures. The corresponding green runs passed after the fixes.
- An initial GitHub test invocation used a nonexistent module name; the corrected invocation passed. This was a harness error, not a skipped test.
- Early advisory tests exposed the wrong fixture capability and canonical tuple handling. Those were corrected before the integrated passing runs.
- Review identified shell composition being classified too optimistically and ordinary draft input errors invalidating the panel. Conservative classification, local size checks and signed input refusals now have regression coverage.
- The first extended browser test used a nonexistent navigation selector. The corrected test uses the existing `repositories` page and passed through real Core previews.
- The first changed-file secret scan flagged a synthetic test-token literal. It was replaced with an explicitly constructed low-entropy fixture; scanner rules were not weakened. The final pre-publication scan passed all 78 candidate files.
- **Full local Core discovery: INTERRUPTED, not PASS.** After roughly 20 minutes in an unchanged repeated-pairing/SQLite audit-growth case, only the coordinator's test child was interrupted. The live Native was untouched. `full-core.log` preserves the KeyboardInterrupt. No partial dot count is reported as completed tests, and no test was removed or marked skipped. This interrupted local run remains a failure/incomplete artifact; the later 41aa baseline hosted run completed the full suite. The new implementation is qualified only by its own required CI.

## Additional negative evidence retained

- Earlier `bf9efb64` CI: Python 3.11 isolated Chrome timed out at its existing 15-second `wait()`; full Core and the other jobs passed. The later 41aa run passed all six jobs. No timeout was weakened or test disabled.
- Initial private state-validator run failed because the harness passed nested MappingProxy values into `EffectWarrant.from_dict`. Canonical JSON decoding corrected the harness; the original failure log is preserved alongside corrected, source-pinned passing runs. No product/state data were changed.
- Source-pinned old-main 2be reader fails on the current copied v3 state with `GovernorError: INVALID_GOVERNOR_AMOUNT`. This is an expected negative compatibility result, not a successful rollback or production test.

## Reproduction and required CI

From the reviewed source checkout with its declared dependencies:

```bash
python3 -B -m unittest discover -s tests -p 'test_native_advisory.py'
python3 -B -m unittest discover -s tests -p 'test_native_github_write.py'
node --test tests/mobile_chat.test.cjs tests/mobile_devices.test.cjs
/usr/bin/python3 -B tests/mobile_device_console_browser.py
python3 -B tests/packaging_acceptance.py --output /tmp/aioa-reviewed-packaging
python3 -B -m runtime.tools.nonzero_architecture --project-root .
python3 -B scripts/check_changed_secrets.py --base 2be99da7aa07f7eb5faa9459fe8a78c5d0b6653a
git diff --check
```

The browser/packaging harnesses require their existing qualified Linux sandbox prerequisites; never replace them with a host-network browser to claim acceptance. The `.github/workflows/nonzero-pr.yml` jobs run installed packaging, isolated browser, JavaScript transport, full unittest discovery, NonZero regressions, architecture/provenance, existing Ruff scopes and Python compilation on Python 3.11/3.12. The separate MCP workflow remains required. Retain the workflow's exact existing optional-dependency skip allowlist; new unexplained skips fail acceptance.

## External acceptance not performed

No paid Muse call, GitHub branch/commit/PR effect through AIOA, Gmail send, production deployment, physical Android test or long GOLD run was performed. Missing credentials, exact owner warrants, retained UNKNOWN liabilities and unbound Native capabilities remain blockers. Publishing the source integration PR is repository development work and must not be presented as Muse autonomously executing GitHub WRITE.
