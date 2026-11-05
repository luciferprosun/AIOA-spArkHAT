# Consolidation validation — pre-CI evidence

Frozen main: `2be99da7aa07f7eb5faa9459fe8a78c5d0b6653a`. Implementation checkpoint: `11f800f9`; the additional browser/race/lost-ACK tests are recorded in `981bab0d`. This is a pre-CI snapshot. The integration PR's checks, associated with its exact final head SHA, are the authority for the full regression result. No historical test result is promoted to a new production qualification.

## Fresh local results

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
- **Full local Core discovery: INTERRUPTED, not PASS.** After roughly 20 minutes in an unchanged repeated-pairing/SQLite audit-growth case, only the coordinator's test child was interrupted. The live Native was untouched. `full-core.log` preserves the KeyboardInterrupt. No partial dot count is reported as completed tests, and no test was removed or marked skipped. Required hosted CI must finish this suite on the final candidate or report a concrete failure.

## Reproduction and mandatory final CI

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
