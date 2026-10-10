# Q04 opt-in typed offline READ advisory projection

`runtime.mcp_bridge.typed_advisory.ReadAdvisoryAdapter` binds the existing
TaskEnvelope and native ProviderRequest through the existing CoreAdmission READ
principal. It does not call any provider or perform an effect. The exact task,
request content, configured model and owner scope enter the binding digest.
A returned TaskResult must match the binding, version, identity, exact model,
complete stop and OFFLINE_FIXTURE mode. Unknown metadata is denied. Artifact
references reuse artifact.get slice limits; questions contain codes and digests,
not free text. Summary, raw audit refs, paths and input text are not exported.

All output remains ADVISORY_ONLY and TRANSPORT_EVIDENCE_ONLY. A digest does not
verify artifact content or prove that a provider or target was contacted. The
adapter does not fetch artifacts, mint human approval, or claim independent
readback. A failed admission leaves the binding available; one successful
admission denies duplicate delivery within this instance. At most 128 bindings
are retained; creating a new adapter is not a durable effect replay barrier.

This is an opt-in offline primitive. The legacy admit_commander_result function
still returns raw observations and must not be used as a public/privacy-safe
projection. Runtime transport integration and durable advisory receipt storage
remain open. approval.status remains BLOCKED_PRIVACY_PROJECTION. No full MCP,
G3/G4, installed E2E, or LIVE gate is promoted by these tests.
