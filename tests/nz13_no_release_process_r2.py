"""Owned private SQLite process-recovery fixture; never a production entry point."""
import fcntl
import json
import os
import runpy
import socket
import sys
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

NETWORK_ATTEMPTS = []


def deny_network(*args, **kwargs):
    NETWORK_ATTEMPTS.append('DENIED')
    raise PermissionError('NO_RELEASE_FIXTURE_NETWORK_DENIED')


def main():
    socket.socket.connect = deny_network
    socket.socket.connect_ex = deny_network
    socket.create_connection = deny_network
    root = Path(__file__).resolve().parents[1]
    checkout = root if (root / 'runtime/core_admission.py').is_file() else root / 'checkout'
    sys.path[:0] = [str(checkout), str(checkout / 'runtime'), str(checkout / 'tests')]
    sys.dont_write_bytecode = True
    support = runpy.run_path(str(Path(__file__).with_name('nz13_source_only_imports.py')))
    source_finder = support['install'](checkout)
    assert sys.flags.dont_write_bytecode and sys.flags.isolated
    from nonzero_cloudops.adapters.portable import PortableExecutor, PortableStateStore
    from test_dual_governor import SCOPE, core

    from lab.archaioa.warrant import EffectWarrant
    from runtime.core_admission import Capability
    from runtime.memory_patch.contracts.serialization import canonical_sha256
    from runtime.memory_patch.persistence.ports import (
        LocalCoreRecordFactory,
        TransactionContext,
        TransactionRunner,
    )
    from runtime.mission.governor import CoreDualGovernor, GovernorPolicy, Limits
    from runtime.mission.intent import CoreIntentJournal
    from runtime.mission.liability import CoreLiabilityLedger
    from runtime.mission.portable_target import CorePortableTarget
    from runtime.mission.target_projection import CoreTargetProjection
    from runtime.mission.target_settlement import TargetBinding
    from runtime.mission.tools import CoreToolRoute
    from runtime.mission.warrant import CoreWarrantLedger

    value = json.loads(sys.stdin.buffer.readline(65537))
    assert type(value) is dict and set(value) == {'root', 'binding', 'warrant', 'mode'}
    assert value['mode'] in ('reconcile', 'inspect', 'blocked_then_reconcile')
    base = Path(value['root']).resolve(strict=True)
    private = Path(os.environ['TMPDIR']).resolve(strict=True)
    assert base != private and private in base.parents and base.name.startswith('tmp')
    now = datetime(2026, 11, 9, tzinfo=UTC)
    admission = core()  # Fresh synthetic local operator; no principal/seal/host credentials copied.
    factory = LocalCoreRecordFactory(base / 'core.sqlite', admission)
    runner = TransactionRunner(admission, factory)
    try:
        ledger = CoreWarrantLedger(admission, runner, SCOPE, clock=lambda: now)
        limits = Limits(100, 10)
        gov = CoreDualGovernor(admission, runner, GovernorPolicy(SCOPE, 'adoption-test', limits, limits, limits),
                               clock=lambda: 100)
        journal = CoreIntentJournal(ledger, gov)
        liability = CoreLiabilityLedger(admission, runner, SCOPE)
        binding = TargetBinding(SCOPE, **value['binding'])
        port = CoreTargetProjection(journal, liability, binding)
        path = base / 'managed/.aioa-core-managed-v1' / canonical_sha256(SCOPE) / port.registration_key / 'inventory.json'
        store = PortableStateStore(path)
        executor = PortableExecutor(store, clock=lambda: now)
        adapter = CorePortableTarget(port, store, executor=executor,
            read_principal=admission.local_operator(Capability.READ), clock=lambda: now)
        route = CoreToolRoute(journal, liability, workspace='workspace-1', policy_revision=4, variant='portable',
            probe=adapter.probe, executor=adapter, target_guard=adapter.target_guard, verifier=adapter.verify,
            clock=lambda: int(now.timestamp()), target_settlement=port)
        warrant = EffectWarrant.from_dict(value['warrant'])
        if value['mode'] == 'blocked_then_reconcile':
            descriptor = os.open(store._lock_path, os.O_RDWR | os.O_CLOEXEC | os.O_NOFOLLOW)
            blocked = False
            try:
                try:
                    fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    blocked = True
                else:
                    fcntl.flock(descriptor, fcntl.LOCK_UN)
            finally:
                os.close(descriptor)
            print(json.dumps({'event': 'fresh_descriptor_lock_probe', 'blocked': blocked}), flush=True)
            assert blocked, 'OLD_PROCESS_GUARD_DID_NOT_FENCE_RECOVERY'
        principal = admission.local_operator(Capability.COMMIT)
        with patch.object(PortableExecutor, 'execute', side_effect=AssertionError('TARGET_EXECUTOR_FORBIDDEN')), \
                patch.object(PortableStateStore, '_write', side_effect=AssertionError('TARGET_WRITER_FORBIDDEN')):
            result = route.inspect(admission.local_operator(Capability.READ), warrant) if value['mode'] == 'inspect' \
                else route.reconcile(principal, warrant, 1)
            row, head = runner.run(TransactionContext(admission.local_operator(Capability.READ), Capability.READ),
                                   lambda tx: port.load(tx))
        print(json.dumps({'event': 'result', 'pid': os.getpid(), 'outcome': result['outcome']['contract_type'],
            'authority': result['authority'], 'grants_replay': result['grants_replay'],
            'head_revision': row.revision, 'generation': head['generation'], 'in_flight': head['in_flight'],
            'state_root': head['state_root'], 'resources_root': head['resources_root'],
            'receipts_root': head['receipts_root'], 'executor_counters': executor.counters(),
            'network_attempts': len(NETWORK_ATTEMPTS), 'source_only_checkout': source_finder.root == checkout.absolute(),
            'checkout_loader': type(sys.modules['runtime.mission.portable_target'].__spec__.loader).__name__,
            'dont_write_bytecode_flag': bool(sys.flags.dont_write_bytecode)}), flush=True)
    finally:
        runner.close()
        admission.close()


if __name__ == '__main__':
    main()
