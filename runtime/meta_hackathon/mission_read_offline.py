"""P01 bounded fixture READ: source codec + existing Core/Meta contracts.

The host supplies an already configured CoreWarrantLedger and principals.
No owner admission, approval, backend, native START, network or UI is created
here. Consumption certifies one ledger use only, never a live effect. This
facade cannot be promoted to a filesystem/browser executor by changing a flag.
"""
from datetime import datetime, timezone
import hashlib

from lab.archaioa.authority import RiskLevel
from lab.archaioa.warrant import EffectWarrant
from runtime.browser_agent.offline_adapter import FIXTURE_TEXT, read_fixture
from runtime.browser_agent.offline_state import OfflineState, OfflineTaskState
from runtime.core_admission import Capability
from runtime.memory_patch.contracts.serialization import canonical_json_bytes, canonical_sha256
from runtime.memory_patch.errors import CommitOutcomeUnknown
from runtime.mission.warrant import CoreWarrantLedger
from runtime.providers.exact import CancellationToken, ExactCallError
from runtime.providers.tool_calling import ToolCall, ToolMessage, strict_json
from .contracts import BrowserTaskV1, MetaContractError, _hash, utc_timestamp
from .muse_plan import parse_muse_plan
from .offline_correlation import OfflineCorrelationLedger
from .offline_receipts import ProviderReceipt

OPERATION = 'READ_OFFLINE_FIXTURE_V1'
SCHEMA = 'aioa.meta.migration-read-summary.v1'
PLAN_FIELDS = ('task_id', 'target_url', 'deadline_utc', 'max_pages', 'timeout_ms', 'max_chars')
TOOL_SCHEMA = {'type': 'function', 'function': {'name': 'navigate_read',
    'description': 'Propose one bounded offline fixture READ. Never authority.',
    'parameters': {'type': 'object', 'properties': {
        'task_id': {'type': 'string'}, 'target_url': {'type': 'string'},
        'deadline_utc': {'type': 'string'}, 'max_pages': {'type': 'integer'},
        'timeout_ms': {'type': 'integer'}, 'max_chars': {'type': 'integer'}},
        'required': list(PLAN_FIELDS), 'additionalProperties': False}}}


def _require(ok):
    if not ok:
        raise MetaContractError('META_OFFLINE_READ_DENIED')


def read_operation(task, call, *, expected_content_sha256, initial_utc):
    """Prepare the exact human-review commitment; never approve/consume it."""
    _require(type(task) is BrowserTaskV1 and type(call) is ToolCall)
    _require(type(initial_utc) is datetime and initial_utc.tzinfo is not None)
    _hash(expected_content_sha256)
    try:
        call.validate()
        fields = strict_json(call.arguments_json)
        _require(call.name == 'navigate_read' and set(fields) == set(PLAN_FIELDS))
        parsed = parse_muse_plan({'tool': 'browser.navigate_read', **fields},
            core_owner_scope_digest=task.owner_scope_digest, core_source_sha=task.source_sha,
            allowed_origins=task.allowed_origins, stopped=False, now=initial_utc)
        _require(parsed.digest == task.digest)
    except (ExactCallError, ValueError, TypeError, UnicodeError, RecursionError):
        raise MetaContractError('META_OFFLINE_READ_DENIED') from None
    fingerprint = 'sha256:'+canonical_sha256({'task': task.digest,
                                               'content_sha256': expected_content_sha256})
    return {'operation_class': OPERATION, 'target_fingerprint': fingerprint,
        'expected_target_revision': task.source_sha,
        'payload': {'schema': 'aioa.meta.offline-read-operation.v1',
            'task_digest': task.digest, 'owner_scope_digest': task.owner_scope_digest,
            'source_sha': task.source_sha, 'tool_call_id': call.call_id, 'tool_name': call.name,
            'arguments_sha256': hashlib.sha256(call.arguments_json.encode()).hexdigest(),
            'tool_schema_sha256': canonical_sha256(TOOL_SCHEMA),
            'expected_content_sha256': expected_content_sha256,
            'initial_utc': initial_utc.astimezone(timezone.utc).isoformat(),
            'environment': 'OFFLINE_FIXTURE'}}


def _summary(task, status, *, terminal_state=None, consumed=False):
    return {'schema': SCHEMA, 'status': status, 'terminal_state': terminal_state or status,
        'environment': 'OFFLINE_FIXTURE', 'task_id': task.task_id, 'task_digest': task.digest,
        'owner_scope_digest': task.owner_scope_digest, 'source_sha': task.source_sha,
        'verified': False, 'dispatch_allowed': False, 'core_warrant_consumed': consumed,
        'tool_result': None, 'evidence_digest': None}


def run_read_once(*, ledger, read_principal, commit_principal, task, call, warrant,
                  current_source_sha, expected_content_sha256, initial_utc,
                  provider_receipt, fixture_text=FIXTURE_TEXT, cancel=None):
    """One fixture step over the admitted host's existing one-use Core ledger.

No retry after uncertain consumption or readback. The fixture outcome and mock
provider receipt are labelled offline, even when every Core gate passes.
"""
    _require(type(ledger) is CoreWarrantLedger and type(task) is BrowserTaskV1)
    _require(cancel is None or type(cancel) is CancellationToken)
    _require(provider_receipt is None or type(provider_receipt) is ProviderReceipt)
    core, scope = ledger.core, ledger.scope
    core.require(read_principal, Capability.READ, scope=scope)
    core.require(commit_principal, Capability.COMMIT, scope=scope)
    now = ledger.clock()
    state = OfflineTaskState(task_digest=task.digest, allowed_origins=task.allowed_origins,
        core_owner_scope_digest=canonical_sha256(scope), core_source_sha=current_source_sha,
        task_owner_scope_digest=task.owner_scope_digest, task_source_sha=task.source_sha,
        initial_utc=initial_utc, deadline_utc=utc_timestamp(task.deadline_utc), timeout_ms=task.timeout_ms)
    stopped = lambda: cancel is not None and cancel.cancelled
    if state.preview(stopped=stopped(), now=now) is not OfflineState.PREVIEWED:
        return _summary(task, state.state.value)
    operation = read_operation(task, call, expected_content_sha256=expected_content_sha256,
                               initial_utc=initial_utc)
    _require(type(warrant) is EffectWarrant and warrant.task_id == task.task_id
        and warrant.operation_class == OPERATION
        and warrant.operation_hash == 'sha256:'+canonical_sha256(operation)
        and warrant.target_fingerprint == operation['target_fingerprint']
        and warrant.expected_target_revision == current_source_sha
        and warrant.money_reservation_id == warrant.risk_reservation_id == 'NONE'
        and warrant.authority_scope.monetary_ceiling.amount == 0
        and warrant.authority_scope.monetary_ceiling.currency == 'USD'
        and warrant.authority_scope.risk_ceiling is RiskLevel.LOW)
    try:
        ledger.consume(commit_principal, warrant)
    except CommitOutcomeUnknown:
        return _summary(task, 'UNKNOWN', consumed=None)
    try:
        core.require(read_principal, Capability.READ, scope=scope)
        if stopped():
            return _summary(task, 'STOPPED', consumed=True)
        observation = read_fixture(task, admission=core, principal=read_principal, scope=scope,
            core_owner_scope_digest=canonical_sha256(scope), core_source_sha=current_source_sha,
            stopped=stopped(), now=ledger.clock(), fixture_text=fixture_text,
            expected_content_sha256=expected_content_sha256)
        current = ledger.clock()
        observed = state.observe(task_digest=observation.task_digest, observed_url=observation.observed_url,
            captured_at_utc=observation.captured_at_utc, stopped=stopped(), now=current)
        if observed is not OfflineState.OBSERVED:
            return _summary(task, observed.value, consumed=True)
        proof = OfflineCorrelationLedger().correlate_once(task, observation, provider_receipt,
            observed_content=fixture_text, now_utc=current.astimezone(timezone.utc).isoformat().replace('+00:00', 'Z'),
            stopped=stopped())
        result = _summary(task, proof.status, terminal_state=observed.value, consumed=True)
        result['evidence_digest'] = proof.digest
        if proof.status == 'OFFLINE_LINKED_UNVERIFIED':
            content = canonical_json_bytes({'task_digest': task.digest, 'source_sha': task.source_sha,
                'content_sha256': observation.content_sha256, 'status': proof.status,
                'environment': 'OFFLINE_FIXTURE'}).decode()
            result['tool_result'] = ToolMessage('tool', content, tool_call_id=call.call_id).to_wire()
        return result
    except Exception:
        # Consumption has happened: no exception text, no uncertain resend,
        # and no model/page text is promoted into authority or public output.
        return _summary(task, 'UNKNOWN', consumed=True)
