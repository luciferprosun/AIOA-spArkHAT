"""Integration checks for public projection and the retired Local API boundary."""
import http.client
import json
import unittest

from runtime.nonzero_cloudops.provenance import public_evidence
import test_nz11_coding_web as coding_web


class E17OperatorBoundaryTests(unittest.TestCase):
    def test_retired_workspace_route_has_no_listener_operation(self):
        case=coding_web.CodingWebTests("test_existing_panel_bootstrap_reports_the_actual_coding_binding")
        case.setUp()
        self.addCleanup(case.doCleanups)
        conn=http.client.HTTPConnection("127.0.0.1",case.server.server_port,timeout=5)
        self.addCleanup(conn.close)
        conn.request("GET","/api/workspace-demo/runs",headers={"X-AIOA-Session-Token":case.service.csrf_token})
        response=conn.getresponse()
        response.read()
        self.assertEqual(response.status,404)

    def test_shared_projection_omits_nested_private_credentials(self):
        # Fabricated shape markers. Keep values out of failure output.
        markers=["gh"+family+"_"+"S"*40 for family in "opusr"]
        payload={"observations":[{"text":"synthetic "+v,"authorization":v} for v in markers],"state":"INERT"}
        result=public_evidence(payload)
        encoded=json.dumps(result)
        self.assertTrue(all(v not in encoded for v in markers),"public projection retained a synthetic marker")
        self.assertEqual(result["state"],"INERT")
        self.assertTrue(all(set(row)=={"text"} for row in result["observations"]),"private keys remained visible")
