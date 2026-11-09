"""Explicit real render acceptance through the existing Core and Linux broker.

This is an operator fixture, not a host/browser launcher. It must run only after
its exact product source is frozen. No credentials, provider, HTTP service,
public network or production Native state is used.
"""
import hashlib
import json
import os
import re
import stat
import sys
import threading
import time
from pathlib import Path
from unittest.mock import patch

import nz11_kernel_acceptance as kernel

from runtime.core_admission import Capability
from runtime.mission.patch_capsule import CorePatchCapsules
from runtime.mission.render_recipe import HtmlRenderRecipe
from runtime.mission.repair_validation import CoreSandboxValidation
from runtime.mission.sandbox_linux import read_evidence_file
from runtime.mobile_gateway.wire import verify
from runtime.providers.exact import CancellationToken

HTML = b'<!doctype html><meta charset="utf-8"><title>Offline render</title><h1>Core render verified</h1>'


def reject_dispatch(*_):
    raise AssertionError('Render readback must not prepare or dispatch')


def receipt(step, *, require_readback=True):
    warrant = step.arguments['warrant']
    rows = []
    for run in step.route.executor.config.root.glob('run-*'):
        if (run / 'receipt.json').is_file():
            raw = read_evidence_file(run, 'receipt.json')
            value = json.loads(raw)
            if value.get('warrant_digest') == warrant.digest():
                rows.append((raw, value))
    assert len(rows) == 1, 'One actual retained broker receipt is required'
    raw, value = rows[0]
    assert value['cgroup_absent_after_cleanup'] is True
    assert value['unit_terminal_observed'] is True
    direct_zero = value['cgroup_populated_zero_directly_observed']
    assert type(direct_zero) is bool and value['project_code_started'] is True
    if require_readback:
        assert value['status'] == 'READBACK_VERIFIED' and direct_zero is True
    else:
        assert value['status'] == 'UNKNOWN'
    return {'sha256': hashlib.sha256(raw).hexdigest(), 'status': value['status'],
            'cleaned': True, 'project_code_started': value['project_code_started'],
            'direct_zero_readback_observed': direct_zero}



READY_MARKER = b'CHROME_FILE_NAVIGATION_ACK\n'


def wait_for_chrome_ready(work_cgroup):
    """Test-only read witness from an actual Chrome PID in this exact job.

    No host process is attached, signalled or executed. This diagnostic marker
    proves a CDP navigation response, not a visible-page PASS or Core authority.
    """
    prefix = '/sys/fs/cgroup/user.slice/user-' + str(os.getuid()) + '.slice/user@' + str(os.getuid()) + '.service/app.slice/'
    if (type(work_cgroup) is not str or re.fullmatch(
            re.escape(prefix) + r'aioa-sandbox-[a-f0-9]{32}\.service/work', work_cgroup) is None):
        raise ValueError('RENDER_CGROUP_WITNESS_REQUIRED')
    expected_cgroup = '0::' + work_cgroup.removeprefix('/sys/fs/cgroup')
    host_namespace = os.readlink('/proc/self/ns/mnt')
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        try:
            with open(work_cgroup + '/cgroup.procs') as stream:
                members = stream.read(4097)
        except OSError:
            time.sleep(.02)
            continue
        fields = members.split()
        if len(members) > 4096 or len(fields) > 64 or not all(re.fullmatch('[0-9]{1,10}', value) for value in fields):
            raise ValueError('RENDER_CGROUP_MEMBERS_INVALID')
        for value in fields:
            pid = int(value)
            if not 0 < pid < 2**31:
                raise ValueError('RENDER_CGROUP_MEMBERS_INVALID')
            owned = []
            try:
                proc = os.open('/proc/' + value, os.O_PATH | os.O_DIRECTORY | os.O_CLOEXEC | os.O_NOFOLLOW)
                owned.append(proc)
                comm = os.open('comm', os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW, dir_fd=proc)
                owned.append(comm)
                if os.read(comm, 64) != b'chrome\n':
                    continue
                cg = os.open('cgroup', os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW, dir_fd=proc)
                owned.append(cg)
                if os.read(cg, 1024).decode().strip() != expected_cgroup:
                    continue
                if os.readlink('ns/mnt', dir_fd=proc) == host_namespace:
                    continue
                artifacts = os.open('root/artifacts', os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | os.O_NOFOLLOW, dir_fd=proc)
                owned.append(artifacts)
                marker = os.open('render-browser-ready.txt', os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW, dir_fd=artifacts)
                owned.append(marker)
                before = os.fstat(marker)
                if (not stat.S_ISREG(before.st_mode) or before.st_uid != os.getuid()
                        or before.st_nlink != 1 or before.st_size != len(READY_MARKER)):
                    continue
                raw = os.read(marker, len(READY_MARKER) + 1)
                after = os.fstat(marker)
                identity = ('st_dev', 'st_ino', 'st_size', 'st_mode', 'st_uid', 'st_nlink', 'st_mtime_ns', 'st_ctime_ns')
                if raw != READY_MARKER or any(getattr(before, key) != getattr(after, key) for key in identity):
                    continue
                os.lseek(cg, 0, os.SEEK_SET)
                if os.read(cg, 1024).decode().strip() != expected_cgroup:
                    continue
                return {'schema': 'aioa.render-navigation-witness.v1', 'pid': pid,
                        'marker_sha256': hashlib.sha256(raw).hexdigest()}
            except OSError:
                continue
            finally:
                for descriptor in reversed(owned):
                    os.close(descriptor)
        time.sleep(.02)
    raise ValueError('RENDER_READY_NOT_OBSERVED')


class RenderReadyObservation:
    """Keeper ACK alone never opens this fixed acceptance barrier."""
    def __init__(self, original, active, *, probe=wait_for_chrome_ready):
        self.original, self.active, self.probe = original, active, probe
        self.work_cgroup, self.witness = None, None

    def __call__(self, stream, *args, **kwargs):
        if args == (24,):
            witness = self.probe(self.work_cgroup)
            if (type(witness) is not dict or set(witness) != {'schema', 'pid', 'marker_sha256'}
                    or witness['schema'] != 'aioa.render-navigation-witness.v1'
                    or type(witness['pid']) is not int or witness['pid'] <= 0
                    or witness['marker_sha256'] != hashlib.sha256(READY_MARKER).hexdigest()):
                raise ValueError('RENDER_READY_NOT_OBSERVED')
            self.witness = witness
            self.active.set()
        value = self.original(stream, *args, **kwargs)
        if type(value) is dict and value.get('stage') == 'WORK_READY':
            self.work_cgroup = value['work_cgroup']
        return value


def main(manifest_path, root):
    root.mkdir(mode=0o700, parents=True, exist_ok=False)
    manifest = json.loads(manifest_path.read_bytes())['manifest']
    fixture = kernel.fixture_core()
    try:
        fx = fixture.fx
        identity = kernel.support.Identity(kernel.support.ec.generate_private_key(kernel.support.ec.SECP256R1()))
        capsules = CorePatchCapsules(fx.journal, identity, source_probe=lambda: None)
        preparer = kernel.SandboxPreparer(fixture, manifest, root, resource_profile='HEADLESS_RENDER_V3')
        validator = CoreSandboxValidation(fx.journal, reject_dispatch, render_capsules=capsules)
        recipe = HtmlRenderRecipe((('index.html', HTML),), (320, 200),
                                  'Offline render', 'Core render verified')
        step = preparer.steps((('RENDER', recipe.recipe_spec()),))[0]
        result = validator.render(fx.p(), step, recipe)
        assert result['status'] == 'PASS' and result['authority'] == 'NONE'
        assert result['oracle']['screenshot']['visible_ink_pixels'] > 0
        proof = {k: v for k, v in result.items() if k not in ('signature', 'record_id')}
        verify(identity.spki, result['signature'], proof)
        actual_receipt = receipt(step)
        assert result['evidence_digest'] == actual_receipt['sha256']
        assert result['warrant_digest'] == step.arguments['warrant'].digest()
        assert fx.journal.inspect(fx.p(Capability.READ), step.arguments['warrant'])['outcome']['contract_type'] == 'Applied'
        config = step.route.executor.config
        first_runs = sorted(str(path) for path in config.root.glob('run-*'))
        recovered = CoreSandboxValidation(fx.journal, reject_dispatch, render_capsules=capsules)
        observed = recovered.read_render(fx.p(Capability.READ), result['warrant_digest'])
        assert observed == {k: v for k, v in result.items() if k != 'record_id'}
        assert recovered.render(fx.p(), step, recipe) == result
        assert sorted(str(path) for path in config.root.glob('run-*')) == first_runs
        denied = []
        for name, failed in (
                ('document-oracle', HtmlRenderRecipe(recipe.bundle, recipe.viewport,
                                                     'Wrong expected title', recipe.expected_text)),
                ('console-error', HtmlRenderRecipe((('index.html', HTML + b'<script>console.error("fixture error")</script>'),),
                                                  recipe.viewport, recipe.expected_title, recipe.expected_text))):
            failed_step = preparer.steps((('RENDER', failed.recipe_spec()),))[0]
            try:
                validator.render(fx.p(), failed_step, failed)
            except ValueError as failure:
                assert str(failure) in ('RENDER_DOCUMENT_ORACLE', 'RENDER_OBSERVATION_BINDING'), str(failure)
            else:
                raise AssertionError('An invalid real observation created a PASS')
            assert validator.read_render(fx.p(Capability.READ), failed_step.arguments['warrant'].digest()) is None
            denied.append({'case': name, 'pass_record': False, 'receipt': receipt(failed_step)})

        # STOP requires a real Chrome PID and a marker written only after its
        # fixed file-navigation CDP reply. This is not a DOM visibility proof.
        import runtime.mission.sandbox_linux as linux
        busy = HtmlRenderRecipe((('index.html', HTML + b'<script>while(true){}</script>'),),
                                recipe.viewport, recipe.expected_title, recipe.expected_text)
        stopped_step = preparer.steps((('RENDER', busy.recipe_spec()),))[0]
        cancellation = CancellationToken()
        stopping = CoreSandboxValidation(fx.journal, reject_dispatch,
                                         render_capsules=capsules, cancel=cancellation)
        active = threading.Event()
        observation = RenderReadyObservation(linux.bounded_line, active)
        completed = []

        def run_stoppable():
            try:
                stopping.render(fx.p(), stopped_step, busy)
            except ValueError:
                completed.append('DENIED_NO_PASS')
            else:
                completed.append('UNEXPECTED_PASS')

        with patch.object(linux, 'bounded_line', side_effect=observation):
            thread = threading.Thread(target=run_stoppable, daemon=True)
            thread.start()
            assert active.wait(45), 'No actual Chrome navigation witness before STOP'
            cancellation.cancel()
            thread.join(45)
            assert not thread.is_alive(), 'STOP left a sandbox operation running'
        assert completed == ['DENIED_NO_PASS'], completed
        assert stopping.read_render(fx.p(Capability.READ), stopped_step.arguments['warrant'].digest()) is None
        stop_receipt = receipt(stopped_step, require_readback=False)
        assert stop_receipt['status'] == 'UNKNOWN'
        assert fx.journal.inspect(fx.p(Capability.READ), stopped_step.arguments['warrant'])['outcome']['contract_type'] == 'Unknown'
        report = {'schema': 'aioa.nz13.hermetic-render-acceptance.v1',
                  'status': 'PASS_REAL_LOCAL_CORE_BROKER_CHROME_ONLY',
                  'signed_pass': result, 'actual_broker_receipt': actual_receipt,
                  'readback_without_replay': True, 'negative_observations': denied,
                  'active_stop': stop_receipt, 'stop_unknown_not_success': True,
                  'actual_chrome_navigation_witness': observation.witness,
                  'stop_proves_dom_visibility': False,
                  'same_core': True, 'same_capsule_identity': True,
                  'network': 'OFF', 'cdp': 'PIPE', 'inherited_browser_profile': False,
                  'provider_calls': 0, 'remote_calls': 0, 'production_changes': 0}
        with (root / 'NZ13_RENDER_ACCEPTANCE.json').open('x') as stream:
            json.dump(report, stream, indent=2)
        print(json.dumps({'status': report['status'], 'receipt': str(root / 'NZ13_RENDER_ACCEPTANCE.json')}), flush=True)
    finally:
        fixture.doCleanups()


if __name__ == '__main__':
    main(Path(sys.argv[1]), Path(sys.argv[2]))
