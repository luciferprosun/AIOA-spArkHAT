# Judge-safe architecture

## Outcome

AIOA separates model-assisted investigation from consequential authority. The portable path uses one
Strands agent and five bounded tools, but deterministic code owns policy, approval binding,
idempotency, recovery, execution, and independent verification. The default path is offline and
provider-neutral; AWS is optional and is not needed to judge the product.

## Components and trust boundaries

```mermaid
flowchart TB
    subgraph HumanBoundary[Human authority boundary]
        H[Human operator]
        C[CLI / loopback console]
    end

    subgraph AgentBoundary[Suggestion and investigation boundary]
        S[One Strands Agent]
        T1[query_resource]
        T2[read_utilization]
        T3[build_evidence]
        T4[plan_remediation]
        T5[verify_outcome]
        M[Deterministic mock model]
    end

    subgraph AuthorityBoundary[Deterministic Non-Zero authority plane]
        P[Immutable proposal + evidence hashes]
        G{Approval / denial gate}
        I[Nonce + semantic idempotency]
        R[Durable recovery / reconciliation]
    end

    subgraph EffectBoundary[Bounded effect and proof boundary]
        X[Mock provider executor]
        V[Independent read-back]
        E[Hash-bound receipt]
    end

    H --> C --> S
    M --> S
    S --> T1 --> T2 --> T3 --> T4 --> P
    P --> G
    H -->|exact decision binding| G
    G -->|deny| E
    G -->|approve| I --> X --> V --> T5 --> E
    R --> G
    R --> I

    AWS[Optional AWS / Bedrock adapters] -. not in portable critical path .-> S
```

The human boundary supplies authority, not merely input. The agent boundary may select and sequence
known capabilities but cannot create a capability or approve a proposal. The effect boundary accepts
only a validated, unexpired, one-time decision. Provider acknowledgement is not treated as success;
independent evidence must close the run.

## Scenario sequence

```mermaid
sequenceDiagram
    participant H as Human
    participant A as Strands agent
    participant G as Non-Zero gate
    participant P as Mock provider
    participant V as Verifier

    A->>G: evidence-bound inert proposal
    G-->>H: exact proposal/evidence hash + challenge
    alt deny
        H->>G: bound denial
        G-->>H: DENIED_BY_HUMAN, zero execution
    else approve
        H->>G: bound approval
        G->>G: persist execution ownership before effect
        G->>P: one allow-listed action
        P-->>G: provider receipt
        G->>V: independent read-back
        V-->>G: evidence hash
        G-->>H: SUCCESS_WITH_EVIDENCE
    else stale, changed, or replayed decision
        H->>G: invalid binding or consumed nonce
        G-->>H: fail-closed rejection, zero mutation delta
    end
```

Restart recovery resumes from durable truth. If an effect may have occurred, reconciliation reads
provider state and the persisted execution receipt before any retry. An identical replay reconciles;
a conflicting replay is rejected.

## Runtime boundary

The canonical container:

- uses a digest-pinned Python 3.12 base and hash-pinned dependency closure;
- runs as declared UID/GID 65532 with no effective capabilities;
- supports read-only root filesystem plus explicit temporary/state mounts;
- starts `python -m aioa_cloudops_agent.portable_server` as PID 1;
- defaults to mock provider, AWS disabled, and declared egress `none`; and
- exposes health and readiness inside the isolated container.

The deterministic CLI proof runs approve, deny, recovery, reconciliation, replay, binding-tamper,
and five fail-closed probes without AWS credentials or external network connections.

## Evidence boundary

Every public claim is linked to a command, test, or committed receipt in
[`DEVPOST_CLAIMS_MATRIX.md`](DEVPOST_CLAIMS_MATRIX.md). B5 evidence is a local-artifact attestation,
not a registry or deployment receipt. The publication manifest inventories every tracked source
file and records why each file is included, transformed, or excluded.

## Explicit non-claims

This architecture has not been proven as a public multi-user service. It does not claim live AWS,
live Bedrock, effective deployed IAM, production availability, a real cloud mutation, an uploaded
container, or a submitted Devpost entry.
