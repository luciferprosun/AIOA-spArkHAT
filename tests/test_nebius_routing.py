from __future__ import annotations

from datetime import datetime, timedelta, timezone
import contextlib
from dataclasses import replace
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from runtime.mission.lite_contracts import LiteBudget
from runtime.providers.nebius_routing import (
    EscalationCondition,
    ModelRole,
    NebiusModelRouter,
    NebiusProviderPort,
    RouteBudget,
    RoutingError,
    create_lite_nebius_provider,
)
from runtime.core_admission import OwnerScope
from runtime.mission.lite_contracts import LiteProfile
from runtime.mission.lite_cli import run_lite_cli
from runtime.providers.nvidia import ProviderError, ProviderRequest
from runtime.providers.exact import ProviderResult


LIGHTNING = "nvidia/Nemotron-3_5-Lightning"
SUPER = "nvidia/nemotron-3-super-120b-a12b"
ULTRA = "nvidia/Nemotron-3-Ultra-550b-a55b"


def catalog_receipt(models=(LIGHTNING, SUPER, ULTRA), *, age=timedelta(minutes=1)):
    return {
        "schema": "aioa.nebius-live-probe.v1",
        "created_utc": (datetime.now(timezone.utc) - age).isoformat(),
        "provider": "nebius",
        "status": "PASS",
        "catalog_model_count": 25,
        "catalog_nemotron_ids": list(models),
        "requested_model": LIGHTNING,
        "selected_model_in_catalog": LIGHTNING in models,
        "live_catalog_validated": True,
        "authority": "ADVISORY_ONLY",
        "fallback": False,
        "response_content_persisted": False,
    }


def route_budgets():
    return {
        ModelRole.FAST: RouteBudget(8192, 128, 20, "0.01"),
        ModelRole.BALANCED: RouteBudget(16384, 256, 25, "0.05"),
        ModelRole.ULTRA: RouteBudget(32768, 512, 30, "0.10"),
    }


class FakeExactProvider:
    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.calls = []

    def generate_exact(self, request, cancellation, deadline):
        self.calls.append(request)
        return ProviderResult(
            content=json.dumps({"summary": "Advice only", "needs_attention": False}),
            provider_connection_id="nebius", requested_model=request.requested_model,
            reported_model=request.requested_model, identity_status="EXACT_MATCH",
            request_id="fixture-request", usage={"prompt_tokens": 9, "completion_tokens": 5,
                                                   "total_tokens": 14},
            finish_reason="stop", transport_scope="LIVE", latency_ms=2,
        )


def quote(model=LIGHTNING, *, age=timedelta(minutes=1), input_rate="1", output_rate="1"):
    return {
        "model_id": model, "currency": "USD", "input_usd_per_million": input_rate,
        "output_usd_per_million": output_rate,
        "quoted_utc": (datetime.now(timezone.utc) - age).isoformat(),
        "input_bound_policy": "utf8-bytes-plus-framing-v1",
    }


class NebiusRoutingTests(unittest.TestCase):
    def test_exact_live_catalog_ids_map_to_roles_without_rewriting(self):
        router = NebiusModelRouter(catalog_receipt(), role_budgets=route_budgets())
        self.assertEqual(LIGHTNING, router.select(ModelRole.FAST).model_id)
        self.assertEqual(SUPER, router.select(ModelRole.BALANCED).model_id)
        self.assertEqual(
            ULTRA,
            router.select(ModelRole.ULTRA,
                          escalation=EscalationCondition.OPERATOR_REQUEST).model_id,
        )

    def test_ultra_requires_explicit_escalation_condition(self):
        router = NebiusModelRouter(catalog_receipt(), role_budgets=route_budgets())
        with self.assertRaises(RoutingError) as caught:
            router.select(ModelRole.ULTRA)
        self.assertEqual("ESCALATION_REQUIRES_EXPLICIT_CONDITION", caught.exception.code)

    def test_unavailable_role_fails_closed_without_fallback(self):
        router = NebiusModelRouter(
            catalog_receipt((LIGHTNING, SUPER)), role_budgets=route_budgets())
        with self.assertRaises(RoutingError) as caught:
            router.select(ModelRole.ULTRA,
                          escalation=EscalationCondition.EVIDENCE_AMBIGUITY)
        self.assertEqual("MODEL_ROLE_UNAVAILABLE", caught.exception.code)

    def test_provider_port_checks_identity_and_usd_ceiling_before_transport(self):
        router = NebiusModelRouter(catalog_receipt(), role_budgets=route_budgets())
        route = router.select(ModelRole.FAST)
        built = []
        port = NebiusProviderPort(
            route, LiteBudget(), quote(), secret_supplier=lambda: "fixture-not-a-real-key",
            provider_factory=lambda **kwargs: built.append(FakeExactProvider(**kwargs)) or built[-1],
        )
        wrong_identity = ProviderRequest("req-1", "trace-1", "nebius", SUPER, "{}", "res-1", 64, 10)
        with self.assertRaises(ProviderError) as caught:
            port.estimated_units(wrong_identity)
        self.assertEqual("MODEL_NOT_FOUND", caught.exception.code)
        self.assertEqual([], built)

        over_ceiling = NebiusProviderPort(
            replace(route, budget=RouteBudget(8192, 128, 20, "0.000001")),
            LiteBudget(), quote(input_rate="100", output_rate="100"),
            secret_supplier=lambda: "fixture-not-a-real-key",
            provider_factory=lambda **kwargs: built.append(FakeExactProvider(**kwargs)) or built[-1],
        )
        request = ProviderRequest("req-2", "trace-2", "nebius", LIGHTNING,
                                  "safe input", "res-2", 128, 20)
        with self.assertRaises(ProviderError) as caught:
            over_ceiling.estimated_units(request)
        self.assertEqual("BUDGET_EXCEEDED", caught.exception.code)
        self.assertEqual([], built)

    def test_provider_port_preserves_exact_identity_and_advisory_authority(self):
        router = NebiusModelRouter(catalog_receipt(), role_budgets=route_budgets())
        route = router.select(ModelRole.FAST)
        built = []
        port = NebiusProviderPort(
            route, LiteBudget(), quote(), secret_supplier=lambda: "fixture-not-a-real-key",
            provider_factory=lambda **kwargs: built.append(FakeExactProvider(**kwargs)) or built[-1],
            clock=lambda: 100,
        )
        request = ProviderRequest("req-3", "trace-3", "nebius", LIGHTNING,
                                  "safe input", "res-3", 128, 20)
        reservation_units = port.estimated_units(request)
        self.assertGreater(reservation_units, 0)
        response = port.request(request)
        self.assertEqual(LIGHTNING, response.model_id)
        self.assertEqual("ADVISORY_ONLY", response.authority)
        self.assertEqual("EXACT_MATCH", response.safe_metadata["identity_status"])
        self.assertEqual(1, len(built[0].calls))
        self.assertEqual("LIVE", built[0].calls[0].transport_scope)

    def test_stale_catalog_or_price_quote_fails_closed(self):
        with self.assertRaises(RoutingError) as caught:
            NebiusModelRouter(catalog_receipt(age=timedelta(days=2)),
                              role_budgets=route_budgets())
        self.assertEqual("STALE_MODEL_CATALOG", caught.exception.code)
        router = NebiusModelRouter(catalog_receipt(), role_budgets=route_budgets())
        with self.assertRaises(ProviderError) as caught:
            NebiusProviderPort(router.select(ModelRole.FAST), LiteBudget(),
                               quote(age=timedelta(days=2)),
                               secret_supplier=lambda: "fixture-not-a-real-key")
        self.assertEqual("STALE_COST_QUOTE", caught.exception.code)

    def test_running_port_rechecks_catalog_and_quote_freshness_before_each_reservation(self):
        now = [datetime.now(timezone.utc)]
        router = NebiusModelRouter(catalog_receipt(), role_budgets=route_budgets(), now=now[0])
        route = router.select(ModelRole.FAST)
        built = []
        port = NebiusProviderPort(
            route, LiteBudget(), quote(), policy_clock=lambda: now[0],
            secret_supplier=lambda: "fixture-not-a-real-key",
            provider_factory=lambda **kwargs: built.append(FakeExactProvider(**kwargs)) or built[-1],
        )
        request = ProviderRequest("req-stale", "trace-stale", "nebius", LIGHTNING,
                                  "safe input", "res-stale", 128, 20)
        self.assertGreater(port.estimated_units(request), 0)
        now[0] += timedelta(days=2)
        with self.assertRaises(ProviderError) as caught:
            port.estimated_units(request)
        self.assertEqual("STALE_MODEL_CATALOG", caught.exception.code)
        self.assertEqual([], built)

    def test_lite_profile_can_bind_only_an_explicit_exact_nebius_route(self):
        profile = LiteProfile(
            OwnerScope("tenant", "owner", "space", "slot"), "watch", "source",
            provider_id="nebius", model_id=LIGHTNING, route_role="FAST",
        )
        self.assertEqual("nebius", profile.provider_id)
        self.assertEqual(LIGHTNING, profile.model_id)
        self.assertEqual("FAST", profile.route_role)

    def test_lite_port_factory_requires_catalog_quote_and_explicit_ultra_escalation(self):
        budget = LiteBudget()
        fast = create_lite_nebius_provider(
            model_id=LIGHTNING, route_role="FAST", escalation_condition=None,
            budget=budget, catalog_receipt=catalog_receipt(), cost_quotes={LIGHTNING: quote()},
            usd_ceiling="0.01", secret_supplier=lambda: "fixture-not-a-real-key",
            provider_factory=lambda **kwargs: FakeExactProvider(**kwargs),
        )
        self.assertEqual(LIGHTNING, fast.model_id)
        with self.assertRaises(RoutingError) as caught:
            create_lite_nebius_provider(
                model_id=ULTRA, route_role="ULTRA", escalation_condition=None,
                budget=budget, catalog_receipt=catalog_receipt(), cost_quotes={ULTRA: quote(ULTRA)},
                usd_ceiling="0.10", secret_supplier=lambda: "fixture-not-a-real-key",
                provider_factory=lambda **kwargs: FakeExactProvider(**kwargs),
            )
        self.assertEqual("ESCALATION_REQUIRES_EXPLICIT_CONDITION", caught.exception.code)

    def test_lite_cli_constructs_nebius_route_from_host_injected_policies(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            catalog_path, quotes_path, manifest_path = (
                root / "catalog.json", root / "quotes.json", root / "manifest.json")
            catalog_path.write_text(json.dumps(catalog_receipt()), encoding="utf-8")
            quotes_path.write_text(json.dumps({LIGHTNING: quote()}), encoding="utf-8")
            manifest_path.write_text(json.dumps({
                "profile_id": "aioa-lite-agent-v1", "manifest_version": 1,
                "owner_scope": {"tenant_id": "tenant", "owner_id": "owner",
                                "space_id": "space", "slot_id": "slot"},
                "watch_id": "watch", "observation_source_ref": "source",
                "provider_id": "nebius", "model_id": LIGHTNING, "route_role": "FAST",
            }), encoding="utf-8")

            class ReadOnlyRuntime:
                def __init__(self, profile):
                    self.profile = profile

                def lite_status(self):
                    return {"state": "IDLE", "provider_id": self.profile.provider_id}

                def close(self):
                    pass

            environment = {
                "HOME": os.environ.get("HOME", directory),
                "AIOA_NEBIUS_CATALOG_RECEIPT": str(catalog_path),
                "AIOA_NEBIUS_COST_QUOTES": str(quotes_path),
                "AIOA_NEBIUS_USD_CEILING": "0.01",
            }
            output = io.StringIO()
            with patch.dict(os.environ, environment, clear=True), contextlib.redirect_stdout(output):
                result = run_lite_cli(
                    ["doctor", "--manifest", str(manifest_path), "--tenant", "tenant",
                     "--owner", "owner", "--space", "space", "--slot", "slot",
                     "--source-id", "source", "--state-root", str(root / "state")],
                    runtime_factory=lambda **kwargs: ReadOnlyRuntime(kwargs["lite_profile"]),
                )
            self.assertEqual(0, result)
            self.assertIn('"provider_id": "nebius"', output.getvalue())
            self.assertIn('"key_present": false', output.getvalue())


if __name__ == "__main__":
    unittest.main()
