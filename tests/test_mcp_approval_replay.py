"""A–O offline matrix. Public fixture signatures never authorize real effects."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest

from tests import test_mcp_approval as approval_tests

NOW = approval_tests.NOW
from runtime.mcp_bridge import evaluate_task
from runtime.mcp_bridge.contracts import ContractError, RiskClass
from runtime.mcp_bridge.policy import PolicyEffect
from runtime.mcp_bridge.approval_replay import FixtureReplayJournal, ReplayState


class MCPApprovalReplayTests(unittest.TestCase):
    sign = approval_tests.MCPApprovalTests.sign

    def setUp(self):
        approval_tests.MCPApprovalTests.setUp(self)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'fixture.sqlite'
        self.journal = FixtureReplayJournal(self.path)

    def run_fixture(self, token=None, task=None, **kw):
        return self.journal.simulate(token or self.token, task or self.task,
                                     scope='fixture-branch', resource='README.md', now=NOW, **kw)

    def count(self, table):
        with sqlite3.connect(self.path) as db:
            return db.execute('SELECT count(*) FROM ' + table).fetchone()[0]

    def denied(self, token=None, task=None, reason='binding', **kw):
        with self.assertRaisesRegex(ContractError, reason):
            self.run_fixture(token, task, **kw)
        self.assertEqual(self.count('fixture_effects'), 0)
        self.assertGreater(self.count('denials'), 0)

    def child(self, *, fault='NONE', reconcile=False, crash=False):
        # Fresh interpreter, no credentials, network, signer or executor.
        code = '''
import json, sys, os
from pathlib import Path
from datetime import datetime, timezone
from runtime.mcp_bridge.approval import ApprovalToken
from runtime.mcp_bridge.approval_replay import FixtureReplayJournal
from runtime.mcp_bridge.task_bus import parse_task
from runtime.mcp_bridge.task_bus import TASK_FENCE
v=json.load(sys.stdin)
task=parse_task('```'+TASK_FENCE+'\\n'+json.dumps(v['task'])+'\\n```')
j=FixtureReplayJournal(Path(v['path']))
if v['crash']:
    j._recover = lambda *args: os._exit(73)
method=j.reconcile if v['reconcile'] else j.simulate
kw={} if v['reconcile'] else {'fault':v['fault']}
r=method(ApprovalToken.from_dict(v['token']), task, scope='fixture-branch', resource='README.md', now=datetime(2026,10,10,12,tzinfo=timezone.utc), **kw)
print(json.dumps({'state':r.state.value,'receipt':r.receipt_id,'liability':r.liability_id,'authority':r.grants_effect_authority}))
'''
        result = subprocess.run([sys.executable, '-B', '-c', code], input=json.dumps(
            dict(path=str(self.path), token=self.token.to_dict(), task=self.task.to_dict(),
                 fault=fault, reconcile=reconcile, crash=crash)), text=True, capture_output=True, timeout=10)
        if crash:
            self.assertEqual(result.returncode, 73, 'fixture did not crash at START boundary')
            return None
        self.assertEqual(result.returncode, 0, 'fresh-process fixture failed')
        return json.loads(result.stdout)

    def test_A_valid_synthetic_approval_one_effect_receipt(self):
        result = self.run_fixture()
        self.assertIs(result.state, ReplayState.APPLIED)
        self.assertIsNotNone(result.receipt_id)
        self.assertFalse(result.grants_effect_authority)
        self.assertEqual(self.count('fixture_effects'), 1)
        self.assertEqual(self.count('starts'), 1)
        self.assertEqual(evaluate_task(self.task).effect, PolicyEffect.REQUIRE_HUMAN)

    def test_B_issue_edited_after_approval_denied(self):
        self.task.payload['path'] = 'edited.md'
        self.denied()

    def test_C_identical_redelivery_returns_receipt(self):
        first = self.run_fixture()
        self.assertEqual(first, self.run_fixture())
        self.assertEqual(self.count('fixture_effects'), 1)

    def test_D_fresh_process_restart_durable_nonce_barrier(self):
        first = self.child()
        self.assertEqual(first, self.child())
        self.assertEqual(self.count('fixture_effects'), 1)
        self.assertEqual(self.count('starts'), 1)

    def test_E_nonce_reused_with_changed_payload_denied(self):
        self.run_fixture(fault='AFTER_START')
        changed = replace(self.task, payload={'path':'changed.md'})
        token = self.sign(replace(self.token, task_fingerprint=changed.fingerprint))
        self.denied(token, changed, reason='nonce collision')

    def test_F_changed_scope_branch_resource_denied(self):
        for field in ('scope', 'resource'):
            with self.subTest(field=field):
                self.denied(self.sign(replace(self.token, **{field:'other'})))

    def test_G_changed_risk_class_denied(self):
        self.denied(task=replace(self.task, risk=RiskClass.READ))

    def test_H_forged_model_github_approval_denied(self):
        for key in ('model-key', 'github-key'):
            with self.subTest(key=key):
                self.denied(self.sign(replace(self.token, key_id=key)), reason='pinned')

    def test_I_expired_token_denied(self):
        token = self.sign(replace(self.token, issued_at='2026-10-09T11:00:00Z',
                                  expires_at='2026-10-09T13:00:00Z'))
        self.denied(token, reason='valid')

    def test_J_wrong_key_or_signature_denied(self):
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        wrong = Ed25519PrivateKey.from_private_bytes(bytes(range(32)))
        for signature in ('00'*64, wrong.sign(self.token.signing_bytes()).hex()):
            with self.subTest(kind='invalid signature'):
                self.denied(replace(self.token, signature=signature), reason='signature')

    def test_K_nonce_collision_fingerprint_mismatch_audited(self):
        self.run_fixture(fault='AFTER_START')
        task = replace(self.task, task_id='other-task')
        token = self.sign(replace(self.token, task_id=task.task_id, task_fingerprint=task.fingerprint))
        self.denied(token, task, reason='nonce collision')
        with sqlite3.connect(self.path) as db:
            self.assertEqual(db.execute('SELECT reason FROM denials').fetchall(), [('NONCE_COLLISION',)])

    def test_L_lost_ack_unknown_readback_reconcile_no_retry(self):
        first = self.child(fault='LOST_ACK')
        self.assertEqual(first['state'], 'UNKNOWN')
        self.assertTrue(first['liability'])
        self.assertEqual(first, self.child())
        recovered = self.child(reconcile=True)
        self.assertEqual(recovered['state'], 'APPLIED')
        self.assertEqual(recovered, self.child())
        self.assertEqual(self.count('fixture_effects'), 1)
        self.assertEqual(self.count('liabilities'), 1)

    def test_M_crash_after_start_unknown_no_auto_replay(self):
        self.child(fault='AFTER_START', crash=True)
        first = self.child()
        self.assertEqual(first['state'], 'UNKNOWN')
        self.assertEqual(first, self.child())
        self.assertEqual(first, self.child(reconcile=True))
        self.assertEqual(self.count('fixture_effects'), 0)
        self.assertEqual(self.count('liabilities'), 1)

    def test_N_publication_failure_resends_result_not_effect(self):
        first = self.child()
        # Publication is outside this primitive. Dropping the result simulates failure.
        self.assertEqual(first, self.child())
        self.assertEqual(self.count('fixture_effects'), 1)

    def test_O_unicode_variant_fail_closed(self):
        for value in ('cafe\u0301.md', 'bad\x00', 'bad\ud800'):
            with self.subTest(kind='noncanonical unicode'), self.assertRaises(ContractError):
                replace(self.token, resource=value)
        composed = self.sign(replace(self.token, resource='caf\u00e9.md'))
        result = self.journal.simulate(composed, self.task, scope='fixture-branch',
                                       resource='caf\u00e9.md', now=NOW)
        self.assertIs(result.state, ReplayState.APPLIED)
        self.assertEqual(self.count('fixture_effects'), 1)

    def test_concurrent_fresh_process_deliveries_consume_once(self):
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: self.child(), range(2)))
        self.assertTrue(all(r['state'] in ('APPLIED', 'UNKNOWN') for r in results))
        self.assertEqual(self.count('starts'), 1)
        self.assertEqual(self.count('fixture_effects'), 1)
        final = self.child()
        self.assertEqual(final['state'], 'APPLIED')
        self.assertTrue(all(r['receipt'] == final['receipt'] for r in results if r['state'] == 'APPLIED'))

    def test_changed_signed_approval_identity_collides_even_same_task(self):
        self.run_fixture(fault='AFTER_START')
        token = self.sign(replace(self.token, approval_id='22345678-1234-4234-8234-123456789abc'))
        self.denied(token, reason='nonce collision')

    def test_denials_never_create_start_and_keep_private_bindings_out_of_audit(self):
        self.denied(replace(self.token, signature='00'*64), reason='signature')
        self.assertEqual(self.count('starts'), 0)
        with sqlite3.connect(self.path) as db:
            self.assertEqual(db.execute('SELECT reason FROM denials').fetchall(), [('VERIFICATION_DENIED',)])
        self.run_fixture(fault='AFTER_START')
        raw = self.path.read_bytes()
        for private_value in (self.token.nonce, self.token.signature, self.token.task_fingerprint,
                              self.token.approval_id, self.token.scope, self.token.resource):
            self.assertNotIn(private_value.encode(), raw)

    def test_readback_does_not_create_effect_or_resolve_absent_marker(self):
        with self.assertRaisesRegex(ContractError, 'no fixture START'):
            self.journal.reconcile(self.token, self.task, scope='fixture-branch', resource='README.md', now=NOW)
        before = self.run_fixture(fault='AFTER_START')
        after = self.journal.reconcile(self.token, self.task, scope='fixture-branch', resource='README.md', now=NOW)
        self.assertEqual(before, after)
        self.assertEqual(self.count('fixture_effects'), 0)
        with sqlite3.connect(self.path) as db:
            self.assertEqual(db.execute('SELECT resolved FROM liabilities').fetchall(), [(0,)])


if __name__ == '__main__':
    unittest.main()
