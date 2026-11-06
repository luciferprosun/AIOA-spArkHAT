# CPL response comparison

The existing `CriticalPromptLoopService.get` result, CLI status and HTTP run
snapshot expose `response_comparison` after a completed run. This is a derived
read projection over the service's existing redacted draft and final response.
Reading it makes no provider request and changes no trace or manifest bytes;
completed historical runs acquire the same projection when reopened.

The selective MIT source is commit
`8e09457cf97669e5f7742a59adaf091ca705ca4f`,
`runtime/epistemic_orchestra/human_review_workspace.py`:
`normalize_response_text` and the descriptive comparisons in
`compare_response_candidates`. The implementation uses the current CPL
responses directly, without the historical Orchestra DTOs, sessions, provider
store, authority flags or separate persistence. Leading blank lines are removed
in linear time instead of repeated list removal.

Schema `aioa.cpl.response-comparison.v1` returns exact UTF-8 fingerprints,
character counts, exact/layout equality and counts of shared or one-sided
unique normalized lines. Layout normalization standardizes line endings and
horizontal whitespace, including inside quoted code; it does **not** establish
semantic equivalence, correctness, consensus or permission. Line order still
matters for equality. The explicit markers are `authority=ADVISORY_ONLY` and
`semantic_equivalence=NOT_EVALUATED`. No response text is added to the projection.

The value is `null` for non-completed runs, missing/blank/non-text responses or
either response above 20,000 characters. Inputs are never truncated to manufacture
equality, and an unavailable comparison does not change final delivery. Existing
plan, five-request, critic, governor, approval and Native deployment gates apply.
This change does not activate Native LIVE CPL or add a UI comparison panel.

Validation covers fingerprints, Unicode, layout and quoted-code distinctions,
line order/counts, bounds, no dispatch or persistence on reads, restart recovery,
real loopback CLI/HTTP equality and installed wheel/sdist availability. Offline
fixture results do not establish live-provider behavior.
