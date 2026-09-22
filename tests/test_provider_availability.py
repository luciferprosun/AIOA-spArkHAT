"""Provider availability evidence projection tests."""

import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from provider_availability import ENV_PATH, provider_availability


def recovered():
    smoke = "NV_OK"
    return {
        "schema": "aioa.nvidia-provider-recovery.v1",
        "status": "RECOVERED",
        "checked_at_utc": "2026-09-21T07:42:49Z",
        "doctor": {"connectivity": "PASS", "credential_readiness": "SET_LOCAL_FILE"},
        "endpoint_host": "integrate.api.nvidia.com",
        "endpoint_path": "/v1/chat/completions",
        "historical_unknowns_modified": False,
        "model": "nvidia/nemotron-3.5-lightning-30b-a3b",
        "new_24h_trial_started": False,
        "smoke_result": smoke,
        "smoke_result_sha256": hashlib.sha256(smoke.encode()).hexdigest(),
    }


def external():
    return {
        "schema": "aioa.nvidia-provider-availability.v1",
        "status": "EXTERNAL_UNAVAILABLE",
        "checked_at_utc": "2026-09-21T07:17:51Z",
        "endpoint_host": "integrate.api.nvidia.com",
        "model": "nvidia/nemotron-3.5-lightning-30b-a3b",
        "reason": "TIMEOUT",
        "live_call_succeeded": False,
    }


class ProviderAvailabilityTests(unittest.TestCase):
    def project(self, value):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "provider.json"
            path.write_text(json.dumps(value), encoding="utf-8")
            with patch.dict(os.environ, {ENV_PATH: str(path)}):
                return provider_availability()

    def test_not_configured_is_unknown_not_inferred_unavailable(self):
        with patch.dict(os.environ, {}, clear=True):
            value = provider_availability()
        self.assertEqual("NOT_CONFIGURED", value["status"])
        self.assertEqual("UNKNOWN", value["provider_mode"])

    def test_recovery_evidence_projects_live(self):
        value = self.project(recovered())
        self.assertEqual("RECOVERED", value["status"])
        self.assertEqual("LIVE", value["provider_mode"])
        self.assertIs(value["evidence_available"], True)
        self.assertIs(value["read_only"], True)

    def test_external_timeout_projects_explicit_unavailable(self):
        value = self.project(external())
        self.assertEqual("EXTERNAL_UNAVAILABLE", value["status"])
        self.assertEqual("EXTERNAL_UNAVAILABLE", value["provider_mode"])
        self.assertEqual("TIMEOUT", value["reason"])

    def test_bad_recovery_digest_is_rejected(self):
        value = recovered()
        value["smoke_result_sha256"] = "0" * 64
        projected = self.project(value)
        self.assertEqual("INVALID_EVIDENCE", projected["status"])
        self.assertEqual("UNKNOWN", projected["provider_mode"])

    def test_symlink_evidence_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / "provider.json"
            target.write_text(json.dumps(recovered()), encoding="utf-8")
            link = Path(temp) / "provider-link.json"
            link.symlink_to(target)
            with patch.dict(os.environ, {ENV_PATH: str(link)}):
                value = provider_availability()
        self.assertEqual("INVALID_EVIDENCE", value["status"])
        self.assertEqual("UNKNOWN", value["provider_mode"])

    def test_dashboard_requests_read_only_provider_projection(self):
        root = Path(__file__).resolve().parents[1]
        html = (root / "web" / "index.html").read_text(encoding="utf-8")
        script = (root / "web" / "app.js").read_text(encoding="utf-8")
        self.assertIn('id="competition-provider-availability"', html)
        self.assertIn('id="competition-provider-evidence"', html)
        self.assertIn('jsonFetch("/api/provider-availability")', script)
        self.assertNotIn('fetch("/api/provider-availability", {method: "POST"', script)


if __name__ == "__main__":
    unittest.main()
