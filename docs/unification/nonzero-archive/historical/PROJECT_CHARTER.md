# Project Charter

## Frozen Product-Level Decisions

| Key | Value |
| --- | --- |
| PROJECT | AIOA Non-Zero CloudOps Agent |
| HACKATHON | AWS Agents for Humans |
| TRACK | Professional Agents |
| LANGUAGE | Python |
| AGENT_ARCHITECTURE | Single Strands Agent |
| MODEL_PLATFORM | Provider-neutral Strands Model; deterministic mock default, Bedrock optional |
| NZ_CONTROL_PLANE | Custom deterministic application layer |
| DURABLE_SOURCE_OF_TRUTH | Local durable contract by default; DynamoDB optional integration |
| EVIDENCE_ARTIFACTS | Local hash-bound receipts by default; S3 optional integration |
| TELEMETRY | Local/OpenTelemetry by default; CloudWatch optional integration |
| AUTHORITY_MODEL | AUTO / PLAN_AND_CONFIRM / NEVER_AUTONOMOUS |
| AGENTCORE | NOT_ON_P0_CRITICAL_PATH |
| NO_LEGACY_CODE_IMPORT | TRUE |
| EXACT_CLOUDOPS_USE_CASE | BOUNDED_IDLE_EC2_REMEDIATION_AGENT |
| PRODUCT_RUNTIME | PORTABLE_FIRST / AWS_OPTIONAL |

## Current Boundary

The project is a bounded idle-EC2 remediation agent for exactly one allow-listed sandbox instance. The canonical maximum tool surface is `inspect_instance`, `read_utilization_metrics`, `build_remediation_evidence`, `stop_sandbox_instance`, and `verify_instance_state`.

The current canonical Strands runtime implements all five bounded tools. Its private EC2 stop path is
live-disabled and has never been invoked against AWS by this project. The credential-free Local-First
path additionally demonstrates provider-neutral resource planning, exact human approval or denial,
protected mock execution, restart reconciliation, and independent verification through the same
Non-Zero run/checkpoint lifecycle. These local application services do not expand the five registered
Strands tools. No AWS deployment or live cloud mutation has been performed.

D-016 is the authorized product-scope review that removes Bedrock, DynamoDB, S3, CloudWatch and
AgentCore from the completion critical path while preserving their optional adapters and historical
deployment contracts. It does not change the single Strands Agent, five-tool cap, authority model,
approval binding, durable ordering, replay protection, verification or audit requirements.
