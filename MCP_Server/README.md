# MCP Server Workspace

This directory is the starting point for the MCP Commander / execution-layer work for the Nebius hackathon branch.

## Scope
- Branch: `nebius-personal-ai`
- Main branch remains frozen and must not be modified.
- This workspace is for integrating the independently built MCP Commander architecture with AIOA only after the standalone components are verified.

## Initial principles
- ChatGPT/OpenAI remains the primary planner interface.
- Deterministic execution is delegated to the MCP Commander worker/policy gateway.
- READ and WRITE remain separated.
- Human approval is required outside the model for sensitive WRITE/EXEC actions.
- Nebius/NVIDIA is an optional specialist inference layer for hackathon-specific workloads.
- Heavy local build artifacts and caches should remain on the USB workspace, not committed here.
- No secrets, API keys, tokens, local runtime state, logs, or browser profiles are committed to this repository.

## Next step
Add the first integration adapter and task-bus contract only after the standalone MCP Commander Phase 02 baseline is accepted.
