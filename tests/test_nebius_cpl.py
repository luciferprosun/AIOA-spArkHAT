from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from critical_loop.policy import CostPolicy, INPUT_BOUND_POLICY
from critical_loop.service import CriticalPromptLoopService
from providers import ProviderManager
from providers.exact import decode_response
from providers.nebius import DEFAULT_NEBIUS_MODEL


class NebiusCPLTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.environment = patch.dict(
            os.environ,
            {
                "AOIA_HOME": str(self.root / "state"),
                "AIOA_COMPETITION_PROFILE": "nebius-personal-ai",
                "NEBIUS_API_KEY": "test-key-not-a-real-secret",
            },
            clear=True,
        )
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.manager = ProviderManager(self.root / "runtime")
        quote = {
            DEFAULT_NEBIUS_MODEL: {
                "quoted_utc": datetime.now(timezone.utc).isoformat(),
                "currency": "USD",
                "input_usd_per_million": "1",
                "output_usd_per_million": "1",
                "input_bound_policy": INPUT_BOUND_POLICY,
            }
        }
        self.service = CriticalPromptLoopService(
            self.manager,
            self.root / "trace",
            cost_policy=CostPolicy(True, "5", json.dumps(quote)),
        )
        self.addCleanup(self.service.close)
        self.requests = []
        self.transport = patch.object(
            self.manager,
            "generate_exact",
            side_effect=self._generate,
        )
        self.transport.start()
        self.addCleanup(self.transport.stop)

    def _generate(self, request, cancel, deadline):
        request.validate()
        cancel.check(deadline)
        self.assertEqual(request.provider_connection_id, "nebius")
        self.assertEqual(request.transport_scope, "LIVE")
        self.assertEqual(request.requested_model, DEFAULT_NEBIUS_MODEL)
        self.requests.append(request)
        if request.response_schema_json:
            content = json.dumps(
                {
                    "summary": "Bounded advisory finding.",
                    "findings": [
                        {
                            "category": "uncertainty",
                            "severity": "warning",
                            "title": "Needs verification",
                            "detail": "Mock transport proves routing, not factual truth.",
                        }
                    ],
                    "uncertainty": ["Fresh independent evidence is still required."],
                    "evidence_conflicts": [],
                }
            )
        elif len(self.requests) == 5:
            content = "Final advisory response from mocked Nebius transport."
        else:
            content = "Initial advisory draft from mocked Nebius transport."

        raw = json.dumps(
            {
                "id": f"mock-nebius-{len(self.requests)}",
                "model": request.requested_model,
                "choices": [
                    {
                        "message": {"content": content},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": 10,
                    "completion_tokens": 10,
                    "total_tokens": 20,
                },
            }
        ).encode()
        return decode_response(raw, request)
    def test_full_cpl_uses_nebius_for_all_five_calls(self) -> None:
        plan = self.service.plan(
            {
                "prompt": "Review this harmless test request.",
                "evidence": "Synthetic evidence for transport routing only.",
                "run_budget_usd": "1",
            }
        )
        self.assertEqual(plan["plan"]["provider_connection_id"], "nebius")
        self.assertEqual(
            plan["plan"]["models"],
            [DEFAULT_NEBIUS_MODEL] * 4,
        )

        self.service.start(plan["run_id"], plan["plan_hash"], plan["nonce"])
        result = self.service.wait(plan["run_id"], 5)

        self.assertEqual(result["execution_status"], "COMPLETED", result["error"])
        self.assertEqual(result["generation_requests"], 5)
        self.assertEqual(len(self.requests), 5)
        self.assertEqual(
            {request.provider_connection_id for request in self.requests},
            {"nebius"},
        )
        self.assertEqual(
            {request.requested_model for request in self.requests},
            {DEFAULT_NEBIUS_MODEL},
        )


if __name__ == "__main__":
    unittest.main()
