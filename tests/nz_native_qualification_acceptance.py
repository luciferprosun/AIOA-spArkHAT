"""Operator-only normal Native review/apply and cold witness recovery on pinned Noble.

Uses disposable keys and the existing NZ13 owned fixture's synthetic operator
admission. This mode measures the Native application path under one UID. It
cannot qualify separate identities or replace the external confinement probes.
"""
import argparse
import hashlib
import json
import multiprocessing
import os
import socket
import stat
import sys
import tempfile
import threading
import time
import unittest
from contextlib import ExitStack
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric import ec

import nz13_native_coding_support as owned
import nz13_native_foundation_support as foundation_fixture
from lab.archaioa.warrant import EffectWarrant
from runtime.core_admission import Capability
from runtime.memory_patch.persistence.ports import CommitOutcomeUnknown, RecordKind
from runtime.mobile_gateway.wire import Identity
from runtime.red_hat.authenticated_boundary import AuthenticatedFixtureRecoveryPort, serve_verifier_fixture_once
from runtime.red_hat.broker_protocol import Peer
from runtime.red_hat.core_adapter import CoreIntentAdapter
from runtime.red_hat.enrollment import ExecutorEnrollment
from runtime.red_hat.execution_binding import capture_binding
from runtime.red_hat.native_qualification import NativeQualificationPort, serve_prepared_native_fixture
from runtime.red_hat.sequenced_boundary import CoreReleaseClient
from runtime.red_hat.sequencer import SequenceClient, SequencedCoreGate, bind_fixture_runner, serve_sequencer
from runtime.red_hat.witness import RegisteredExecutor

DEVICE = 'owned-native-qualification'
SEQUENCE_EPOCH = 1
SPAWN = multiprocessing.get_context('spawn')


def peer(pid):
    return Peer(pid, os.getuid(), os.getgid())


def anchor(stack, path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
    stack.callback(os.close, fd)
    return fd


def listener(stack, endpoint):
    sock = stack.enter_context(socket.socket(socket.AF_UNIX))
    sock.bind(str(endpoint))
    sock.listen(5)
    return sock


def message(pipe, seconds):
    if not pipe.poll(seconds):
        raise TimeoutError('NATIVE_QUALIFICATION_CHILD_TIMEOUT')
    return pipe.recv()


def child_process(stack, target, *args):
    parent, child = SPAWN.Pipe()
    process = SPAWN.Process(target=target, args=(child, *args))
    process.start()
    child.close()
    def cleanup():
        if process.is_alive():
            process.kill()
        process.join(5)
        parent.close()
    stack.callback(cleanup)
    return process, parent


def broker(pipe, endpoint, root, core_pid):
    with ExitStack() as stack:
        srv = listener(stack, endpoint)
        signer = Identity(ec.generate_private_key(ec.SECP256R1()))
        pipe.send(signer.spki)
        enrollment, ref, epoch, seq, seq_pid, release, spki = message(pipe, 300)
        links = []
        parent = (root/'repo'/ref).parent.stat()
        def count(event, args):
            if event == 'os.link' and args[1] == ref.rsplit('/',1)[1] and args[3] >= 0:
                meta = os.fstat(args[3])
                if (meta.st_dev, meta.st_ino) == (parent.st_dev, parent.st_ino):
                    links.append((meta.st_dev, meta.st_ino))
        sys.addaudithook(count)
        success = serve_prepared_native_fixture(
            srv, root_fd=anchor(stack, root), exact_ref=ref, device_id=DEVICE,
            sequence=SequenceClient(str(seq), peer(seq_pid), SEQUENCE_EPOCH),
            release=CoreReleaseClient(str(release), peer(core_pid), spki),
            core_peer=peer(core_pid), core_spki=spki, identity=signer, enrollment=enrollment,
            core_epoch=epoch, broker_epoch=SEQUENCE_EPOCH, enabled=True)
        pipe.send({'completed':success, 'cas_attempts':len(links)})


def sequencer(pipe, endpoint, directory, core_pid, broker_pid):
    with ExitStack() as stack:
        srv = listener(stack, endpoint)
        pipe.send(True)
        serve_sequencer(srv, directory=anchor(stack, directory), core_peer=peer(core_pid),
                        broker_peer=peer(broker_pid), epoch=SEQUENCE_EPOCH, enabled=True)


def verifier(pipe, endpoint, root, core_pid, enrollment, binding, core_spki):
    with ExitStack() as stack:
        srv = listener(stack, endpoint)
        signer = Identity(ec.generate_private_key(ec.SECP256R1()))
        pipe.send(signer.spki)
        fd = anchor(stack, root)
        for ordinal in range(2):
            stamp = int(time.time())
            pipe.send(('listening', ordinal))
            serve_verifier_fixture_once(srv, root_fd=fd, binding=binding, enrollment=enrollment,
                                        identity=signer, core_peer=peer(core_pid), core_spki=core_spki,
                                        now=stamp, enabled=True)


def revision(journal, principal, warrant):
    return journal._run(principal, Capability.READ, lambda tx:
                        tx.get(RecordKind.OPERATION, journal._key(warrant)).revision)


def recover(pipe, packet, endpoints):
    from unittest.mock import patch
    from runtime.meta_hackathon import runtime_adapter
    from runtime.meta_hackathon.native_authority import NativeHostCompositionConfig
    from runtime.mission.worker import CandidateFile, CandidatePatch

    with ExitStack() as stack:
        evidence = Path(packet['root'])
        case = unittest.TestCase()
        host = owned.NativeOwnedFixture.__new__(owned.NativeOwnedFixture)
        host.retained = {}
        host.body = packet['composition']
        candidates = tuple(CandidatePatch(tuple(CandidateFile(**file) for file in files))
                           for files in packet['candidates'])
        # Reopen only the producer's closed test DB; no administration bootstrap.
        with patch.object(runtime_adapter, '_desktop_operator_uid', return_value=(os.getuid(),
                {'uid':os.getuid(), 'method':'FIXTURE_OS_ADMISSION'})):
            host.host = runtime_adapter.NativeMobileComposition(
                Path(packet['native_root']), origin=packet['origin'], existing_profile=True,
                host_composition=NativeHostCompositionConfig.from_dict(host.body),
                offline_candidates=candidates)
        stack.callback(host.close)
        foundation_fixture.fixture_tls(host.host)
        case.assertNotEqual(host.host.instance_id, packet['instance'])
        case.assertEqual(host.host.identity.spki, packet['spki'])
        case.assertEqual(tuple(host.host.source), tuple(packet['source']))
        warrant = EffectWarrant.from_dict(packet['warrant'])
        journal = host.host.foundation.intent_journal
        adapter = CoreIntentAdapter(journal)
        enrollment = packet['enrollment']
        with host.host._native_coding.authority(Capability.READ) as principal:
            before = revision(journal, principal, warrant)
            case.assertEqual('Unknown', journal.inspect(principal, warrant)['outcome']['contract_type'])
        with host.host._native_coding.authority(Capability.COMMIT) as principal:
            binding = capture_binding(adapter, principal, warrant, enrollment, trusted_device_id=DEVICE,
                                      now=int(time.time()), broker_epoch=SEQUENCE_EPOCH)
        fd = anchor(stack, evidence)
        endpoint = endpoints/'verify.sock'
        process, control = child_process(stack, verifier, endpoint, evidence, os.getpid(), enrollment,
                                         binding, host.host.identity.spki)
        spki = message(control, 20)
        def resolve(task_id):
            case.assertEqual(warrant.task_id, task_id)
            return dict(warrant=warrant, request=binding.request, enrollment=enrollment, root_fd=fd,
                        trusted_device_id=DEVICE, now=int(time.time()), core_epoch=warrant.lease_epoch,
                        broker_epoch=SEQUENCE_EPOCH)
        host.host.coding_tasks.native_witness_recovery_port = AuthenticatedFixtureRecoveryPort(
            adapter, host.host.coding_tasks, resolve, endpoint=str(endpoint), verifier_peer=peer(process.pid),
            verifier_spki=spki, core_spki=host.host.identity.spki, enabled=True)
        # Cold process has no dispatch port or broker listener. A second request
        # rechecks the witness independently against the original operation.
        case.assertIsNone(host.host._native_coding.qualification_port)
        from runtime.mission.git_publish import CoreRemoteGitRoute
        paths = {CoreRemoteGitRoute._dispatch_local_patch.__code__:'route',
                 NativeQualificationPort.dispatch.__code__:'broker_handoff'}
        dispatches = {'route':0, 'broker_handoff':0}
        def trace(frame, event, arg):
            if event == 'call' and frame.f_code in paths:
                dispatches[paths[frame.f_code]] += 1
        previous, previous_threads = sys.getprofile(), threading.getprofile()
        try:
            sys.setprofile(trace)
            threading.setprofile(trace)
            replies = []
            for ordinal in range(2):
                case.assertEqual(('listening', ordinal), message(control, 20))
                replies.append(host.request('reconcile', {'task_id':warrant.task_id}))
        finally:
            threading.setprofile(previous_threads)
            sys.setprofile(previous)
        case.assertEqual({'route':0, 'broker_handoff':0}, dispatches)
        case.assertEqual(replies[0], replies[1])
        case.assertEqual(process.pid, replies[0]['verification_process_pid'])
        case.assertEqual('VERIFIED', replies[0]['task']['state'])
        case.assertEqual('Applied', replies[0]['intent']['outcome']['contract_type'])
        with host.host._native_coding.authority(Capability.READ) as principal:
            delta = revision(journal, principal, warrant) - before
        case.assertEqual(1, delta)
        process.join(5)
        case.assertEqual(0, process.exitcode)
        pipe.send({'settlements':delta, 'recovery_redispatches':dispatches['route'],
                   'recovery_broker_handoffs':dispatches['broker_handoff'],
                   'verifier_pid':process.pid, 'cold_core_pid':os.getpid(),
                   'intent_digest':warrant.operation_hash})


def produce(parent, context, endpoint_dir):
    case = unittest.TestCase()
    owned.ACTUAL_CONTEXT = context
    with ExitStack() as stack:
        stack.callback(setattr, owned, 'ACTUAL_CONTEXT', None)
        stack.callback(case.doCleanups)
        fx = owned.NativeOwnedFixture(case, broker_fixture=True)
        fx.complete_single_candidate(case)
        status = fx.request('get_receipts', {'task_id':fx.task.task_id})
        capsule = status['receipts'][-1]['receipt']['capsule_digest']
        ref = 'refs/heads/aioa/nz11-' + capsule[:32]
        for name in ('state', 'evidence', 'sequencer'):
            (fx.root/name).mkdir(mode=0o700)
        repo = fx.target_repo.path
        (repo/'refs/heads/aioa').mkdir(mode=0o700, exist_ok=True)
        marker = repo/'.redhat-disposable'
        with marker.open('xb') as out:
            out.write(b'AIOA_RED_HAT_FIXTURE_V1\n')
        marker.chmod(0o400)
        case.assertFalse((repo/ref).exists())
        b_ep, s_ep, r_ep = (endpoint_dir/name for name in ('b','s','r'))
        proc, pipe = child_process(stack, broker, b_ep, fx.root, os.getpid())
        signer = message(pipe, 20)
        now = int(time.time())
        enrollment = ExecutorEnrollment(RegisteredExecutor('native-disposable-broker',os.getuid(),signer),
                                        1, now-1, now+900)
        sequence, control = child_process(stack, sequencer, s_ep, fx.root/'sequencer', os.getpid(), proc.pid)
        case.assertTrue(message(control, 20))
        gate = SequencedCoreGate(SequenceClient(str(s_ep), peer(sequence.pid), SEQUENCE_EPOCH), enabled=True)
        bind_fixture_runner(fx.host.runner, gate, enabled=True)
        # If an assertion fails, retire the owned Core while its sequencer still exists.
        stack.callback(fx.close)
        fx.host._native_coding.qualification_port = NativeQualificationPort.prepare(
            gate=gate, enrollment=enrollment, device_id=DEVICE, broker_peer=peer(proc.pid), endpoint=str(b_ep),
            release_listener=listener(stack, r_ep), anchor=anchor(stack,fx.root), lifetime=300, enabled=True)
        review = fx.request('review_effect', {'task_id':fx.task.task_id})
        preview = review['effect_preview']
        route, warrant, _ = fx.host.coding_tasks._effect(fx.task.task_id, capsule)
        case.assertEqual(ref,route.plan.ref)
        exact = {'task_id':fx.task.task_id, 'capsule_digest':capsule,
                 'operation_digest':preview['operation_digest']}
        case.assertEqual('APPROVED', fx.request('approve', exact)['state'])
        pipe.send((enrollment, ref, warrant.lease_epoch, s_ep, sequence.pid, r_ep, fx.host.identity.spki))
        try:
            fx.request('apply', exact)
        except CommitOutcomeUnknown:
            pass
        broker_result = message(pipe, 20)
        proc.join(5)
        case.assertEqual(0, proc.exitcode)
        case.assertEqual({'completed':True,'cas_attempts':1}, broker_result)
        case.assertEqual(route.plan.commit_sha+'\n', (repo/ref).read_text())
        with fx.host._native_coding.authority(Capability.READ) as p:
            case.assertEqual('Unknown', route.journal.inspect(p,warrant)['outcome']['contract_type'])
        case.assertIn(fx.request('read_status', {'task_id':fx.task.task_id})['state'], ('APPLYING','UNKNOWN'))
        body = dict(fx.body, retained_sandbox_task_ids=sorted(fx.host._native_coding.jobs))
        packet = dict(root=str(fx.root), native_root=str(fx.native_root), origin=fx.origin,
                      composition=body, instance=fx.host.instance_id, spki=fx.host.identity.spki,
                      source=list(fx.host.source), warrant=warrant.to_dict(), enrollment=enrollment,
                      candidates=[[{'path':f.path,'text':f.text} for f in c.files] for c in fx.candidates])
        # The lifecycle may quarantine an uncertain handle and refuse a clean
        # close. Only the supervisor observes process exit and OS lease release.
        packet.update(producer_pid=os.getpid(), broker_pid=proc.pid, ref=ref,
                      cas_attempts=broker_result['cas_attempts'])
        parent.send(packet)


def run_owned(context):
    with ExitStack() as stack:
        # Short private paths keep the kernel's sockaddr_un limit independent
        # of the operator's retained storage location.
        endpoints = Path(stack.enter_context(tempfile.TemporaryDirectory(prefix='rhq-', dir='/tmp')))
        producer, initial = child_process(stack, produce, context, endpoints)
        packet = message(initial, 900)
        producer.join(60)
        if producer.exitcode != 0 or packet['producer_pid'] != producer.pid:
            raise ValueError('ORIGINAL_CORE_EXIT_REQUIRED')
        child, cold = child_process(stack, recover, packet, endpoints)
        observed = message(cold, 90)
        child.join(15)
        actors = (producer.pid,child.pid,packet['broker_pid'],observed['verifier_pid'])
        if child.exitcode != 0 or observed['cold_core_pid'] != child.pid or len(set(actors)) != 4:
            raise ValueError('COLD_VERIFICATION_PROCESSES_REQUIRED')
        return {**observed,'qualification':'SAME_UID_OWNED_NATIVE_FIXTURE', 'production':False,
                'cross_uid_qualified':False, 'producer_pid':producer.pid, 'broker_pid':packet['broker_pid'],
                'cas_attempts':packet['cas_attempts'],
                'target_ref':packet['ref'], 'fixture_root':packet['root']}


class SnapshotReader:
    """The owned fixture may copy only pinned runtime snapshots or new session files."""
    def __init__(self, session, manifest):
        self.session = session
        self.snapshots = {Path(v['snapshot']):(v['bytes'],v['sha256'])
                          for v in manifest['manifest'].values()}

    def info(self, path):
        if (path.resolve(strict=True) != path or not stat.S_ISREG(path.lstat().st_mode)
                or (not path.is_relative_to(self.session) and path not in self.snapshots)):
            raise ValueError('UNOWNED_FIXTURE_INPUT')
        return path.lstat()

    def read(self, path, maximum=8*1024*1024):
        info = self.info(path)
        if info.st_size > maximum:
            raise ValueError('FIXTURE_INPUT_SIZE')
        with path.open('rb') as stream:
            raw = stream.read(maximum+1)
        if (len(raw) != info.st_size or (path in self.snapshots
                and self.snapshots[path] != (len(raw),hashlib.sha256(raw).hexdigest()))):
            raise ValueError('FIXTURE_INPUT_CHANGED')
        return raw


def main():
    from scripts.unification.noble_preflight import compare_manifest, host_gaps, observe, pinned_json
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest')
    parser.add_argument('--manifest-sha256')
    parser.add_argument('--management-receipt')
    parser.add_argument('--runtime-manifest', help='NZ13 bounded snapshot map pinned in the operator manifest')
    args = parser.parse_args()
    observed = observe()
    gaps = host_gaps(observed)
    if not all((args.manifest,args.manifest_sha256,args.management_receipt,args.runtime_manifest)):
        gaps.append('EXTERNAL_PINS_AND_RUNTIME_SNAPSHOTS')
    if gaps:
        print(json.dumps({'status':'BLOCKED_HOST','missing':gaps,'cas_attempts':0,'settlements':0}))
        return 2
    manifest = pinned_json(args.manifest, args.manifest_sha256)
    compare_manifest(manifest, observed, args.management_receipt)
    native = manifest['native']
    import re
    if (os.getuid() == 0 or native['uids']['core'] != os.getuid()
            or not re.fullmatch('[0-9a-f]{32}', native['session'])):
        raise ValueError('DISPOSABLE_CORE_ROLE_REQUIRED')
    runtime = pinned_json(args.runtime_manifest, native['owned_runtime_manifest_sha256'], maximum=8*1024*1024)
    session = Path('/run/aioa-qualification')/native['session']
    scratch = session/'owned-application'
    if (session.resolve(strict=True) != session or session.stat().st_uid != 0
            or stat.S_IMODE(session.stat().st_mode) & 0o022
            or scratch.resolve(strict=True) != scratch or not scratch.is_dir()
            or scratch.stat().st_uid != os.getuid() or stat.S_IMODE(scratch.stat().st_mode) != 0o700):
        raise ValueError('PRIVATE_DISPOSABLE_SCRATCH_REQUIRED')
    # Exclusive single use. An interrupted producer cannot be restarted as the same session.
    run = scratch/'run'
    run.mkdir(mode=0o700)
    fixture = run/'fixture'
    fixture.mkdir(mode=0o700)
    report = run_owned({'fixture_root':fixture, 'runtime_manifest':runtime,
                        'safe':SnapshotReader(run, runtime)})
    with (run/'application-result.json').open('x') as stream:
        json.dump(report, stream, sort_keys=True)
        stream.flush()
        os.fsync(stream.fileno())
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == '__main__':
    os.umask(0o077)
    raise SystemExit(main())
