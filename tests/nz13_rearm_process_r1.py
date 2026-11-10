"""Fresh-exec owned SQLite REARM readback; no target execution or product entry."""
import json
import os
import runpy
import socket
import sys
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch


def main():
    network_attempts = []
    def deny(*_args, **_kwargs):
        network_attempts.append('DENIED')
        raise PermissionError('REARM_PROCESS_NETWORK_DENIED')
    socket.socket.connect = deny
    socket.socket.connect_ex = deny
    socket.create_connection = deny
    checkout = Path(__file__).resolve().parents[1]
    assert (checkout / 'runtime/core_admission.py').is_file()
    sys.path[:0] = [str(checkout), str(checkout / 'runtime'), str(checkout / 'tests')]
    source_finder = runpy.run_path(str(Path(__file__).with_name('nz13_source_only_imports.py')))['install'](checkout)
    assert sys.dont_write_bytecode and sys.flags.isolated and sys.flags.dont_write_bytecode
    from lab.archaioa.warrant import EffectWarrant
    from nonzero_cloudops.adapters.portable import PortableExecutor, PortableStateStore
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
    from test_dual_governor import SCOPE, core

    value = json.loads(sys.stdin.buffer.readline(65537))
    assert type(value) is dict and set(value) == {'root', 'binding', 'warrant', 'mode'}
    assert value['mode'] in ('unresolved', 'reconcile', 'inspect')
    base = Path(value['root']).resolve(strict=True)
    private = Path(os.environ['TMPDIR']).resolve(strict=True)
    assert base != private and private in base.parents and base.name.startswith('tmp')
    now = datetime(2026, 11, 9, tzinfo=UTC)
    admission = core()
    runner = TransactionRunner(admission, LocalCoreRecordFactory(base / 'core.sqlite', admission))
    try:
        ledger = CoreWarrantLedger(admission, runner, SCOPE, clock=lambda: now)
        # Exactly the declared owned fixture bootstrap policy, not production.
        limits = Limits(1000, 100)
        governor = CoreDualGovernor(admission, runner, GovernorPolicy(SCOPE, 'adoption-test', limits, limits, limits), clock=lambda: 100)
        journal = CoreIntentJournal(ledger, governor)
        liability = CoreLiabilityLedger(admission, runner, SCOPE)
        binding = TargetBinding(SCOPE, **value['binding'])
        port = CoreTargetProjection(journal, liability, binding)
        path = base / 'managed/.aioa-core-managed-v1' / canonical_sha256(SCOPE) / port.registration_key / 'inventory.json'
        store = PortableStateStore(path)
        executor = PortableExecutor(store, clock=lambda: now)
        adapter = CorePortableTarget(port, store, executor=executor, read_principal=admission.local_operator(Capability.READ), clock=lambda: now)
        route = CoreToolRoute(journal, liability, workspace='workspace-1', policy_revision=5, variant='portable',
            probe=adapter.probe, executor=adapter, target_guard=adapter.target_guard, verifier=adapter.verify,
            clock=lambda: int(now.timestamp()), target_settlement=port)
        warrant = EffectWarrant.from_dict(value['warrant'])
        with patch.object(PortableExecutor, 'execute', side_effect=AssertionError('RELEASE_FORBIDDEN')), \
             patch.object(PortableExecutor, 'rearm', side_effect=AssertionError('REARM_FORBIDDEN')), \
             patch.object(PortableStateStore, '_write', side_effect=AssertionError('WRITE_FORBIDDEN')):
            read_principal = admission.local_operator(Capability.READ)
            if value['mode'] == 'unresolved':
                try:
                    route.reconcile(admission.local_operator(Capability.COMMIT), warrant, 1)
                except ValueError:
                    pass
                else:
                    raise AssertionError('MISSING_ACK_WAS_SETTLED')
                result = route.inspect(read_principal, warrant)
            elif value['mode'] == 'inspect':
                result = route.inspect(read_principal, warrant)
            else:
                result = route.reconcile(admission.local_operator(Capability.COMMIT), warrant, 1)
            row, head = runner.run(TransactionContext(read_principal, Capability.READ), lambda tx: port.load(tx))
        print(json.dumps({'event': 'result', 'pid': os.getpid(), 'outcome': result['outcome']['contract_type'],
            'authority': result['authority'], 'grants_replay': result['grants_replay'],
            'head_revision': row.revision, 'generation': head['generation'],
            'flight_phase': None if head['in_flight'] is None else head['in_flight']['phase'],
            'executor_counters': executor.counters(), 'network_attempts': len(network_attempts),
            'source_only_checkout': source_finder.root == checkout.absolute(),
            'checkout_loader': type(sys.modules['runtime.mission.portable_target'].__spec__.loader).__name__,
            'dont_write_bytecode_flag': bool(sys.flags.dont_write_bytecode)}), flush=True)
    finally:
        runner.close()
        admission.close()


if __name__ == '__main__':
    main()
