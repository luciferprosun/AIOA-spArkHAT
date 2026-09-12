# Portable AWS Dependency Inventory — B0 Re-attestation

## Re-attested identity

- baseline commit: `6a83e1a09a26b6572edea52e728e3d51857035e3`
- baseline branch: `main` before the local portable work branch
- baseline suite: `1291 passed`, `0 failed`, `0 skipped`, `1109.38s`
- baseline environment: AWS credential/profile/region variables removed and EC2 metadata disabled
- live AWS calls or mutations: `0`

This inventory describes the current application boundaries rather than treating historical release
reports as proof. The installed `strands-agents==1.53.0` distribution itself declares `boto3` and
`botocore` dependencies. Their package presence is therefore a constraint of the required Strands
version, not evidence that portable execution selects or calls AWS.

## Architecture inventory

| Concern | Canonical implementation |
| --- | --- |
| application entrypoints | canonical `scripts/run_portable_demo.py`; retained interactive/local phase launchers and historical Phase 3 jury proof |
| Strands Agent construction | `agent/factory.py::create_primary_agent` |
| model provider boundary | `providers/model.py::ModelProvider` and `MockModelProvider` |
| AWS model integration | `agent/factory.py::create_bedrock_model` |
| registered tools | the five-tool surface in `agent/factory.py`; no portable expansion |
| policy / authority | `domain/authority.py`, `nz/authority.py`, `cloudops/plan_remediation.py`, `safety/policy.py` |
| approval and hash binding | `agent/hitl.py`, `agent/approval_flow.py`, `agent/local_hitl.py` |
| evidence and verification | `cloudops/evidence_models.py`, `cloudops/build_evidence.py`, `verification/`, Local-2 read-back |
| durable state | repository protocols plus local atomic files and optional DynamoDB adapters under `persistence/` |
| checkpoint / recovery | `persistence/recovery.py`, `recovery/coordinator.py`, Local-2 receipt reconciliation |
| replay / idempotency | `persistence/idempotency.py`, `persistence/semantic_idempotency.py`, Local-2 decision and execution keys |
| local API | loopback-only `local_api/` with bearer-token binding and no cloud dependency |
| AWS judge/runtime | `judge/`, `deployment/`, and Lambda handlers; optional deployed integration only |
| infrastructure | `infra/sam/template.yaml` and IAM policy documents; offline validation or future deployment only |

## AWS classification at the baseline

| Classification | Dependency or boundary | Reason |
| --- | --- | --- |
| `REQUIRED_CORE` | implicit Bedrock default in `create_primary_agent` | Calling the canonical factory without model injection selected Bedrock; B1 must remove this default from the core path. |
| `OPTIONAL_INTEGRATION` | `config/agent.py`, `aws_clients.py`, `create_bedrock_model` | Explicit Bedrock configuration and bounded client construction remain useful when AWS is later selected. |
| `OPTIONAL_INTEGRATION` | `judge/`, `deployment/`, `handlers/`, `remediation/lambda_handler.py` | Deployed judge, Secrets Manager, Lambda, X-Ray, DynamoDB, EC2 and CloudWatch composition. |
| `OPTIONAL_INTEGRATION` | DynamoDB repositories and AWS-shaped EC2/CloudWatch client protocols | Live adapters are preserved; local implementations satisfy the same application contracts. |
| `OPTIONAL_INTEGRATION` | `infra/`, `requirements/phase3-*`, deployment and cleanup contracts | Offline-verifiable deployment material, not portable startup authority. |
| `TEST_ONLY` | AWS settings/client/IAM/IaC and Day 15 tests plus synthetic fixtures | They prove fail-closed AWS contracts using fakes and static documents. |
| `DEMO_ONLY` | historical Bedrock compatibility spike and future-live placeholders | They document prior bounded attempts; the deterministic jury path is local. |
| `LEGACY` | Day 15 deployment-blocker evidence and Phase 3 deployment-ready wording | Retained provenance; it cannot define the new portable critical path. |
| `UNUSED` | AgentCore | No AgentCore source integration exists and none is required for portable execution. |

The transitive `boto3`/`botocore` packages required by Strands are not counted as an operational
`REQUIRED_CORE` AWS integration: portable mode creates no AWS client, performs no credential
discovery, and permits no AWS call. Removing those packages would require changing the pinned
hackathon framework and is intentionally outside this phase.

## External side-effect boundaries

Real AWS clients can originate only from the lazy constructors in `aws_clients.py` or the explicitly
deployed composition in `judge/composition.py`. The private EC2 stop and Lambda invocation paths stay
behind existing settings, authority, approval, emergency-veto, idempotency, and verification gates.
The local mock executor accepts neither a boto client nor arbitrary shell commands and can mutate
only its separately persisted sandbox inventory.

## B0 portable contract

`AIOA_RUNTIME_MODE=portable`, `AIOA_MODEL_PROVIDER=mock`, and
`AIOA_AWS_INTEGRATION_ENABLED=false` are the safe defaults. Portable composition rejects any AWS
runtime settings. Selecting `aws/bedrock` requires the explicit opt-in plus explicit Bedrock model
and region configuration; absence or mismatch fails closed and never falls back to mock.

B1 must route canonical default model construction through one provider factory so the baseline
`REQUIRED_CORE` Bedrock default becomes `OPTIONAL_INTEGRATION` while Strands remains the agent
framework.

## B1 closure

The canonical default now resolves through `providers/factory.py::create_model_provider` to the
deterministic mock Strands model. `create_bedrock_model` moved behind that provider module and imports
the Bedrock/AWS client implementation only inside the explicitly selected constructor. Therefore the
application-level operational count after B1 is:

```text
REQUIRED_CORE AWS integrations = 0
OPTIONAL_INTEGRATION Bedrock/AWS paths = preserved
```

The Strands distribution's transitive AWS SDK packages remain installed for the reason documented
above, but portable startup creates no AWS object and grants no AWS call authority.

## B2 closure

`scripts/run_portable_demo.py` is the canonical deterministic judge command. It invokes the real
five-tool Strands Agent and embeds the existing approve/deny/fail-closed/replay/recovery verifier
receipt in one hash-bound portable evidence bundle. The sandbox creates no AWS client, socket, shell
or external resource. Approved execution changes one isolated local mock resource; denial, binding
failure, malformed output, provider failure, replay and recovery add zero mutations.
