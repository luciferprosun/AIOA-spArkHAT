"""Owned, explicitly synthetic OS/TLS data; never real Native qualification."""
import base64
import json
import os
import time
from dataclasses import asdict
from pathlib import Path
from tempfile import mkdtemp
from unittest.mock import patch

from runtime.core_admission import OwnerScope
from runtime.meta_hackathon import runtime_adapter
from runtime.mission.git_publish import GitSourceSnapshot
from runtime.mission.governor import GovernorPolicy, Limits
from runtime.mission.project_recipe import PythonFunctionCase, PythonRepositoryRecipe
from runtime.mission.sandbox_contracts import PYTHON_ARGV

OWNED_ROOTS = []

def config_data(root):
    source = GitSourceSnapshot('fixture-repo', 'fixture-workspace', 'c' * 40,
                               'd' * 40, (('src/app.py', b'def value():\n    return 1\n'),))
    project = source.export(root / 'base')
    for name in ('candidate', 'cache', 'source-repo', 'git-target', 'portable'):
        (root / name).mkdir(mode=0o700)
    case = PythonFunctionCase('one', 'app', 'value', b'[]', b'1')
    recipe = PythonRepositoryRecipe(source.repository_id, source.source_base_sha, ('src/app.py',),
                                     ('src',), tuple((stage, (case,)) for stage in ('FAST_TESTS', 'TARGETED_TESTS', 'FINAL_TESTS')),
                                     PYTHON_ARGV)
    scope = OwnerScope('local-linux', f'uid-{os.getuid()}', 'aioa-main', 'mobile-status')
    policy = GovernorPolicy(scope, 'native-mobile-chat-v1', Limits(50000000, 20),
                            Limits(50000000, 20), Limits(50000000, 20), max_clock_step_seconds=3600)
    return {'schema': 'aioa.native-host-composition.v1', 'profile': 'OWNED_OFFLINE_PROOF_V1',
            'host_source': {'source_sha': 'a' * 40, 'capsule_digest': 'b' * 64},
            'bootstrap_policy_digest': policy.digest, 'base_root': str(root / 'base'),
            'candidate_root': str(root / 'candidate'), 'source_repository': str(root / 'source-repo'),
            'git_target_repository': str(root / 'git-target'), 'sandbox_cache_root': str(root / 'cache'),
            'project_source': asdict(project),
            'source_snapshot': {'repository_id': source.repository_id, 'workspace_id': source.workspace_id,
                                'source_base_sha': source.source_base_sha, 'git_tree_sha': source.git_tree_sha,
                                'ref': source.ref, 'files': [[p, base64.b64encode(data).decode()] for p, data in source.files]},
            'recipe': json.loads(recipe.manifest_bytes()),
            'sandbox_seed': {'descriptor_path': str(root / 'cache/host-config.json'), 'descriptor_sha256': 'e' * 64},
            'retained_sandbox_task_ids': [],
            'accounting': {'job_model_id': 'aioa/offline-host-worker-v1', 'job_provider_id': 'offline-host',
                           'effect_model_binding_id': 'aioa/offline-host-worker-v1'},
            'operations': ['GIT_COMMIT', 'PORTABLE_REARM_DEMO_V1', 'PORTABLE_RELEASE_ELASTIC_IP', 'SANDBOX_EXEC'],
            'portable': {'binding': {'scope': list(scope.binding()), 'workspace': project.workspace_id,
                                     'target_id': 'fixture-target', 'incarnation': 'fixture-incarnation',
                                     'guard_fingerprint': 'f' * 64},
                         'inventory_path': str(root / 'portable/inventory.json'),
                         'registration_digest': '1' * 64, 'adoption_digest': '2' * 64,
                         'expected_head_revision': 1, 'generation': 0, 'history_digest': '3' * 64,
                         'resource_query': {'resource_type': 'AWS::EC2::EIP', 'resource_id': 'eipalloc-12345678',
                                            'region': 'eu-central-1'}},
            'limits_plan': {'sandbox_effects': 8, 'local_git_effects': 2, 'portable_effects': 2,
                            'max_duration_seconds': 3600, 'proposed_capacity': proposal()}}


def proposal(risk=80, threshold=12):
    return {'risk_limits': {'task_limit': risk, 'owner_provider_limit': risk, 'global_limit': risk},
            'sandbox_exec_failure_threshold': threshold}


def new_host(case):
    from runtime.meta_hackathon.native_authority import NativeHostCompositionConfig
    root = Path(mkdtemp(prefix="owned-native-foundation-"))
    OWNED_ROOTS.append(str(root))
    data = config_data(root)
    spec = NativeHostCompositionConfig.from_dict(data)
    authentication = {'uid': os.getuid(), 'method': 'SYNTHETIC_TEST_ONLY'}
    with patch.object(runtime_adapter, '_desktop_operator_uid', return_value=(os.getuid(), authentication)):
        owner = runtime_adapter.NativeMobileComposition(root / 'native', origin='https://fixture.example.org',
                                                       source_probe=lambda: ('a' * 40, 'b' * 64),
                                                       host_composition=spec)
    case.addCleanup(owner.close)
    return owner, data


def fixture_tls(owner):
    owner.tls_verified = True
    owner._tls_expires = time.time() + 3600
    owner.tls_pin = 'SYNTHETIC_TEST_ONLY'


def initialize(owner):
    f = owner.foundation
    return owner.operator_request(os.getuid(), {'op': 'governor_initialize', 'request_id': '0' * 32,
        'expected_version': 0, 'expected_epoch': 0, 'bootstrap_policy_digest': f.governor.policy.digest,
        'composition_digest': f.spec.digest, 'source_sha': owner.source[0], 'capsule_digest': owner.source[1]})


def review(owner, request_id='1' * 32, proposed=None):
    return owner.operator_request(os.getuid(), {'op': 'execution_capacity_review', 'request_id': request_id,
                                               'proposed': proposed or proposal()})


def approve(owner, value):
    return owner.operator_request(os.getuid(), {'op': 'execution_capacity_approve',
        'request_id': value['review']['request_id'], 'review_digest': value['review']['review_digest']})


def apply(owner, value):
    return owner.operator_request(os.getuid(), {'op': 'execution_capacity_apply',
        'request_id': value['review']['request_id'], 'review_digest': value['review']['review_digest'],
        'warrant_digest': value['warrant_digest']})
