"""Run the credential-free Local-First Phase 1 flow against deterministic fixtures."""

import argparse
from datetime import UTC, datetime
from pathlib import Path

from aioa_cloudops_agent.agent import create_local_first_runtime
from aioa_cloudops_agent.cloudops import MOCK_UNATTACHED_EIP_ID
from aioa_cloudops_agent.config import LocalFirstMode, LocalFirstSettings, RuntimeSettings
from aioa_cloudops_agent.nz import (
    BudgetCounters,
    CloudResourceType,
    ResourceQuery,
    ResultStatus,
    Run,
    generate_run_id,
    generate_trace_id,
)


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--state-path",
        type=Path,
        default=Path(".local/aioa-local-phase1-state.json"),
    )
    parser.add_argument("--resource-id", default=MOCK_UNATTACHED_EIP_ID)
    parser.add_argument(
        "--resource-type",
        choices=[item.value for item in CloudResourceType],
        default=CloudResourceType.ELASTIC_IP.value,
    )
    return parser.parse_args()


def main() -> int:
    args = _arguments()
    now = datetime.now(UTC)
    runtime = create_local_first_runtime(
        LocalFirstSettings(mode=LocalFirstMode.MOCK, state_path=args.state_path),
        runtime_settings=RuntimeSettings.from_environment(),
    )
    run = Run.new(
        run_id=generate_run_id(),
        trace_id=generate_trace_id(),
        correlation_id=generate_trace_id(),
        idempotency_key=f"local/demo/{generate_run_id()}",
        created_at=now,
        budget=BudgetCounters(max_turns=8, max_tokens=2_048),
    )
    result = runtime.flow.execute(
        run,
        ResourceQuery(
            resource_type=CloudResourceType(args.resource_type),
            resource_id=args.resource_id,
        ),
    )
    print(result.model_dump_json(indent=2))
    return 0 if result.status is ResultStatus.SUCCESS else 1


if __name__ == "__main__":
    raise SystemExit(main())
