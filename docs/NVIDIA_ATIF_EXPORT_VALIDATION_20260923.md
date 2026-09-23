# NVIDIA ATIF exporter validation — 2026-09-23

Status: `LOCAL_SCHEMA_VALIDATION_PASS / TEST_FIXTURE_ONLY`

This record documents validation of the read-only AIOA competition-evidence
exporter against NVIDIA's pinned ATIF model. It does not establish LIVE provider
availability, LIVE Nemotron behavior, or a 24-hour certification.

## Scope

Validated implementation:

- `runtime/nvidia_trajectory.py`
- `scripts/nvidia_trajectory_export.py`
- `tests/test_nvidia_trajectory_export.py`
- source artifact: deterministic `aioa.nvidia-competition-demo.v1`
- target schema: `ATIF-v1.7`

The exporter is an evidence projection, not a raw provider transcript. It emits
no hidden reasoning and preserves `TEST_FIXTURE` / non-LIVE claim boundaries.
## Pinned NVIDIA validator

Local validator package:

- package: `nvidia-nat-atif`
- version: `1.7.0`
- reported schema constant: `ATIF-v1.7`
- validation model: `nat.atif.trajectory.Trajectory`

The package was installed outside the repository under the sprint state tree.
No application dependency or production environment was changed.

Official references:

- https://docs.nvidia.com/nemo/agent-toolkit/1.7/api/nat/atif/trajectory/index.html
- https://docs.nvidia.com/nemo/agent-toolkit/latest/api/nat/atif/step/index.html

## Validation result

Focused evidence-audit + exporter regression: `12/12 PASS`.
The NVIDIA model-validation test was enabled rather than skipped.
A fresh deterministic competition demo was then generated with the existing
repository fixture path and exported to ATIF. NVIDIA `Trajectory.model_validate`
accepted the output with:

- 15 sequential steps (`1..15`);
- `schema_version = ATIF-v1.7`;
- `reasoning_content` absent on every step;
- no LIVE provider claim;
- no raw provider trace.

Evidence directory (local sprint state, not committed to the repository):
`atif-validation/20260923T062010Z`

SHA-256:

- demo: `f4ac9dd82a1c1e2c030554f6bb76b42359cf9e9bf867bfca06d097482647e5c0`
- trajectory: `b0a21f243115cda30c37f90d45e34627126652608555c8f7adb83c1a31611f86`

## Claim boundary

Result: `PASS` for local ATIF-v1.7 schema compatibility of this deterministic
TEST_FIXTURE evidence exporter. This is not NVIDIA certification, a LIVE model
trace validation, endpoint validation, benchmark reproduction, or 24h PASS.
