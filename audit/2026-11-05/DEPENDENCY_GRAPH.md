# Dependencies and activation boundaries

Base: `2be99da7aa07f7eb5faa9459fe8a78c5d0b6653a`. The graph describes one composition, not permission to activate every node.

```mermaid
flowchart TD
  UI[White Hole Mission Control] --> Session[Existing TLS and private operator session]
  Android[Android channel] --> Session
  Session --> Core[CoreAdmission and existing TransactionRunner]
  Core --> Chat[Muse chat and owner session]
  Chat --> Provider[Existing exact Meta provider]
  Core --> Preview[Pure command and email previews]
  Core --> Read[Bounded GitHub and local Git READ]
  Chat --> Proposal[Untrusted task proposal]
  Proposal --> Review[Core validation and exact owner review]
  Review --> Warrant[Warrant and durable START]
  Warrant --> Guard[ServiceGuard]
  Guard --> Git[Scoped create-only Git adapter]
  Git --> Verify[Independent GitHub GET]
  Preview --> Audit[Existing SQLite audit and signed receipts]
  Read --> Audit
  Provider --> Audit
  Verify --> Audit
  Audit --> UI
  Core -. requires native binding .-> CPL[Canonical CPL 1+3+1]
  Core -. requires native binding .-> Worker[Bounded worker]
  Core -. requires HAT and persistence binding .-> Memory[MemoryPatch and NativeLearning]
  Core -. requires native orchestration binding .-> NZ[NonZero CloudOps]
```

- G0/G1: preserve source capsule, OS owner admission, host identity, transaction scope, exact warrants, UNKNOWN and no-retry contracts before any effect adapter.
- Chat/READ and pure previews do not enable worker, semantic memory, CPL or GitHub WRITE.
- Git WRITE additionally needs scoped local App configuration, current installation permission check, resolved owner liabilities and an exact live proposal/warrant. A CLI OAuth token is not a fallback.
- Native worker needs canonical orchestration/CPL binding and qualified sandbox admission; the existing OFFLINE_FIXTURE guard remains. A lambda that always approves is not a CPL integration.
- Memory/knowledge need a borrowed current transaction factory, explicit selected HAT and consent. Historical SQLite stores are not dependencies to reintroduce.
- Gmail sending needs an actual Core effect gate, current account enrollment and transport/readback contract. Pure MIME/PKCE helpers do not satisfy them.
- External legal corpus requires pinned manifest/index/source identity and provenance/rights review. Its absence does not block ordinary Native chat.
- Android build/pairing verification remains a separate channel gate; no SDK, device or alternate gateway is started for this Linux integration.
