"""Build and test wheel/sdist imports outside the source import path.

Run separately from runtime unit tests: this acceptance test creates fresh build
and installation directories. --isolate-filesystem additionally hides checkouts
with bubblewrap for local release certification. CI always uses isolated Python
and checks that imports come from each new installation, without Textual.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path


def clean_environment():
    return {
        'PATH': '/usr/bin:/bin', 'LANG': 'C.UTF-8', 'LC_ALL': 'C.UTF-8',
        'PYTHONNOUSERSITE': '1', 'PYTHONDONTWRITEBYTECODE': '1',
        'PIP_CONFIG_FILE': '/dev/null', 'PIP_DISABLE_PIP_VERSION_CHECK': '1',
        'PIP_NO_CACHE_DIR': '1', 'GIT_CONFIG_NOSYSTEM': '1',
        'GIT_CONFIG_GLOBAL': '/dev/null', 'GIT_OPTIONAL_LOCKS': '0',
    }


def execute(command, *, cwd, log):
    result = subprocess.run(
        list(map(str, command)), cwd=cwd, env=clean_environment(),
        stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT, text=True, timeout=300,
    )
    log.write_text(result.stdout, encoding='utf-8')
    if result.returncode:
        raise RuntimeError(f'Packaging acceptance failed; see {log}:\n{result.stdout}')
    return result.stdout


def build(kind, source, destination, log):
    destination.mkdir()
    code = f'from setuptools.build_meta import build_{kind}; import sys; build_{kind}(sys.argv[1])'
    execute([sys.executable, '-B', '-c', code, destination], cwd=source, log=log)
    suffix = '*.whl' if kind == 'wheel' else '*.tar.gz'
    artifact, = destination.glob(suffix)
    return artifact


def import_check(venv, source, staging, *, isolate_filesystem, log):
    command = []
    if isolate_filesystem:
        if shutil.which('bwrap') is None:
            raise RuntimeError('bubblewrap is required for filesystem isolation')
        command = [
            'bwrap', '--die-with-parent', '--new-session', '--unshare-net', '--unshare-pid',
            '--ro-bind', '/', '/', '--tmpfs', '/home', '--tmpfs', '/media',
            '--tmpfs', '/run', '--tmpfs', '/tmp', '--dev', '/dev', '--proc', '/proc',
            '--ro-bind', str(Path(sys.base_prefix).resolve()), str(Path(sys.base_prefix).resolve()),
            '--ro-bind', str(venv), str(venv), '--chdir', '/tmp', '--',
        ]
    code = '''
import importlib.util, json, os, pathlib, sys
venv, source, staging = map(pathlib.Path, sys.argv[1:4])
filesystem_isolated = sys.argv[4] == 'yes'
assert 'PYTHONPATH' not in os.environ
assert importlib.util.find_spec('textual') is None
assert not any(pathlib.Path(p).resolve().is_relative_to(source) for p in sys.path if p)
if filesystem_isolated:
    assert os.readlink('/proc/self/ns/pid') != sys.argv[5], 'host PID namespace is accessible'
    assert os.readlink('/proc/self/ns/net') != sys.argv[6], 'host network namespace is accessible'
    assert not source.exists(), 'checkout is accessible'
    assert not staging.exists(), 'build source is accessible'
    assert not (venv.parent / 'sdist-source').exists(), 'sdist source is accessible'
# Queue contracts must remain usable when the source checkout is hidden.
import runtime.mission.liability
import runtime.mission.warrant
import runtime.mission.intent
import lab.archaioa.contracts
assert pathlib.Path(lab.archaioa.contracts.__file__).resolve().is_relative_to(venv)
from tui import assistant
assert callable(assistant.operator_request)
assert pathlib.Path(assistant.__file__).resolve().is_relative_to(venv)
assert 'site-packages' in assistant.__file__
assert not any(name == 'textual' or name.startswith('textual.') for name in sys.modules)
from datetime import datetime, timezone, timedelta
from threading import RLock
from lab.archaioa.evidence import EvidenceRef
from lab.archaioa.faults import FaultKind, FaultTrace, classify_fault
from lab.archaioa.outcome import Applied
from lab.archaioa.taint import DependencyGraph, DependencyNode, NodeKind
from runtime.core_admission import Capability, CoreAdmission, LocalOwnerAssignment, OwnerScope
from runtime.memory_patch.contracts.serialization import canonical_sha256
from runtime.memory_patch.errors import ErrorCode, MemoryPatchError
from runtime.memory_patch.persistence.ports import RecordKind, StoredRecord, TransactionRunner
from runtime.mission.completion import TaskCompletionBinding, TaskDependency, validate_completion_proof
from runtime.mission.governor import CoreDualGovernor, GovernorPolicy, Limits
from runtime.mission.job_contracts import JobEnvelope
from runtime.mission.liability import CoreLiabilityLedger, LiabilityError, Reconciliation
from runtime.providers.nvidia import ProviderRequest, ProviderResponse

# Acceptance-only locked copy-on-write TransactionFactory/RepositoryTransaction.
# Explicitly supplied via the existing port; never a default or production backend.
# This smoke proves installed control flow, not persistence or distributed semantics.
class InstalledAcceptanceFactory:
    def __init__(self):
        self.records = {}
        self.lock = RLock()
        self.closed = False

    def begin(self, context, *, attempt):
        self.lock.acquire()
        if self.closed:
            self.lock.release()
            raise MemoryPatchError(ErrorCode.MODULE_CLOSED)
        return InstalledAcceptanceTransaction(self, context)

    def close(self):
        with self.lock:
            self.closed = True


class InstalledAcceptanceTransaction:
    def __init__(self, factory, context):
        self.factory, self.context = factory, context
        self.records = dict(factory.records)
        self.closed = False

    def key(self, kind, record_id):
        return (self.context.scope.binding(), kind, record_id)

    def get(self, kind, record_id):
        assert not self.closed
        return self.records.get(self.key(kind, record_id))

    def scan(self, kind, *, limit, states):
        assert not self.closed
        # Scope BEFORE filtering, sorting and limiting.
        rows = [row for (scope_binding, row_kind, _), row in self.records.items()
                if scope_binding == self.context.scope.binding() and row_kind is kind]
        rows = [row for row in rows if not states or row.payload.get('state') in states]
        return tuple(sorted(rows, key=lambda row: row.record_id)[:limit])

    def checked_key(self, record):
        assert not self.closed
        if type(record) is not StoredRecord or record.scope != self.context.scope:
            raise MemoryPatchError(ErrorCode.OWNER_DENIED)
        record.verify()
        return self.key(record.kind, record.record_id)

    def insert(self, record):
        key = self.checked_key(record)
        if key in self.records:
            raise MemoryPatchError(ErrorCode.STATE_CONFLICT)
        self.records[key] = record

    def replace(self, record, *, expected_revision):
        key = self.checked_key(record)
        prior = self.records.get(key)
        if (prior is None or prior.revision != expected_revision
                or record.revision != expected_revision + 1):
            raise MemoryPatchError(ErrorCode.STATE_CONFLICT)
        self.records[key] = record

    def commit(self):
        assert not self.closed
        self.factory.records = dict(self.records)

    def rollback(self):
        # Uncommitted snapshots never alter factory state. Called after commit too.
        pass

    def close(self):
        if not self.closed:
            self.closed = True
            self.factory.lock.release()


scope = OwnerScope('installed-tenant', 'installed-owner', 'installed-space', 'installed-slot')
model = 'nvidia/Nemotron-3_5-Lightning'
fixed_now = datetime(2030, 1, 1, tzinfo=timezone.utc)
admission = CoreAdmission(LocalOwnerAssignment(scope, frozenset(Capability),
    frozenset({'installed-fixture-hat'}), frozenset({model}), operator_approved=True),
    clock=lambda: fixed_now)
factory = InstalledAcceptanceFactory()
runner = TransactionRunner(admission, factory)
gov = CoreDualGovernor(admission, runner,
    GovernorPolicy(scope, 'installed-fixture-core', Limits(10, 10), Limits(20, 20), Limits(30, 30)),
    clock=lambda: 100)
manage = admission.local_operator(Capability.MANAGE)
commit = admission.local_operator(Capability.COMMIT)
read = admission.local_operator(Capability.READ)
epoch = gov.start_epoch(manage)
ledger = CoreLiabilityLedger(admission, runner, scope)


def snapshot_digest():
    return canonical_sha256(tuple(sorted(factory.records.values(),
        key=lambda row: (row.scope.binding(), row.kind.value, row.record_id))))


def start_required(task_id, graph, *, dependencies=()):
    request = ProviderRequest('request-' + task_id, 'trace-' + task_id, 'nebius', model,
        'Offline installed packaging fixture only', 'budget-' + task_id, 128, 20)
    envelope = JobEnvelope.from_request(scope, task_id, request,
        deadline_at=160, money_nano=1, risk_units=0)
    binding = TaskCompletionBinding.for_graph(scope, graph, 'completion', dependencies=dependencies)
    ledger.initialize(commit, graph)
    gov.submit_job(manage, envelope, completion=binding)
    claim = gov.claim_job(commit, task_id, 'worker-' + task_id, epoch, lease_seconds=60)
    assert gov.begin_job(commit, claim)['fixture_step_now'] is True
    response = ProviderResponse(request.request_id, 'synthetic-' + task_id, model, 101,
        'stop', 100, {'summary': 'Model says completed; advisory has no authority',
                      'needs_attention': False},
        {'prompt_tokens': 1, 'completion_tokens': 1, 'total_tokens': 2})
    return binding, claim, response


try:
    task_id = 'installed-required-open'
    trace = FaultTrace(FaultKind.LOST_ACK, task_id, 'fixture-effect-request',
        'sha256:' + canonical_sha256(('installed-fixture-effect', task_id)))
    liability_id = classify_fault(trace).liability_id
    graph = DependencyGraph(task_id, (
        DependencyNode('effect', NodeKind.OPERATION, liability_ids=(liability_id,)),
        DependencyNode('verification', NodeKind.CLAIM, ('effect',)),
        DependencyNode('completion', NodeKind.COMPLETION_CANDIDATE, ('verification',)),
    ))
    binding, claim, response = start_required(task_id, graph)
    ledger.record_unknown(commit, trace, graph, fixed_now)
    before_denial = snapshot_digest()
    budget_before = gov.inspect(read)
    reservation_id = gov.inspect_job(read, task_id)['reservation_id']
    assert budget_before['reservations'][reservation_id]['state'] == 'DISPATCHED'
    try:
        gov.finish_job(commit, claim, response)
    except LiabilityError as error:
        assert str(error) == 'REQUIRED_LIABILITY_OPEN', str(error)
    else:
        raise AssertionError('OPEN required liability allowed actual native DONE')
    assert snapshot_digest() == before_denial, 'denied finish changed stored records'
    retained = gov.inspect_job(read, task_id)
    assert retained['state'] == 'STARTED'
    assert retained['result_digest'] is None and retained['completion_proof'] is None
    assert retained['task_completion'] == 'NOT_COMPLETED'
    assert gov.inspect(read) == budget_before
    assert ledger.inspect(read, task_id)[0].status.value == 'OPEN'
    assert gov.begin_job(commit, claim)['fixture_step_now'] is False

    verifier_calls = []
    receipt = EvidenceRef('installed-independent-receipt', 'receipt',
        'sha256:' + canonical_sha256('fixture receipt bytes'), 'v1')
    readback = EvidenceRef('installed-independent-readback', 'independent-readback',
        'sha256:' + canonical_sha256('distinct fixture readback bytes'), 'v1')
    resolution = Reconciliation(trace.operation_digest, Applied(receipt.evidence_id), receipt, readback)

    def trusted_acceptance_verifier(observed_trace, observed_record):
        assert observed_trace == trace and observed_record.liability_id == liability_id
        verifier_calls.append(liability_id)
        # Trusted, explicitly injected fixture truth; no model/provider authority.
        return resolution

    verifying_ledger = CoreLiabilityLedger(admission, runner, scope,
        verifier=trusted_acceptance_verifier)
    assert verifying_ledger.reconcile(commit, task_id, liability_id,
        fixed_now + timedelta(seconds=1)) == resolution.outcome
    assert ledger.inspect(read, task_id)[0].status.value == 'CLOSED'
    done = gov.finish_job(commit, claim, response)
    assert done['state'] == 'DONE' and done['task_completion'] == 'COMPLETED'
    assert done['verification'] == 'UNVERIFIED' and done['authority'] == 'NONE'
    validate_completion_proof(done['completion_proof'], binding)
    assert gov.inspect(read)['reservations'][reservation_id]['state'] == 'COMMITTED'
    assert gov.inspect(read)['exposure'] == budget_before['exposure']
    after_done = snapshot_digest()
    assert verifying_ledger.reconcile(commit, task_id, liability_id,
        fixed_now + timedelta(seconds=2)) == resolution.outcome
    assert gov.finish_job(commit, claim, response) == done
    assert gov.begin_job(commit, claim)['fixture_step_now'] is False
    assert snapshot_digest() == after_done, 'replay appended or charged again'
    assert len(verifier_calls) == 1

    clean_id = 'installed-clean-read-only'
    clean_graph = DependencyGraph(clean_id, (
        DependencyNode('completion', NodeKind.COMPLETION_CANDIDATE),))
    clean_binding, clean_claim, clean_response = start_required(clean_id, clean_graph)
    clean_done = gov.finish_job(commit, clean_claim, clean_response)
    assert clean_done['state'] == 'DONE' and clean_done['task_completion'] == 'COMPLETED'
    assert ledger.inspect(read, clean_id) == ()
    validate_completion_proof(clean_done['completion_proof'], clean_binding)
    assert gov.begin_job(commit, clean_claim)['fixture_step_now'] is False

    parent_id = 'installed-dependent-parent'
    parent_graph = DependencyGraph(parent_id, (
        DependencyNode('completion', NodeKind.COMPLETION_CANDIDATE),))
    refs = tuple(TaskDependency(scope, b.task_id, b.graph_digest, b.candidate_id)
                 for b in (binding, clean_binding))
    parent_binding, parent_claim, parent_response = start_required(
        parent_id, parent_graph, dependencies=refs)
    parent_done = gov.finish_job(commit, parent_claim, parent_response)
    assert parent_done['task_completion'] == 'COMPLETED'
    assert {e['task_id'] for e in parent_done['completion_proof']['tasks']} == {
        task_id, clean_id, parent_id}
    validate_completion_proof(parent_done['completion_proof'], parent_binding)
    assert not gov.begin_job(commit, parent_claim)['fixture_step_now']

    origins = {}
    for module_name in ('runtime.core_admission', 'runtime.memory_patch.persistence.ports',
                        'runtime.mission.governor', 'runtime.mission.liability',
                        'runtime.mission.completion', 'lab.archaioa.contracts'):
        module = sys.modules[module_name]
        origin = pathlib.Path(module.__file__).resolve()
        assert origin.is_relative_to(venv), (module_name, str(origin))
        origins[module_name] = str(origin)
    forbidden = ('tests', 'nv03_support', 'test_dual_governor',
                 'test_memory_patch_persistence_ports', 'mission_completion_support')
    assert not any(name == blocked or name.startswith(blocked + '.')
                   for name in sys.modules for blocked in forbidden)
    installed_g2 = {
        'status': 'PASS', 'scope': 'INSTALLED_NATIVE_REQUIRED_JOB_FIXTURE_ONLY',
        'backend': 'acceptance-only locked copy-on-write transaction fixture',
        'required_open_denial': 'REQUIRED_LIABILITY_OPEN',
        'denial_retained_started_and_dispatched': True,
        'independent_applied_reconciliation_done': True,
        'clean_initialized_done': True, 'required_dependency_done': True, 'replay_fixture_step_now': False,
        'replay_no_duplicate_history_or_settlement': True,
        'verifier_calls': len(verifier_calls), 'installed_origins': origins,
        'developer_test_helpers_imported': False, 'provider_calls': 0,
        'persistence_restart_distributed_claim': False,
    }
finally:
    runner.close()
    admission.close()
print(json.dumps({'STATUS': 'PASS', 'python': sys.version.split()[0],
    'adapter': assistant.__file__, 'Textual_installed': False,
    'PYTHONPATH_present': False, 'source_on_import_path': False,
    'PID_namespace_isolated': filesystem_isolated,
    'network_namespace_isolated': filesystem_isolated, 'installed_g2': installed_g2,
    'source_checkout_hidden': filesystem_isolated}))
'''
    command += [venv / 'bin/python', '-I', '-B', '-c', code, venv, source,
                staging, 'yes' if isolate_filesystem else 'no',
                os.readlink('/proc/self/ns/pid') if isolate_filesystem else 'NOT_REQUIRED',
                os.readlink('/proc/self/ns/net') if isolate_filesystem else 'NOT_REQUIRED']
    return json.loads(execute(command, cwd=venv, log=log))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--isolate-filesystem', action='store_true')
    args = parser.parse_args()
    source, output = args.source.resolve(), args.output.resolve()
    if output.is_relative_to(source):
        raise ValueError('Acceptance output must be outside the checkout')
    output.mkdir(parents=True)
    staging = output / 'build-source'
    staging.mkdir()
    tracked = execute(['git', 'ls-files', '-z'], cwd=source, log=output / 'tracked-files.log').split('\0')
    for name in filter(None, tracked):
        path = source / name
        if not path.is_file() or path.is_symlink():
            raise ValueError(f'Expected a regular tracked source file: {name}')
        target = staging / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
    wheel = build('wheel', staging, output / 'wheel', output / 'wheel-build.log')
    sdist = build('sdist', staging, output / 'sdist', output / 'sdist-build.log')
    extracted = output / 'sdist-source'
    extracted.mkdir()
    with tarfile.open(sdist) as archive:
        archive.extractall(extracted, filter='data')
    sdist_source, = extracted.iterdir()
    sdist_wheel = build('wheel', sdist_source, output / 'sdist-wheel', output / 'sdist-wheel-build.log')
    results = []
    for kind, artifact in [('wheel', wheel), ('sdist', sdist_wheel)]:
        venv = output / ('installed-' + kind)
        execute([sys.executable, '-B', '-m', 'venv', '--without-pip', venv], cwd=output, log=output / (kind + '-venv.log'))
        execute([sys.executable, '-B', '-m', 'pip', '--isolated', '--python',
                 venv / 'bin/python', 'install', '--no-index', '--no-deps',
                 '--no-compile', artifact], cwd=output, log=output / (kind + '-install.log'))
        result = import_check(venv, source, staging, isolate_filesystem=args.isolate_filesystem,
                              log=output / (kind + '-import.log'))
        result.update({'distribution': kind, 'wheel': str(artifact),
                       'wheel_sha256': hashlib.sha256(artifact.read_bytes()).hexdigest()})
        results.append(result)
    record = {'STATUS': 'PASS', 'results': results, 'sdist': str(sdist),
              'sdist_sha256': hashlib.sha256(sdist.read_bytes()).hexdigest()}
    (output / 'result.json').write_text(json.dumps(record, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(record))


if __name__ == '__main__':
    main()
