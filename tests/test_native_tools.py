"""Offline contracts only: fake network, real Core/SQLite and bounded child IO."""
import importlib
import importlib.util
import json
import os
from pathlib import Path
import unittest
import tempfile
import subprocess
import shlex
from unittest.mock import patch

import test_mobile_pairing as pairing_fixture
from runtime.core_admission import AdmissionError
from runtime.mobile_gateway import wire
from runtime.memory_patch.errors import MemoryPatchError


def module(test):
    name = 'runtime.mcp_bridge.native_read'
    test.assertIsNotNone(importlib.util.find_spec(name), 'bounded native READ executor is absent')
    return importlib.import_module(name)


class NativeReadTests(unittest.TestCase):
    def test_repository_is_numeric_identity_bound_and_projects_only_public_fields(self):
        m = module(self)
        repo = {'id': 1247349659, 'full_name': 'luciferprosun/AIOA-spArkHAT',
                'default_branch': 'main', 'visibility': 'public', 'private': False,
                'html_url': 'https://github.com/luciferprosun/AIOA-spArkHAT',
                'irrelevant': 'must not reach UI'}
        branch = {'name': 'main', 'commit': {'sha': 'a' * 40}}
        with patch.object(m, '_github_json', side_effect=[repo, branch]) as transport:
            result = m.read('github.repository', Path(__file__).resolve().parents[1])
        self.assertEqual('main', result['data']['branch'])
        self.assertEqual('a' * 40, result['data']['commit_sha'])
        self.assertEqual(1247349659, result['data']['repository_id'])
        self.assertNotIn('irrelevant', result['data'])
        self.assertEqual(2, transport.call_count)

    def test_write_arbitrary_url_and_flags_are_denied_before_any_child(self):
        m = module(self)
        with patch.object(m, '_bounded_command') as child:
            for op in ('issue.create', 'git.push', 'https://evil.test', '--help', '', None):
                with self.subTest(op=op), self.assertRaises(ValueError):
                    m.read(op, Path(__file__).resolve().parents[1])
            child.assert_not_called()

    def test_repository_substitution_is_denied(self):
        m = module(self)
        for repo in ({'id': 1, 'full_name': 'luciferprosun/AIOA-spArkHAT'},
                     {'id': 1247349659, 'full_name': 'attacker/repo'}):
            with self.subTest(repo=repo), patch.object(m, '_github_json', return_value=repo), self.assertRaises(ValueError):
                m.read('github.repository', Path(__file__).resolve().parents[1])

    def test_git_status_disables_helpers_and_has_no_model_arguments(self):
        m = module(self)
        with patch.object(m, '_bounded_command', return_value=b'') as child:
            result = m.read('git.status', Path(__file__).resolve().parents[1])
        argv = child.call_args.args[0]
        self.assertIn('core.fsmonitor=false', argv)
        self.assertIn('--no-optional-locks', argv)
        self.assertEqual('git.status', result['operation'])
        self.assertNotIn('shell', child.call_args.kwargs)
        self.assertEqual('/dev/null', child.call_args.kwargs['env']['GIT_CONFIG_GLOBAL'])
        self.assertEqual('', child.call_args.kwargs['env'].get('GIT_ALLOW_PROTOCOL'), 'Git must deny every transport, including configured remote helpers')

    def test_child_output_and_timeout_are_bounded(self):
        m = module(self)
        with self.assertRaises(ValueError):
            m._bounded_command(['/usr/bin/python3', '-I', '-c', 'print("x"*5000)'],
                               cwd=Path('/tmp'), env={'PATH': '/usr/bin:/bin'}, timeout=2, max_bytes=100)
        with self.assertRaises(ValueError):
            m._bounded_command(['/usr/bin/python3', '-I', '-c', 'import time; time.sleep(2)'],
                               cwd=Path('/tmp'), env={'PATH': '/usr/bin:/bin'}, timeout=.05)

    def test_old_or_escaped_transport_config_is_rejected_without_gh_migration(self):
        m = module(self)
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            for content in ('git_protocol: https\n', 'version: 1\n"http_\\u0075nix_socket": /tmp/evil\n',
                            'version: ""\nversion: 1\nhttp_unix_socket: ""\n',
                            'version: 01\nhttp_unix_socket: ""\n',
                            'version: 1\nbase: &b {http_unix_socket: /tmp/evil}\n<<: *b\n'):
                (directory/'config.yml').write_text(content)
                (directory/'config.yml').chmod(0o600)
                with patch.object(m, '_qualified_gh'), patch.object(m, '_environment', return_value={'GH_CONFIG_DIR': tmp}), patch.object(m, '_bounded_command',return_value=b'') as child:
                    with self.assertRaises(ValueError): m._github_json('repos/'+m.REPOSITORY)
                    child.assert_not_called()

    def test_host_transport_override_is_checked_before_api_and_env_is_clean(self):
        m = module(self)
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp)/'config.yml').write_text('version: 1\n')
            (Path(tmp)/'config.yml').chmod(0o600)
            with patch.object(m, '_qualified_gh'), patch.object(m, '_environment', return_value={'GH_CONFIG_DIR': tmp}), patch.object(m, '_bounded_command', side_effect=[b'\n', b'/tmp/evil\n']) as child:
                with self.assertRaises(ValueError): m._github_json('repos/'+m.REPOSITORY)
                self.assertEqual(2, child.call_count)
                self.assertTrue(all('api' not in c.args[0] for c in child.call_args_list))
        with patch.dict(os.environ, {'GH_TOKEN': 'synthetic-secret', 'HTTPS_PROXY': 'http://evil', 'GH_DEBUG': 'api'}):
            env = m._environment()
            self.assertFalse({'GH_TOKEN','GITHUB_TOKEN','HTTPS_PROXY','GH_DEBUG'} & set(env))

    def test_every_child_checks_authority_and_cannot_continue_after_revocation(self):
        m = module(self); revoked = False
        def check():
            if revoked: raise AdmissionError()
        def first(*args, **kwargs):
            nonlocal revoked
            revoked = True
            return {'id': 1247349659, 'full_name': m.REPOSITORY, 'default_branch': 'main'}
        with patch.object(m, '_github_json', side_effect=first) as child:
            with self.assertRaises(AdmissionError): m.read('github.repository', Path('/tmp'), check=check)
            self.assertEqual(1, child.call_count)

    def test_partial_clone_transport_fence_denies_helper_even_when_repo_enables_ext(self):
        m = module(self)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); marker = root/'HELPER_RAN'; helper = root/'helper'
            helper.write_text('#!/bin/sh\nprintf invoked > '+shlex.quote(str(marker))+'\nexit 1\n')
            helper.chmod(0o700)
            def git(*args, body=None):
                return subprocess.check_output(['/usr/bin/git', '-C', tmp, *args], input=body, stderr=subprocess.DEVNULL).strip()
            git('init', '-q')
            git('config', 'core.repositoryformatversion', '1')
            git('config', 'remote.origin.url', 'ext::'+str(helper))
            git('config', 'remote.origin.promisor', 'true')
            git('config', 'extensions.partialClone', 'origin')
            git('config', 'protocol.ext.allow', 'always')
            tree = git('hash-object', '-w', '-t', 'tree', '--stdin', body=b'').decode()
            content = ('tree '+tree+'\nparent '+'1'*40+'\nauthor Fixture <fixture@example.invalid> 1 +0000\n'
                       'committer Fixture <fixture@example.invalid> 1 +0000\n\nOffline missing parent\n').encode()
            commit = git('hash-object', '-w', '-t', 'commit', '--stdin', body=content).decode()
            git('update-ref', 'HEAD', commit)
            with self.assertRaises(ValueError): m.read('git.log', root)
            self.assertFalse(marker.exists(), 'Native READ invoked an external transport helper')
            # Git2.43 log fails at the missing parent without lazy fetching.
            # Exercise the same environment/IO fence using an actual promisor
            # object lookup, then prove its negative control invokes the helper.
            lookup = ['/usr/bin/git', '-C', tmp, 'cat-file', '-p', '1'*40]
            with self.assertRaises(ValueError):
                m._bounded_command(lookup, cwd=root, env=m._environment())
            self.assertFalse(marker.exists())
            unprotected = m._environment();unprotected.pop('GIT_ALLOW_PROTOCOL');unprotected.pop('GIT_NO_LAZY_FETCH')
            with self.assertRaises(ValueError):
                m._bounded_command(lookup, cwd=root, env=unprotected)
            self.assertTrue(marker.exists(), 'negative control did not exercise lazy fetch')


class NativeToolCoreTests(unittest.TestCase):
    setUp = pairing_fixture.PairingTests.setUp
    start = pairing_fixture.PairingTests.start
    tearDown = pairing_fixture.PairingTests.tearDown

    def invoke(self, request='c' * 32, operation='github.repository', **extra):
        return self.app.operator_request(os.getuid(), dict(op='tool_read', request_id=request, operation=operation, **extra))

    def test_core_receipt_is_signed_durable_and_replay_does_not_repeat_network(self):
        m = module(self)
        with patch.object(m, 'read', return_value={'operation': 'github.repository', 'data': {'commit_sha': 'd' * 40}, 'transport': 'FIXTURE_NOT_LIVE'}) as read:
            result = self.invoke()
            self.assertEqual(result, self.invoke())
            self.assertEqual(1, read.call_count)
        self.assertEqual('READ', result['receipt']['effect'])
        self.assertEqual('FIXTURE_NOT_LIVE', result['receipt']['transport'])
        self.assertEqual(wire.digest(wire.canonical(result['data'])), result['receipt']['data_sha256'])
        wire.verify(self.app.identity.spki, result['signature'], result['receipt'])
        self.app.close(); self.start()
        with patch.object(m, 'read') as read:
            historical = self.invoke()
            self.assertEqual(result, historical)
            read.assert_not_called()

    def test_lease_peer_source_and_injection_denied_before_external_read(self):
        m = module(self)
        with patch.object(m, 'read') as read:
            with self.assertRaises((wire.MobileError, ValueError)):
                self.invoke(approved=True)
            with self.assertRaises((wire.MobileError, ValueError)):
                self.invoke(operation='issue.create')
            with self.assertRaises(AdmissionError):
                self.app.operator_request(os.getuid()+1, {'op': 'tool_read', 'request_id': 'c'*32, 'operation': 'github.repository'})
            self.source[1] = 'e' * 64
            with self.assertRaises(AdmissionError): self.invoke()
            self.source[1] = 'b' * 64; self.app._auth_deadline = 0
            with self.assertRaises(AdmissionError): self.invoke()
            read.assert_not_called()

    def test_source_change_during_read_refuses_receipt(self):
        m = module(self)
        def drift(*args, **kwargs):
            self.source[0] = 'd' * 40
            return {'operation': 'github.repository', 'data': {}, 'transport': 'FIXTURE_NOT_LIVE'}
        with patch.object(m, 'read', side_effect=drift), self.assertRaises(AdmissionError): self.invoke()

    def test_tls_expiry_after_signing_cannot_commit_success(self):
        m=module(self);original=wire.Identity.sign
        def expire(identity,value):
            signature=original(identity,value)
            self.app._tls_expires=0
            return signature
        with patch.object(m,'read',return_value={'operation':'github.repository','data':{},'transport':'FIXTURE_NOT_LIVE'}), patch.object(wire.Identity,'sign',autospec=True,side_effect=expire):
            with self.assertRaises((AdmissionError,MemoryPatchError)):self.invoke()
        self.assertEqual('TOOL_READ_PENDING',self.app.mobile._get('native-tool-read-'+'c'*32).payload['state'])


class NativeChatToolTests(unittest.TestCase):
    setUp=pairing_fixture.PairingTests.setUp
    tearDown=pairing_fixture.PairingTests.tearDown
    invoke=NativeToolCoreTests.invoke

    def start(self):
        from test_mobile_chat import NativeChatTests
        NativeChatTests.start(self)

    def test_chat_enabled_read_commits_without_nested_transaction_or_model_call(self):
        m=module(self)
        with patch.object(m,'read',return_value={'operation':'git.status','data':{'text':''},'transport':'LOCAL_GIT_READ'}), patch('runtime.providers.meta_model_api._https_once') as model:
            value=self.app.operator_request(os.getuid(),{'op':'tool_read','request_id':'c'*32,'operation':'git.status'})
            self.assertEqual('READ',value['receipt']['effect'])
            model.assert_not_called()

    def test_registry_does_not_construct_cpl_or_spend(self):
        module(self)
        result = self.app.operator_request(os.getuid(), {'op': 'status'})
        self.assertEqual('BLOCKED_NATIVE_CPL_NOT_BOUND', result['components']['cpl']['status'])
        self.assertFalse(result['components']['github_write']['enabled'])
        self.assertEqual(0, result['model_calls'])
        self.assertEqual(0, result['components']['cpl']['provider_calls'])

    def test_registry_reports_only_current_instance_verified_github_observation(self):
        m=module(self)
        result=self.app.operator_request(os.getuid(),{'op':'status'})
        self.assertEqual('NOT_RUN',result['components']['github_read']['status'])
        with patch.object(m,'read',return_value={'operation':'github.repository','data':{'repository':m.REPOSITORY},'transport':'LIVE_GITHUB_GET'}):
            self.invoke()
        result=self.app.operator_request(os.getuid(),{'op':'status'})
        self.assertEqual('VERIFIED_READ',result['components']['github_read']['status'])
        self.assertEqual('c'*32,result['components']['github_read']['request_id'])
        self.app.close();self.start()
        result=self.app.operator_request(os.getuid(),{'op':'status'})
        self.assertEqual('NOT_RUN',result['components']['github_read']['status'])

    def test_readback_only_never_dispatches_and_pending_cannot_replay(self):
        m = module(self)
        with patch.object(m, 'read', side_effect=ValueError('synthetic transport failure')) as read:
            with self.assertRaises(ValueError): self.invoke()
            pending = self.app.operator_request(os.getuid(), {'op': 'tool_readback', 'request_id': 'c'*32})
            self.assertEqual('UNKNOWN', pending['state'])
            with self.assertRaises(wire.MobileError): self.invoke()
            self.assertEqual(1, read.call_count)

    def test_proposal_requires_real_current_chat_receipt_and_never_executes(self):
        module(self)
        request = {'op': 'tool_proposal', 'request_id': 'd'*32, 'chat_request_id': 'a'*32}
        fake = {'state': 'SUCCEEDED', 'live_verified': True, 'current_source': True,
                'source_sha': self.source[0], 'capsule_digest': self.source[1], 'request_id': 'a'*32,
                'thread_id': 'b'*32, 'receipt': {'response_sha256': 'e'*64},
                'reply': json.dumps({'operation': 'issue.create', 'target_repo': 'luciferprosun/AIOA-spArkHAT',
                                     'title': 'Synthetic proposal', 'body': 'Offline test, not a real model call.'})}
        fake['receipt']['response_sha256'] = wire.digest(fake['reply'].encode())
        with patch.object(self.app.missions, 'chat_request', return_value=fake):
            result = self.app.operator_request(os.getuid(), request)
            self.assertFalse(result['execution_authorized'])
            self.assertEqual('issue.create', result['proposal']['operation'])
            self.assertEqual('BLOCKED_REMOTE_START_NOT_BOUND', result['status'])
            self.assertIsNone(result['proposal']['approval_digest'])
            fake['current_source'] = False
            with self.assertRaises(wire.MobileError):
                self.app.operator_request(os.getuid(), {**request, 'request_id': 'e'*32})
