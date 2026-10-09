# Final local fixture provenance review

Preparation basis: `238336a10bcbf7991d7d6735ae692e4437f694e3`. Metadata classification does not clear history for publication.

Reviewed all 30 remaining observations: CONFIRMED_FIXTURE=0; LIKELY_FIXTURE_WITH_LIMITATION=30; UNKNOWN=0. Preserved redacted context identifies negative tests, mocked environments, fixture receipt fields or test constructor inputs. Historical blob existence and line bounds were checked. Test placement does not independently establish synthetic origin; all 30 still require human provenance/security review. No UNKNOWN evidence is promoted to PASS.

The exact 30 are reconstructed from the preserved 106-observation triage: exclude explicit nonsecret markers, non-test observations, twelve previously shape-checked observations, the separately reviewed telemetry marker, and two judge_secret_id references (identifiers rather than credential values). The JSON lists object/path/line/category and original observation index, with source-evidence hashes; secret values and raw source are never exported.

Original semantics remain 75 FIXTURE, 5 EXAMPLE_PLACEHOLDER, 26 NON_CREDENTIAL_IDENTIFIER. Raw tracked findings remain 8 category hits; history findings remain 65 blobs / 106 observations. These historical results do not certify secret-free history.

Ten binary objects are separately path/type inventoried; embedded content and redistribution rights remain human-gated. Security release remains BLOCKED_SECURITY_REVIEW. Scanners, allowlists, tests and history were unchanged.
