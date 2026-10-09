# Unified reviewer clock contract

The certification run for PR #16 at `1ddf676` failed three unified-reviewer tests on Python 3.11 and 3.12. The same tests could pass in isolation on a slower machine. The failing assertions required verified independent readback, not merely a successful target response.

The unified fixture advanced its simulated clock by one second per `prepare` or `execute` call. Its independent disposable target process recorded `dispatched_at` using wall time. On a fast runner, approval could therefore be timestamped after the target receipt. `project_shadow_delta` correctly rejected that inconsistent chronology as `UNKNOWN`; filesystem speed could accidentally hide the mismatch.

The correction is confined to the unified fixture in `tests/nv13_unified.py`: reuse wall time through the existing `GuardFixture(clock=...)` interface and stop equating polling with elapsed time. ServiceGuard, the independent target, receipt validation, production clocks and authority gates are unchanged.

The regression polls the approval-required operation twelve times, verifies zero effects before human approval, then requires a verified certificate, one independent effect, one offline advisory call and replay without a second effect after reopening. It failed before the correction and passed afterward. The full focused module passed 19 tests locally. These local observations do not assert that a later CI run passed; current GitHub receipts remain the certification authority for the exact PR head.

Missing/stale CSR metadata, changed context, revoked approval, malformed proofs and stable `UNKNOWN` still prevent reviewer success. No assertion was changed from `VERIFIED` to `UNKNOWN`, no sleep or retry was added, and no paid provider or cloud deployment is involved.
