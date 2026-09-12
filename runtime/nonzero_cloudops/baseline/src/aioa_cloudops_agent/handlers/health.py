"""Deterministic health endpoint with no AWS authority."""

import json
import os
from typing import Final

from aioa_cloudops_agent.config import AwsSettings

SERVICE_IDENTIFIER: Final = "aioa-nonzero-cloudops-agent"


def lambda_handler(_event: object, _context: object) -> dict[str, object]:
    """Return a deterministic health response without external calls."""

    stage = os.environ.get("APP_STAGE", "hackathon")
    settings = AwsSettings(stage=stage)
    body = {
        "service": SERVICE_IDENTIFIER,
        "stage": settings.stage,
        "status": "ok",
    }
    return {
        "statusCode": 200,
        "headers": {"content-type": "application/json"},
        "body": json.dumps(body, separators=(",", ":"), sort_keys=True),
    }
