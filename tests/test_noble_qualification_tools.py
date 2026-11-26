"""Offline operator-harness contracts. No host qualification or Chrome launch."""
import base64
import copy
import json
import os
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric import ec
from lab_archaioa import test_warrant
from runtime.mission.sandbox_contracts import SandboxOperation, SandboxRecipe
from runtime.mobile_gateway.wire import Identity
from scripts.unification import g04_qualification as g04
from scripts.unification import noble_preflight as noble
from scripts.unification import noble_role_probe as role
from test_nz13_render_observation import png


class QualificationContracts(unittest.TestCase):
    def test_unsigned_laptop_inputs_cannot_dispatch(self):
        from unittest.mock import patch
        with patch.object(g04, 'observe', return_value={}), patch.object(g04, 'host_gaps', return_value=['OS']):
            with self.assertRaisesRegex(ValueError, 'BLOCKED_HOST'):
                g04.execute_admitted(None, None, None, manifest_path=None,
                                     manifest_sha256=None, management_receipt=None)

    def test_manifest_must_match_digest_from_separate_channel(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'manifest.json'
            path.write_bytes(b'{"source":1}')
            pin = noble.digest(path.read_bytes())
            self.assertEqual(noble.pinned_json(path, pin), {'source': 1})
            path.write_bytes(b'{"source":2}')
            with self.assertRaisesRegex(ValueError, 'DOCUMENT_PIN_MISMATCH'):
                noble.pinned_json(path, pin)

    def test_missing_path_and_symlink_do_not_count_as_permission_denial(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'existing').write_bytes(b'sentinel')
            (root / 'link').symlink_to(root / 'existing')
            mode = os.O_WRONLY
            self.assertEqual(role.try_open(root, Path('existing'), mode), 'OPENED')
            self.assertEqual((root / 'existing').read_bytes(), b'sentinel')
            for path in ('missing', 'link', 'link/child'):
                with self.subTest(path=path), self.assertRaises(OSError):
                    role.try_open(root, Path(path), mode)

    def test_role_denials_use_the_authorized_empty_ref_and_same_pattern_siblings(self):
        target = 'refs/heads/aioa/nz11-' + 'a' * 32
        root = Path('/example')
        rows = role.probe_paths(root, {'exact_ref': target}, 'verifier')
        self.assertEqual(rows['exact_create'][0], root / 'repo' / target)
        self.assertTrue(rows['exact_create'][1] & os.O_EXCL)
        for key in ('sibling_write', 'sibling_create'):
            self.assertEqual(rows[key][0].parent, rows['exact_create'][0].parent)
            self.assertRegex(rows[key][0].name, r'^nz11-[0-9a-f]{32}$')
        self.assertEqual(len({rows[k][0] for k in ('sibling_write', 'sibling_create', 'exact_create')}), 3)
        with self.assertRaisesRegex(ValueError, 'NATIVE_PLAN_REF_REQUIRED'):
            role.probe_paths(root, {'exact_ref': 'refs/heads/qualification'}, 'broker')

    def export(self):
        signer = Identity(ec.generate_private_key(ec.SECP256R1()))
        fixed = g04.recipe()
        spec = SandboxRecipe('recipe:html-' + fixed.digest[:24], 'test-only', 'a' * 64, 'b' * 64,
                             'c' * 64, pids_max=128, timeout_ms=20000, resource_profile='HEADLESS_RENDER_V3')
        op = {'operation_class': 'SANDBOX_EXEC', 'expected_target_revision': 'recipe-v1',
              'target_fingerprint': 'sha256:' + 'd' * 64, 'payload': spec.payload('workspace', 'task', 'step')}
        sample = test_warrant.WarrantTests().fixture()
        warrant = replace(sample, operation_hash=SandboxOperation.parse(op).digest)
        pins = {'core_spki_sha256': noble.digest(base64.b64decode(signer.spki)), 'warrant': warrant.digest(),
                'session_id': 'fixture-session', 'profile_sha256': 'a' * 64,
                'uid': 17001, 'recipe_sha256': fixed.digest}
        scanline = b'\x00' + b'\x00\x00\x00\xff' * 20 + b'\xff\xff\xff\xff' * 300
        image = png(width=320, height=200, rows=scanline * 200)
        document = {'href': 'file:///work/site/index.html', 'ready_state': 'complete',
                    'title': fixed.expected_title, 'body_text': fixed.expected_text}
        stdout = json.dumps({'schema': 'aioa.hermetic-render-observation.v1', 'recipe_digest': fixed.digest,
                             'document': document, 'console_errors': 0,
                             'transport': {'kind': 'CDP_PIPE', 'network': 'OFF', 'profile': 'FRESH'},
                             'screenshot_base64': base64.b64encode(image).decode()})
        unit = 'aioa-sandbox-' + 'a' * 32 + '.service'
        cg = '/user.slice/user-17001.slice/user@17001.service/app.slice/' + unit + '/work'
        receipt = {'request': {'session_id': pins['session_id'], 'operation': op},
                   'warrant_digest': warrant.digest(), 'operation_digest': warrant.operation_hash,
                   'profile_digest': pins['profile_sha256'], 'status': 'READBACK_VERIFIED',
                   'unit_terminal_observed': True, 'project_code_started': True, 'unit': unit,
                   'cgroup_absent_after_cleanup': True, 'cgroup_populated_zero_directly_observed': True,
                   'observations': {'worker_gate': {'work_cgroup': '/sys/fs/cgroup' + cg, 'before_exec_placement': True},
                                    'peer': {'uid': 17001, 'cgroup': '0::' + cg, 'pidfd_pinned': True},
                                    'worker_populated_zero_after_readback': True,
                                    'worker_populated_zero_before_readback': True,
                                    'namespaces': {k: {'host': 'old', 'worker': 'new'} for k in
                                                   ('user', 'mnt', 'pid', 'net', 'ipc', 'uts', 'cgroup')},
                                    'privileges': {'Seccomp': '2', 'NoNewPrivs': '1', 'CapEff': '0'},
                                    'worker_terminal': {'stdout': stdout}}}
        proof = {'schema': 'aioa.trusted-render-validation.v1', 'status': 'PASS', 'authority': 'NONE',
                 'warrant_digest': warrant.digest(), 'warrant': warrant.to_dict(),
                 'operation_digest': warrant.operation_hash, 'sandbox_profile_digest': pins['profile_sha256'],
                 'profile_digest': fixed.digest, 'oracle': fixed.verify_observation(stdout.encode())}
        return signer, pins, proof, receipt

    def test_signed_fixture_checks_and_retains_separate_stop_requirement(self):
        signer, pins, proof, receipt = self.export()
        raw = json.dumps(receipt).encode()
        proof['evidence_digest'] = noble.digest(raw)
        record = {**proof, 'signature': signer.sign(proof)}
        result = g04.verify_export(pins, record, raw, signer.spki)
        self.assertEqual(result['active_stop'], 'SEPARATE_EVIDENCE_REQUIRED')
        with self.assertRaisesRegex(ValueError, 'G04_SIGNED_RECEIPT'):
            g04.verify_export(pins, record, raw + b' ', signer.spki)
        with self.assertRaisesRegex(ValueError, 'G04_SIGNER'):
            g04.verify_export(dict(pins, core_spki_sha256='0' * 64), record, raw, signer.spki)
        for key, value, code in [('cgroup_absent_after_cleanup', False, 'G04_CLEANUP'),
                                 ('warrant_digest', 'wrong', 'G04_RECEIPT_BINDINGS')]:
            changed = copy.deepcopy(receipt)
            changed[key] = value
            raw = json.dumps(changed).encode()
            proof['evidence_digest'] = noble.digest(raw)
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, code):
                g04.verify_export(pins, {**proof, 'signature': signer.sign(proof)}, raw, signer.spki)
