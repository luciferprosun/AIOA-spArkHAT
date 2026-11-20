"""Public remote file projection must never disclose recognized credentials.

Synthetic content only; all transports are the existing mocked READ plane.
"""
import copy
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import test_mobile_pairing as pairing
from test_native_repository_context import PublicRepositoryFixture

from runtime.mcp_bridge import native_read
from runtime.meta_hackathon.native_tools import chat_read_context


class ReadProjectionTests(unittest.TestCase):
    def project(self, content, *, demo=False):
        fixture = PublicRepositoryFixture(demo, content)
        operation = 'github.demo_context' if demo else 'github.code_context'
        with patch.object(native_read, '_github_json', side_effect=fixture.get):
            result = native_read.read(operation, '.')
        self.assertEqual(6, len(fixture.calls))
        return fixture, result

    def test_all_fixed_file_recipes_mask_whole_source_before_bounding(self):
        for demo in (False, True):
            for payload in ('ghp_' + 'Z' * 40,
                            ('-----BEGIN OPENSSH PRIVATE KEY-----\nSYNTHETIC_BODY_ONLY\n'
                             '-----END OPENSSH PRIVATE KEY-----'),
                            'sk-' + 'Z' * 40):
                with self.subTest(demo=demo, family=payload[:4]):
                    raw = ('# Public source\n' + payload + '\n').encode()
                    fixture, result = self.project(raw, demo=demo)
                    file = result['data']['files'][0]
                    self.assertEqual('[REDACTED]', file['excerpt'])
                    self.assertTrue(file.get('redacted'))
                    self.assertFalse(file['truncated'])
                    self.assertEqual(len(raw), file['bytes'])
                    self.assertEqual(hashlib.sha256(raw).hexdigest(), file['sha256'])
                    self.assertEqual(fixture.blob, file['git_blob_sha'])
                    self.assertNotIn(payload, json.dumps(result))
                    self.assertNotIn('SYNTHETIC_BODY_ONLY', json.dumps(result))

    def test_secret_crossing_or_after_excerpt_boundary_is_not_partially_exposed(self):
        for start in (1510, 1534, 2048):
            with self.subTest(start=start):
                raw = b'X' * start + ('ghs_' + 'A' * 40 + '.BBBBBBBB.CCCCCCCC').encode()
                _, result = self.project(raw)
                self.assertEqual('[REDACTED]', result['data']['files'][0]['excerpt'])
                self.assertTrue(result['data']['files'][0].get('redacted'))

    def test_clean_legacy_shape_and_raw_hashes_are_preserved(self):
        raw = b'# Neutral fixture\nNo provider material here.\n'
        _, result = self.project(raw)
        file = result['data']['files'][0]
        self.assertEqual({'path', 'git_blob_sha', 'sha256', 'bytes', 'excerpt', 'truncated'}, set(file))
        self.assertEqual(raw.decode(), file['excerpt'])
        self.assertFalse(file['truncated'])
        native_read.validate_context_data('github.code_context', result['data'])

    def test_legacy_secret_bearing_projection_is_refused_at_receipt_resolution(self):
        raw = ('gho_' + 'Q' * 40).encode()
        fixture = PublicRepositoryFixture(content=raw)
        data = {'repository': fixture.repo, 'repository_id': fixture.repo_id,
                'url': 'https://github.com/' + fixture.repo, 'branch': 'main',
                'commit_sha': 'c' * 40, 'tree_sha': fixture.tree, 'read_source': 'GITHUB_API',
                'files': [{'path': 'README.md', 'git_blob_sha': fixture.blob,
                           'sha256': hashlib.sha256(raw).hexdigest(), 'bytes': len(raw),
                           'excerpt': raw.decode(), 'truncated': False}]}
        with self.assertRaisesRegex(ValueError, 'CHAT_READ_DATA_MISMATCH'):
            native_read.validate_context_data('github.code_context', data)

    def test_redacted_variant_cannot_claim_a_plaintext_excerpt_or_bad_flag(self):
        _, result = self.project(('github_pat_' + 'Y' * 40).encode())
        self.assertIs(result['data']['files'][0].get('redacted'), True)
        native_read.validate_context_data('github.code_context', result['data'])
        for key, bad in (('redacted', False), ('redacted', 1), ('truncated', True),
                         ('excerpt', 'attacker supplied projection')):
            with self.subTest(field=key, bad=bad):
                data = copy.deepcopy(result['data'])
                data['files'][0][key] = bad
                with self.assertRaises(ValueError):
                    native_read.validate_context_data('github.code_context', data)


class SignedProjectionTests(unittest.TestCase):
    setUp = pairing.PairingTests.setUp
    start = pairing.PairingTests.start
    tearDown = pairing.PairingTests.tearDown

    def test_same_core_signed_readback_contains_projection_and_raw_source_digest(self):
        marker = 'ghr_' + 'K' * 40
        fixture = PublicRepositoryFixture(content=('# Neutral\n' + marker).encode())
        with patch.object(native_read, '_github_json', side_effect=fixture.get):
            reply = self.app.operator_request(os.getuid(), {'op': 'tool_read',
                'operation': 'github.code_context', 'request_id': '7' * 32})
            context = chat_read_context(self.app, '7' * 32)
        self.assertNotIn(marker, json.dumps(reply))
        self.assertNotIn(marker, json.dumps(context))
        file = context['data']['files'][0]
        self.assertEqual('[REDACTED]', file['excerpt'])
        self.assertEqual(fixture.blob, file['git_blob_sha'])
        self.assertEqual(hashlib.sha256(fixture.content).hexdigest(), file['sha256'])
        self.assertEqual('UNTRUSTED_READ_DATA', context['trust'])
        self.assertEqual(6, len(fixture.calls))


class LegacyReadPrivacyTests(unittest.TestCase):
    def test_legacy_issue_title_uses_the_same_whole_field_redaction(self):
        marker = 'ghp_' + 'L' * 40
        metadata = {'id': native_read.REPOSITORY_ID, 'full_name': native_read.REPOSITORY,
                    'default_branch': 'main'}
        issue = {'number': 1, 'state': 'open', 'title': 'Neutral ' + marker,
                 'html_url': 'https://github.com/' + native_read.REPOSITORY + '/issues/1'}
        with patch.object(native_read, '_github_json', side_effect=[metadata, [issue]]):
            result = native_read.read('github.issues', '.')
        self.assertEqual('[REDACTED]', result['data']['issues'][0]['title'])
        self.assertNotIn(marker, json.dumps(result))

    def test_legacy_local_git_observations_never_echo_recognized_credentials(self):
        marker = 'github_pat_' + 'M' * 40
        for operation in ('git.log', 'git.status', 'git.branches'):
            with self.subTest(operation=operation), \
                    patch.object(native_read, '_binary'), \
                    patch.object(native_read, '_bounded_command', return_value=('Neutral ' + marker).encode()):
                result = native_read.read(operation, Path(__file__).resolve().parents[1])
                self.assertEqual('[REDACTED]', result['data']['text'])
                self.assertNotIn(marker, json.dumps(result))

    def test_credential_shaped_default_ref_is_refused_before_a_second_get(self):
        marker = 'gho_' + 'N' * 40
        metadata = {'id': native_read.REPOSITORY_ID, 'full_name': native_read.REPOSITORY,
                    'default_branch': marker}
        branch = {'name': marker, 'commit': {'sha': 'a' * 40}}
        with patch.object(native_read, '_github_json', side_effect=[metadata, branch]) as transport, \
                self.assertRaisesRegex(ValueError, 'GITHUB_CONTEXT_REF'):
            native_read.read('github.repository', '.')
        self.assertEqual(1, transport.call_count)


class SharedPolicyTests(unittest.TestCase):
    def test_shared_base_policy_is_present_and_in_the_native_source_seal(self):
        spec = importlib.util.find_spec('runtime.secret_redaction')
        self.assertIsNotNone(spec, 'Shared policy has not been ported to the base runtime')
        from runtime.meta_hackathon.runtime_adapter import SOURCE_FILES
        self.assertIn('runtime.secret_redaction', spec.name)
        self.assertIn('runtime/secret_redaction.py', SOURCE_FILES)
        self.assertIn('runtime/failure_boundary.py', SOURCE_FILES)

    def test_compatibility_import_reuses_the_same_canonical_policy_functions(self):
        self.assertIsNotNone(importlib.util.find_spec('runtime.secret_redaction'))
        from runtime import secret_redaction
        from runtime.nonzero_cloudops.models import redaction
        self.assertIs(secret_redaction.redact_sensitive_text, redaction.redact_sensitive_text)
        self.assertIs(secret_redaction.contains_sensitive_material, redaction.contains_sensitive_material)
        self.assertIs(secret_redaction._SENSITIVE_PATTERNS, redaction._SENSITIVE_PATTERNS)

    def test_base_native_composes_in_a_fresh_process_with_optional_models_forbidden(self):
        self.assertIsNotNone(importlib.util.find_spec('runtime.secret_redaction'))
        self.assertIsNotNone(importlib.util.find_spec('runtime.failure_boundary'))
        import runtime
        code = '''
import importlib.abc, os, sys, tempfile
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,sys.argv[1])
class BlockOptional(importlib.abc.MetaPathFinder):
    def find_spec(self,fullname,path=None,target=None):
        if fullname.split('.')[0] in ('uuid6','pydantic','pydantic_core'):
            raise ImportError('OPTIONAL_MODELS_FORBIDDEN')
        return None
sys.meta_path.insert(0,BlockOptional())
from runtime.meta_hackathon.runtime_adapter import NativeMobileComposition
from runtime.mcp_bridge import native_read
assert native_read._rich_text('ghp_'+'F'*40,128)=='[REDACTED]'
with tempfile.TemporaryDirectory() as directory:
    with patch('runtime.meta_hackathon.runtime_adapter._desktop_operator_uid',
               return_value=(os.getuid(),{'uid':os.getuid(),'test_only':True})):
        host=NativeMobileComposition(Path(directory)/'fixture',origin='https://host.example.org',
                                     source_probe=lambda:('1'*40,'2'*64))
    host.close()
assert not any(name.split('.')[0] in ('uuid6','pydantic','pydantic_core') for name in sys.modules)
print('BASE_NATIVE_OPTIONAL_IMPORT_FREE')
'''
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run([sys.executable, '-I', '-B', '-c', code,
                                     str(Path(runtime.__file__).resolve().parents[1])],
                                    env={'PATH': '/usr/bin:/bin', 'LANG': 'C.UTF-8',
                                         'HOME': directory, 'TMPDIR': directory, 'PYTHONDONTWRITEBYTECODE': '1'},
                                    cwd=directory, capture_output=True, timeout=30, check=False)
        self.assertEqual(0, result.returncode, result.stderr.decode(errors='replace'))
        self.assertEqual(b'BASE_NATIVE_OPTIONAL_IMPORT_FREE\n', result.stdout)

    def test_relocated_policy_files_remain_forbidden_in_a_real_patch_preview(self):
        from nz11_support import BareRepository

        from runtime.mission.git_publish import GitSourceSnapshot
        from runtime.mission.patchset import BoundedPatchSetPolicy
        from runtime.mission.worker import CandidateFile, CandidatePatch, Task
        for name in ('runtime/secret_redaction.py', 'runtime/failure_boundary.py',
                     'runtime/nonzero_cloudops/models/redaction.py'):
            with self.subTest(path=name), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                repository = BareRepository(root / 'source.git', {name: b'policy = "fixed"\n'})
                snapshot = GitSourceSnapshot.capture(repository.path, expected_sha=repository.base,
                    repository_id='policy-fixture', workspace_id='workspace-1')
                base = root / 'export'
                source = snapshot.export(base)
                task = Task('policy-task', 'policy-run', 'workspace-1', 'policy-fixture',
                            repository.base, 'Neutral fixture test.', 1000)
                candidate = CandidatePatch((CandidateFile(name, 'policy = "changed"\n'),))
                with self.assertRaisesRegex(ValueError, 'PATCHSET_CORE_POLICY_DENIED'):
                    BoundedPatchSetPolicy().preview(base, source=source, task=task,
                        worker_session_id='fixture-session', candidate=candidate)
                self.assertEqual(b'policy = "fixed"\n', (base / name).read_bytes())
