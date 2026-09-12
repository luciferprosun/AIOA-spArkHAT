"""Offline one-system certification; never loads or retrieves retired source."""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import re
import tomllib
import zipfile
from pathlib import Path

JUDGE = '4fafed8b1a877e55d96ddd9baea0a737fbeeaa4a'
SOURCE_TREE = 'a6587b72b4f7d1365ef7de7cab107ea6578f4567'
PHASE3 = '6563f93e2b895d494063161b438d05209e2655ca'
IMPORT = '119a8ba12e54a2fbea42a43d62725e25fb5bc380'
MANIFESTS = {'pyproject.toml', 'setup.py', 'setup.cfg', 'package.json', 'MANIFEST.in',
             'Pipfile', 'poetry.lock', 'requirements.txt'}
FORBIDDEN_IMPORTS = {'aioa_cloudops_agent', 'subprocess', 'strands', 'boto3', 'botocore',
    'socket', 'socketserver', 'http', 'flask', 'fastapi', 'aiohttp', 'requests', 'urllib'}
FORBIDDEN_TEXT = ('baseline', 'aioa_cloudops_agent', 'AIOA-NonZero-CloudOps-Agent',
    'AIOA-Integration-Sandbox', 'sys.path', 'PYTHONPATH', 'LocalApiApplication',
    'run_local_hitl_api', 'portable_server', 'operator.credential',
    'git clone', 'git fetch', 'git pull', 'pip install', 'git+')
FORBIDDEN_CALLS = {'eval', 'exec', '__import__', 'os.system', 'os.popen',
                   'importlib.import_module', 'ProviderManager', 'HTTPServer',
                   'ThreadingHTTPServer', 'Popen'}


def _call_name(node):
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return _call_name(node.value)+'.'+node.attr
    return ''


def inspect_python(source: str) -> list[str]:
    errors = []
    for text in FORBIDDEN_TEXT:
        if text in source:
            errors.append('FORBIDDEN_NATIVE_REFERENCE:'+text)
    try:
        tree = ast.parse(source, feature_version=(3, 11))
    except SyntaxError:
        return [*errors, 'NATIVE_PY311_SYNTAX']
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports = [alias.name.split('.')[0] for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            imports = [(node.module or '').split('.')[0]] if not node.level else []
            if node.level > 2:
                errors.append('NATIVE_RELATIVE_IMPORT_ESCAPE')
        else:
            imports = []
        errors.extend('FORBIDDEN_NATIVE_IMPORT:'+name for name in imports if name in FORBIDDEN_IMPORTS)
        if isinstance(node, ast.Call) and _call_name(node.func) in FORBIDDEN_CALLS:
            errors.append('FORBIDDEN_NATIVE_CALL:'+_call_name(node.func))
        if isinstance(node, ast.ClassDef) and node.name in {'LocalApiApplication', 'ProviderManager', 'SessionManager', 'TokenAuthorizer'}:
            errors.append('SECOND_APPLICATION_MECHANISM:'+node.name)
    return sorted(set(errors))


def inspect_module(module: Path) -> dict:
    errors = []
    baseline = module/'baseline'
    if baseline.exists() or baseline.is_symlink():
        errors.append({'path': 'baseline', 'code': 'BASELINE_PATH_EXISTS'})
    if not module.is_dir() or module.is_symlink():
        errors.append({'path': '.', 'code': 'NATIVE_DIRECTORY_UNAVAILABLE'})
    nested_git, manifests, count = [], [], 0
    for path in sorted(module.rglob('*')):
        relative = str(path.relative_to(module))
        if path.is_symlink():
            errors.append({'path': relative, 'code': 'NATIVE_SYMLINK'})
            continue
        if path.name in {'.git', '.gitmodules'}:
            nested_git.append(relative)
        if path.name in MANIFESTS or path.name.endswith(('.dist-info', '.egg-info')):
            manifests.append(relative)
        if path.is_file() and path.suffix == '.py':
            count += 1
            for code in inspect_python(path.read_text(encoding='utf-8')):
                errors.append({'path': relative, 'code': code})
    errors.extend({'path': path, 'code': 'NESTED_GIT'} for path in nested_git)
    errors.extend({'path': path, 'code': 'SECOND_PACKAGE'} for path in manifests)
    for required in ('__init__.py', 'contract.py', 'service.py', 'execution.py', 'policy.py',
                     'verification.py', 'provenance.py', 'adapters/portable.py', 'LICENSE-NONZERO.txt'):
        if not (module/required).is_file():
            errors.append({'path': required, 'code': 'NATIVE_COMPONENT_MISSING'})
    return {'status': 'PASS' if not errors else 'FAIL', 'native_python_files': count,
        'BASELINE_PATH_EXISTS': 'YES' if baseline.exists() or baseline.is_symlink() else 'NO',
        'NESTED_GIT': 'YES' if nested_git else 'NO', 'SECOND_PACKAGE': 'YES' if manifests else 'NO',
        'findings': errors}


def verify_ownership(runtime: Path) -> list[dict]:
    required = {
        'main.py': ('class AgentRuntime', 'def nonzero_cloudops', 'NonZeroCloudOpsService(',
                    'self.safeguards.kill_switch', 'self.nonzero_config', 'native-v1', 'NONZERO_REQUIRES_OPERATOR_ENDPOINTS'),
        'commands/local_commands.py': ('def cmd_nonzero', 'runtime.nonzero_cloudops'),
        'webapp.py': ('class WebRuntimeService', 'def _handle_nonzero', 'self._service().runtime.nonzero_cloudops',
                      'nonzero-operator-v1', 'X-AIOA-Session-Token'),
        'nonzero_cloudops/provenance.py': ('from tools.provenance import AppendOnlyProvenanceStore, verify_provenance_chain',),
        'nonzero_cloudops/service.py': ('CoreEvidenceLink(', 'BoundExecutionWorkflow(', 'InvestigationWorkflow(',
                                       'operator_id: str', 'self._guard()', 'self._evidence.check('),
        'nonzero_cloudops/execution.py': ('request_approval', 'def decide', 'def resume', 'decision_nonce',
                                         'proposal_hash', 'RECOVERY_REQUIRED'),
    }
    errors = []
    for relative, tokens in required.items():
        path = runtime/relative
        source = path.read_text() if path.is_file() else ''
        for token in tokens:
            if token not in source:
                errors.append({'path': relative, 'code': 'CORE_OWNERSHIP_OR_SAFETY_SEAM_MISSING', 'required': token})
    return errors


def verify_provenance(project: Path) -> dict:
    lock_path = project/'docs/provenance/NONZERO_CLOUDOPS_RETIREMENT_LOCK.json'
    lock = json.loads(lock_path.read_text())
    expected = {'source_repo': 'luciferprosun/AIOA-NonZero-CloudOps-Agent', 'judge_sha': JUDGE,
        'source_tree_sha': SOURCE_TREE, 'phase2_import_commit': IMPORT,
        'phase3_native_final_sha': PHASE3, 'source_file_count': 412,
        'statement': 'reference source retired from active tree; recoverable from Git history / frozen source'}
    errors = [key for key, value in expected.items() if lock.get(key) != value]
    artifacts = {'license_sha256': 'runtime/nonzero_cloudops/LICENSE-NONZERO.txt',
                 'native_source_map_sha256': 'docs/provenance/NONZERO_CLOUDOPS_NATIVE_MAP.json',
                 'parity_fixture_sha256': 'tests/fixtures/nonzero_parity_v1.json'}
    for key, relative in artifacts.items():
        if hashlib.sha256((project/relative).read_bytes()).hexdigest() != lock.get(key):
            errors.append(key)
    mapping = json.loads((project/artifacts['native_source_map_sha256']).read_text())
    if mapping['source_sha'] != JUDGE or len(mapping['ports']) != 26:
        errors.append('native_source_map_identity')
    for item in mapping['ports']:
        if not re.fullmatch('[0-9a-f]{64}', item['source_sha256']):
            errors.append('source_hash_format')
        relative = Path(item['native'])
        if relative.is_absolute() or '..' in relative.parts or not (project/'runtime/nonzero_cloudops'/relative).is_file():
            errors.append('native_mapping_target')
    tests = lock.get('final_reference_test_result', {})
    if (tests.get('status'), tests.get('passed'), tests.get('failed'), tests.get('skipped')) != ('PASS', 1447, 0, 0):
        errors.append('final_reference_test_result')
    gates = lock.get('final_reference_gates_result', {})
    for gate in ('ruff', 'portable', 'p0', 'p1', 'b4', 'evidence_build', 'evidence_validate', 'secrets'):
        if gates.get(gate, {}).get('status') != 'PASS':
            errors.append('final_reference_gate:'+gate)
    return {'status': 'PASS' if not errors else 'FAIL', 'findings': errors,
            'source_reads': 0, 'git_commands': 0, 'source_sha': JUDGE}


def verify_wheel(wheel: Path) -> dict:
    with zipfile.ZipFile(wheel) as archive:
        names = archive.namelist()
        forbidden = [name for name in names if '/baseline/' in name or 'aioa_cloudops_agent' in name
                     or '/.git/' in name or (name.startswith('runtime/nonzero_cloudops/') and Path(name).name in MANIFESTS)]
        metadata = [name for name in names if name.endswith('.dist-info/METADATA')]
        if len(metadata) != 1:
            forbidden.append('SECOND_DISTRIBUTION_METADATA')
        elif 'Name: aioa-sparkhat\n' not in archive.read(metadata[0]).decode():
            forbidden.append('WRONG_CORE_DISTRIBUTION')
        for required in ('runtime/nonzero_cloudops/service.py', 'runtime/nonzero_cloudops/LICENSE-NONZERO.txt',
                         'runtime/main.py', 'runtime/critical_loop/service.py', 'runtime/evidence_review/engine.py'):
            if required not in names:
                forbidden.append('MISSING:'+required)
    return {'status': 'PASS' if not forbidden else 'FAIL', 'findings': forbidden,
            'sha256': hashlib.sha256(wheel.read_bytes()).hexdigest()}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project-root', type=Path, required=True)
    parser.add_argument('--wheel', type=Path)
    args = parser.parse_args(argv)
    project = args.project_root.resolve()
    module = inspect_module(project/'runtime/nonzero_cloudops')
    ownership = verify_ownership(project/'runtime')
    provenance = verify_provenance(project)
    packaging = tomllib.loads((project/'pyproject.toml').read_text())
    packaging_ok = (packaging['project']['name'] == 'aioa-sparkhat'
        and packaging['project']['requires-python'] == '>=3.11'
        and packaging['project']['optional-dependencies']['nonzero'] == ['pydantic==2.13.4', 'uuid6==2025.0.1'])
    for entries in packaging['tool']['setuptools'].get('package-data', {}).values():
        if any('baseline' in entry or 'aioa_cloudops_agent' in entry for entry in entries):
            packaging_ok = False
    wheel = verify_wheel(args.wheel) if args.wheel else None
    passed = module['status'] == provenance['status'] == 'PASS' and not ownership and packaging_ok
    passed = passed and (wheel is None or wheel['status'] == 'PASS')
    result = {'ONE_SYSTEM_STATIC_GATE': 'PASS' if passed else 'FAIL', **module,
        'CORE_OWNERSHIP': 'PASS' if not ownership else 'FAIL', 'ownership_findings': ownership,
        'PROVENANCE_LOCK': provenance, 'PACKAGING': 'PASS' if packaging_ok else 'FAIL', 'wheel': wheel}
    if passed:
        result.update({'BASELINE_IMPORTS': 0, 'RUNTIME_JURY_DEPENDENCY': 'NO',
            'RUNTIME_SANDBOX_DEPENDENCY': 'NO', 'SECOND_SERVER_REQUIRED': 'NO',
            'SECOND_CREDENTIAL_LAYER': 'NO', 'SECOND_PROVIDER_MANAGER': 'NO'})
    print(json.dumps(result, indent=2))
    return 0 if passed else 1


if __name__ == '__main__':
    raise SystemExit(main())
