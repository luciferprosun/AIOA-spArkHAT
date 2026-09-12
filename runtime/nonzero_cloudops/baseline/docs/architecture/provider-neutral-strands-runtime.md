# Provider-Neutral Strands Runtime

## Canonical runtime

The application still constructs exactly one `strands.Agent` with the frozen five-tool surface.
`create_model_provider` is the single model-selection boundary and returns a Strands `Model` plus
public-safe runtime metadata. Model output remains untrusted input to the existing Non-Zero policy,
approval, persistence, execution, and verification layers.

```text
AIOA Non-Zero control plane
           |
           v
   one Strands Agent
           |
           v
 create_model_provider
      |          |
      v          v
 deterministic  Bedrock
 mock Model      (explicit AWS integration only)
```

## Selection contract

| Runtime | Provider | Startup contract | Network / AWS |
| --- | --- | --- | --- |
| `portable` | `mock` | safe default; no credential or secret | forbidden / zero |
| `portable` | `bedrock` | rejected | forbidden / zero |
| `aws` | `mock` | rejected | no fallback |
| `aws` | `bedrock` | explicit opt-in plus explicit Bedrock settings | optional integration boundary |

The canonical agent factory now defaults to the deterministic mock Strands model. A caller may
inject a model only through the same resolved provider metadata. Passing explicit historical
`BedrockSettings` derives an explicit AWS selection for compatibility with the preserved deployed
judge composition; it does not affect portable startup.

No paid non-AWS provider dependency is added in this phase. The factory is prepared to add one
officially supported Strands `Model` behind another closed enum value later, but deterministic tests
and the judge demo intentionally require no key, paid API, local LLM, or network service.

## Deterministic provider outcomes

`MockModelProvider` implements both the local `create_plan` protocol and the native Strands `Model`
stream interface. Scripted outcomes cover:

- normal and approval-required proposals;
- malformed and empty output;
- timeout and generic provider errors;
- explicit retryable and non-retryable failures;
- policy-invalid authority claims and denied action requests; and
- a deterministic tool-call sequence for the canonical Strands Agent.

There is no hidden retry in the local planning boundary. Each scripted provider failure is called
once, persisted as a typed terminal result, and cannot become approval or success. The existing
Strands model circuit remains bounded and never replays one invocation internally.

## Failure and secret semantics

Configuration errors use fixed allow-list messages. Provider initialization failures become
`ModelProviderUnavailableError` with a fixed public-safe message; the original exception remains
chained for local debugging but is never rendered into application results. Local flow failures map
to explicit retryable/non-retryable `FailureDetail` values. Unknown exceptions become the fixed
`MODEL_PROVIDER_INVALID_FAILURE` outcome.

No provider selection, model runtime metadata, or `.env.example` field contains a secret. Portable
mode loads no API key, AWS credential, profile, or region from ambient credential discovery.
