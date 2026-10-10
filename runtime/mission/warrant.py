"""Offline-ready linear warrant registry on Core's existing transaction port.

No signer, executor or default composition. Only an admitted local human can
register the exact decision. Consuming returns a *ledger receipt*, never proof
of an effect. Commit ACK loss must be inspected; consume never grants replay.
DDR uses the existing canonical EvidenceRef set: the trusted host selects
relevant dependencies before approval, excluding unrelated evidence. Every
selected metadata change invalidates the decision; ordering does not.
"""
from datetime import datetime, timezone
import json

from lab.archaioa.warrant import EffectWarrant, RevisionPolicy
from runtime.core_admission import Capability, CoreAdmission, OwnerScope
from runtime.memory_patch.contracts.serialization import canonical_json_bytes, canonical_sha256
from runtime.memory_patch.errors import ErrorCode, MemoryPatchError
from runtime.memory_patch.persistence.ports import RecordKind, StoredRecord, TransactionContext, TransactionRunner

KIND = 'aioa-linear-warrant-v1'


class WarrantError(MemoryPatchError, ValueError):
    def __init__(self, reason):
        super().__init__(ErrorCode.INTEGRITY_FAILED)
        self.args = (reason,)


def require(condition, reason='WARRANT_DENIED'):
    if not condition:
        raise WarrantError(reason)


def approval_digest(warrant):
    """Canonical exact human decision commitment, without self-reference."""
    require(type(warrant) is EffectWarrant)
    value = warrant.to_dict()
    del value['approval_digest']
    return 'sha256:' + canonical_sha256(value)


class CoreWarrantLedger:
    def __init__(self, core, runner, scope, *, clock=None):
        require(type(core) is CoreAdmission and type(runner) is TransactionRunner
                and type(scope) is OwnerScope, 'INVALID_WARRANT_BINDINGS')
        self.core, self.runner, self.scope = core, runner, scope
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    def _key(self, warrant):
        require(type(warrant) is EffectWarrant)
        # Owner-wide nonce barrier, independent of task/operation/warrant ID.
        return canonical_sha256((KIND, self.scope, warrant.nonce))

    def _run(self, principal, purpose, callback):
        self.core.require(principal, purpose, scope=self.scope)
        return self.runner.run(TransactionContext(principal, purpose), callback)

    def _check(self, warrant):
        require(type(warrant) is EffectWarrant)
        require(warrant.owner_scope == canonical_sha256(self.scope), 'WARRANT_OWNER_MISMATCH')
        require(warrant.revision_policy is RevisionPolicy.REQUIRE, 'WARRANT_REVISION_REQUIRED')
        now = self.clock()
        require(isinstance(now, datetime) and now.tzinfo is not None
                and warrant.issued_at <= now < warrant.expires_at, 'WARRANT_EXPIRED')

    def _load(self, tx, warrant):
        stored = tx.get(RecordKind.OPERATION, self._key(warrant))
        require(stored is not None, 'HUMAN_APPROVAL_REQUIRED')
        try:
            state = json.loads(canonical_json_bytes(stored.payload))
            require(set(state) == {'schema', 'root', 'active', 'consumption'} and state['schema'] == KIND)
            root = EffectWarrant.from_dict(state['root'])
            active = EffectWarrant.from_dict(state['active'])
            require(root.approval_digest == approval_digest(root))
            require(root.owner_scope == canonical_sha256(self.scope))
            require(self._key(root) == stored.record_id)
            self._attenuation(root, active)
            require(state['consumption'] is None or state['consumption'] == self._receipt(active))
            return stored, state, active
        except (KeyError, TypeError, ValueError):
            raise WarrantError('WARRANT_INTEGRITY') from None

    @staticmethod
    def _attenuation(parent, child):
        # Delegation can narrow scope/window only, never mint another use.
        mutable = {'authority_scope', 'expires_at', 'warrant_id'}
        p, c = parent.to_dict(), child.to_dict()
        require(all(p[key] == c[key] for key in p if key not in mutable), 'WARRANT_ESCALATION')
        require(parent.authority_scope.contains(child.authority_scope)
                and child.expires_at <= parent.expires_at, 'WARRANT_ESCALATION')

    def _save(self, tx, warrant, state, stored=None):
        record = StoredRecord(RecordKind.OPERATION, self._key(warrant), self.scope,
                              stored.revision + 1 if stored else 1, state)
        if stored is None:
            tx.insert(record)
        else:
            tx.replace(record, expected_revision=stored.revision)

    @staticmethod
    def _receipt(warrant):
        return {'kind': 'WARRANT_CONSUMPTION_ONLY', 'warrant_digest': warrant.digest(),
                'grants_replay': False, 'effect_verified': False}

    def approve(self, principal, warrant):
        def mutation(tx):
            self._check(warrant)
            require(warrant.approval_digest == approval_digest(warrant), 'APPROVAL_DIGEST_MISMATCH')
            require(tx.get(RecordKind.OPERATION, self._key(warrant)) is None, 'NONCE_ALREADY_REGISTERED')
            self._save(tx, warrant, {'schema': KIND, 'root': warrant.to_dict(),
                                    'active': warrant.to_dict(), 'consumption': None})
        return self._run(principal, Capability.OWNER_APPROVAL, mutation)

    def delegate(self, principal, parent, child):
        def mutation(tx):
            self._check(parent); self._check(child)
            stored, state, active = self._load(tx, parent)
            require(active == parent and state['consumption'] is None, 'WARRANT_INACTIVE')
            self._attenuation(parent, child)
            state['active'] = child.to_dict()
            self._save(tx, parent, state, stored)
        return self._run(principal, Capability.COMMIT, mutation)

    def consume(self, principal, current):
        """Host supplies independently refreshed exact bindings, including DDR,
        lease epoch and reservation identities. No effect runs in a transaction.
        """
        def mutation(tx):
            self._check(current)
            stored, state, active = self._load(tx, current)
            require(current == active, 'STALE_WARRANT_BINDING')
            require(state['consumption'] is None, 'WARRANT_ALREADY_CONSUMED')
            state['consumption'] = self._receipt(active)
            self._save(tx, current, state, stored)
            return state['consumption']
        return self._run(principal, Capability.COMMIT, mutation)

    def inspect(self, principal, warrant):
        """Read-only ACK reconciliation, including after expiry; no raw approval."""
        def read(tx):
            _, state, _ = self._load(tx, warrant)
            return state['consumption']
        return self._run(principal, Capability.READ, read)
