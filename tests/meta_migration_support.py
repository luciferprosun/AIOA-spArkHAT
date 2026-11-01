"""Explicit offline operator/transaction/provider fixtures; never runtime defaults."""
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import hashlib
import json
from pathlib import Path

from lab.archaioa.authority import AuthorityScope, Money, RiskLevel
from lab.archaioa.decision_root import DecisionDependencyRoot
from lab.archaioa.evidence import EvidenceRef
from lab.archaioa.warrant import EffectWarrant, RevisionPolicy
from runtime.browser_agent.offline_adapter import FIXTURE_ORIGIN, FIXTURE_TEXT, FIXTURE_URL
from runtime.core_admission import Capability, CoreAdmission, LocalOwnerAssignment, OwnerScope
from runtime.memory_patch.contracts.serialization import canonical_sha256
from runtime.memory_patch.persistence.ports import TransactionRunner
from runtime.meta_hackathon.contracts import BrowserTaskV1
from runtime.meta_hackathon.offline_receipts import BudgetReservation, MOCK_RESPONSE_SCHEMA, OfflineReceiptLedger
from runtime.meta_hackathon.provider_offline import OFFLINE_MODEL, build_offline_envelope
from runtime.mission.warrant import CoreWarrantLedger, approval_digest
from nv03_support import DurableFactory


class ReadFixture:
    def __init__(self, root, api, codec):
        self.now = datetime(2026, 6, 1, 12, tzinfo=timezone.utc)
        self.initial = self.now
        self.scope = OwnerScope('fixture-tenant', 'fixture-owner', 'fixture-space', 'fixture-slot')
        self.core = CoreAdmission(LocalOwnerAssignment(self.scope, frozenset({
            Capability.READ, Capability.COMMIT, Capability.OWNER_APPROVAL}),
            frozenset({'fixture-hat'}), frozenset({OFFLINE_MODEL}), operator_approved=True),
            clock=lambda: self.now)
        self.path = Path(root)/'core-fixture.json'
        self.runner = TransactionRunner(self.core, DurableFactory(self.path))
        self.ledger = CoreWarrantLedger(self.core, self.runner, self.scope, clock=lambda: self.now)
        self.task = BrowserTaskV1(task_id='meta-fixture-read', owner_scope_digest=canonical_sha256(self.scope),
            source_sha='1'*40, allowed_origins=(FIXTURE_ORIGIN,), target_url=FIXTURE_URL,
            deadline_utc='2026-06-01T12:05:00Z', operation='navigate_read',
            max_pages=1, timeout_ms=8000, max_chars=1600)
        self.call = codec.ToolCall('call_fixture_read', 'navigate_read', json.dumps({
            key: self.task.to_dict()[key] for key in ('task_id', 'target_url', 'deadline_utc',
                'max_pages', 'timeout_ms', 'max_chars')}, sort_keys=True, separators=(',', ':')))
        self.text = FIXTURE_TEXT
        self.content_sha = hashlib.sha256(self.text.encode()).hexdigest()
        self.api = api
        self.warrant = self.make_warrant()
        envelope = build_offline_envelope(self.task, 'Offline fixture instruction', budget_usd_limit=0.0)
        self.reservation = BudgetReservation(task_digest=self.task.digest,
            owner_scope_digest=self.task.owner_scope_digest, source_sha=self.task.source_sha,
            model=OFFLINE_MODEL, attempt_id='fixture-attempt', nonce='a'*64,
            issued_at_utc='2026-06-01T11:59:59Z', expires_at_utc='2026-06-01T12:05:00Z',
            max_output_tokens=128, max_usd='0.00')
        self.provider_receipt = OfflineReceiptLedger(max_total_usd='0.00').record_once(
            self.reservation, envelope, mock_response_json=json.dumps({
                'schema': MOCK_RESPONSE_SCHEMA, 'model': OFFLINE_MODEL,
                'task_digest': self.task.digest, 'owner_scope_digest': self.task.owner_scope_digest,
                'source_sha': self.task.source_sha, 'attempt_id': 'fixture-attempt',
                'nonce_sha256': self.reservation.nonce_sha256, 'completion_tokens': 0, 'status': 'MOCK_DONE'}),
            mock_cost_usd='0.00', now_utc='2026-06-01T12:00:00Z')

    def make_warrant(self):
        operation = self.api.read_operation(self.task, self.call,
            expected_content_sha256=self.content_sha, initial_utc=self.initial)
        scope = AuthorityScope(operation_classes=(operation['operation_class'],),
            target_scope=operation['target_fingerprint'], risk_ceiling=RiskLevel.LOW,
            monetary_ceiling=Money(Decimal(0), 'USD'), not_before=self.initial,
            expires_at=self.initial+timedelta(seconds=2), owner_scope=self.task.owner_scope_digest,
            task_scope=self.task.task_id)
        warrant = EffectWarrant(warrant_id='fixture-warrant', task_id=self.task.task_id,
            owner_scope=self.task.owner_scope_digest, operation_class=operation['operation_class'],
            operation_hash='sha256:'+canonical_sha256(operation),
            target_fingerprint=operation['target_fingerprint'], expected_target_revision=self.task.source_sha,
            revision_policy=RevisionPolicy.REQUIRE, decision_dependency_root=DecisionDependencyRoot((
                EvidenceRef('fixture-task', 'task', 'sha256:'+self.task.digest, 'v1'),)),
            lease_epoch=0, authority_scope=scope, approval_digest='sha256:'+'0'*64,
            money_reservation_id='NONE', risk_reservation_id='NONE', nonce='fixture-read-nonce',
            issued_at=self.initial, expires_at=self.initial+timedelta(seconds=2))
        return replace(warrant, approval_digest=approval_digest(warrant))

    def principal(self, capability=Capability.READ):
        return self.core.local_operator(capability)

    def approve(self):
        self.ledger.approve(self.principal(Capability.OWNER_APPROVAL), self.warrant)

    def run(self, **changes):
        values = dict(ledger=self.ledger, read_principal=self.principal(),
            commit_principal=self.principal(Capability.COMMIT), task=self.task, call=self.call,
            warrant=self.warrant, current_source_sha=self.task.source_sha,
            expected_content_sha256=self.content_sha, initial_utc=self.initial,
            provider_receipt=self.provider_receipt, fixture_text=self.text)
        values.update(changes)
        return self.api.run_read_once(**values)

    def consumption(self):
        return self.ledger.inspect(self.principal(), self.warrant)

    def close(self):
        self.runner.close(); self.core.close()


def run_demo():
    """Reproducible TEST fixture, not a new product CLI or owner transport."""
    import tempfile
    from runtime.meta_hackathon import mission_read_offline as api
    from runtime.providers import tool_calling as codec
    with tempfile.TemporaryDirectory(prefix='aioa-meta-p01-fixture-') as root:
        fixture = ReadFixture(root, api, codec)
        try:
            fixture.approve()
            return fixture.run()
        finally:
            fixture.close()


if __name__ == '__main__':
    print(json.dumps(run_demo(), sort_keys=True, separators=(',', ':')))
