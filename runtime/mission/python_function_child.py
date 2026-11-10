"""Untrusted normal-Python observation process, only inside the one broker."""
import importlib
import json
import os
import re
import runpy
import sys
from contextlib import redirect_stdout
from pathlib import Path


def require(value, code):
    if not value:
        raise ValueError(code)


def _require_sandbox():
    status = Path('/proc/self/status').read_text()
    require('NoNewPrivs:\t1' in status and 'Seccomp:\t2' in status
            and Path('/bootstrap').is_file()
            and os.statvfs('/inputs/function_child.py').f_flag & os.ST_RDONLY,
            'SANDBOX_ONLY_RECIPE')


def _function_domain(mode, index):
    legacy = {'mode': 'observe', 'profile': 'ISOLATED_PYTHON_FUNCTIONS_V1'}
    framework = {'mode': 'observe', 'profile': 'ISOLATED_PYTEST_FUNCTIONS_V1'}
    require(type(mode) is dict and mode in (legacy, framework)
            and type(index) is int and 0 <= index < (8 if mode == framework else 16), 'FUNCTION_CHILD_DOMAIN')
    if mode == framework:
        return {'root': '/work/oracle-project', 'profile': 'PYTEST_ORACLE_V1', 'index': index}
    return {'root': '/work/project', 'profile': 'FUNCTION_V1', 'index': None}


def _framework_args(nodes):
    require(type(nodes) is tuple and 1 <= len(nodes) <= 16
            and all(type(node) is str and 0 < len(node) <= 256 for node in nodes)
            and nodes == tuple(sorted(set(nodes))), 'PYTEST_CHILD_SELECTION')
    for node in nodes:
        name = node.split('::', 1)[0]
        require(re.fullmatch(r'tests/[A-Za-z0-9_./-]+\.py::[A-Za-z][A-Za-z0-9_]*'
                             r'(?:::[A-Za-z][A-Za-z0-9_]*){0,3}(?:\[[A-Za-z0-9_.:-]{1,64}\])?', node)
                and all(part not in ('', '.', '..') for part in name.split('/')),
                'PYTEST_CHILD_SELECTION')
    return ['-c', '/work/tests/pytest.ini', '--rootdir=/work/tests', '--confcutdir=/work/tests',
            '--import-mode=importlib', '--assert=plain', '--strict-config', '--strict-markers',
            '--capture=sys', '--basetemp=/tmp/pytest-framework/run',
            '-p', 'no:cacheprovider', '-p', 'no:terminal', *('/work/tests/' + node for node in nodes)]


def _check_pytest_environment(env):
    require(env.get('PYTEST_DISABLE_PLUGIN_AUTOLOAD') == '1'
            and 'PYTEST_ADDOPTS' not in env and 'PYTEST_PLUGINS' not in env, 'PYTEST_CHILD_ENV')


def _check_framework_origins(modules):
    expected = {'pytest': 'pytest/__init__.py', '_pytest': '_pytest/__init__.py', 'py': 'py.py',
                'pluggy': 'pluggy/__init__.py', 'iniconfig': 'iniconfig/__init__.py',
                'packaging': 'packaging/__init__.py', 'pygments': 'pygments/__init__.py'}
    require(type(modules) is dict and set(modules) == set(expected), 'PYTEST_CHILD_ORIGIN')
    for name, filename in expected.items():
        observed = getattr(modules[name], '__file__', None)
        require(type(observed) is str and observed == '/work/dependencies/' + filename, 'PYTEST_CHILD_ORIGIN')


class FrameworkRecorder:
    """Bounded untrusted guest events, never an assertion or approval oracle."""

    def __init__(self, expected):
        _framework_args(expected)
        self.expected, self.collected, self.events, self.invalid = expected, None, {}, False

    def demand(self, condition, code):
        if not condition:
            self.invalid = True
            raise ValueError(code)

    def pytest_collection_finish(self, session):
        nodes = [item.nodeid for item in session.items]
        self.demand(self.collected is None and all(type(node) is str for node in nodes)
                    and tuple(sorted(nodes)) == self.expected, 'PYTEST_CHILD_COLLECTION')
        self.collected = tuple(sorted(nodes))

    def pytest_runtest_logreport(self, report):
        node, phase, outcome = report.nodeid, report.when, report.outcome
        self.demand(type(node) is str and node in self.expected
                    and type(phase) is str and phase in ('setup', 'call', 'teardown')
                    and type(outcome) is str and outcome in ('passed', 'failed')
                    and not hasattr(report, 'wasxfail') and (node, phase) not in self.events,
                    'PYTEST_CHILD_EVENT')
        self.events[node, phase] = outcome

    def result(self, suite_digest, stage, exit_code):
        self.demand(not self.invalid and self.collected == self.expected
                    and type(exit_code) is int and exit_code in (0, 1), 'PYTEST_CHILD_COMPLETION')
        results = []
        for node in self.expected:
            events = {phase: self.events[node, phase] for phase in ('setup', 'call', 'teardown')
                      if (node, phase) in self.events}
            self.demand({'setup', 'teardown'} <= set(events)
                        and ('call' in events) == (events['setup'] == 'passed'), 'PYTEST_CHILD_COMPLETION')
            results.append({'node_id': node, 'outcome': 'PASS' if all(
                value == 'passed' for value in events.values()) else 'FAIL'})
        passed = all(item['outcome'] == 'PASS' for item in results)
        self.demand(exit_code == (0 if passed else 1), 'PYTEST_CHILD_EXIT')
        return {'schema': 'aioa.pytest-framework-observation.v1', 'suite_digest': suite_digest,
                'stage': stage, 'collected': list(self.collected), 'results': results, 'exit_code': exit_code}


def run_pytest():
    _require_sandbox()
    require(sys.argv == [sys.argv[0], 'pytest'], 'PYTEST_CHILD_MODE')
    require(json.loads(Path('/inputs/mode.json').read_bytes())
            == {'mode': 'observe', 'profile': 'ISOLATED_PYTEST_FUNCTIONS_V1'}, 'PYTEST_CHILD_MODE')
    _check_pytest_environment(os.environ)
    roots = json.loads(Path('/inputs/imports.json').read_bytes())
    require(type(roots) is list and 1 <= len(roots) <= 4
            and all(type(root) is str and (not root or re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_/-]{0,127}', root))
                    and '..' not in root.split('/') for root in roots), 'FUNCTION_IMPORT_ROOTS')
    policy = runpy.run_path('/inputs/test_policy.py')
    suite = policy['PytestSuite'].from_manifest(Path('/inputs/pytest-suite.json').read_bytes())
    context = json.loads(Path('/inputs/context.json').read_bytes())
    nodes = suite.node_ids(context['stage'])
    isolation = runpy.run_path('/inputs/function_policy.py')
    isolation['restrict_function_process'](profile='PYTEST_FRAMEWORK_V1')
    sys.path[:0] = ['/work/dependencies']
    modules = {name: importlib.import_module(name) for name in (
        'pytest', '_pytest', 'py', 'pluggy', 'iniconfig', 'packaging', 'pygments')}
    _check_framework_origins(modules)
    sys.path[1:1] = [str(Path('/work/project', root)) for root in roots]
    recorder = FrameworkRecorder(nodes)
    with redirect_stdout(sys.stderr):
        exit_code = int(modules['pytest'].main(_framework_args(nodes), plugins=[recorder]))
    result = recorder.result(suite.digest, context['stage'], exit_code)
    # Parent and Core both recheck these advisory facts; host expected answers
    # never enter this process, and only a separate fresh child supplies calls.
    raw = json.dumps(result, sort_keys=True, separators=(',', ':'), ensure_ascii=True, allow_nan=False)
    require(len(raw.encode()) + 1 <= 8192, 'PYTEST_CHILD_OUTPUT_BOUND')
    print(raw, flush=True)


def run():
    _require_sandbox()
    require(len(sys.argv) == 2 and re.fullmatch(r'[0-9]|1[0-5]', sys.argv[1]), 'FUNCTION_CALL_INDEX')
    index = int(sys.argv[1])
    domain = _function_domain(json.loads(Path('/inputs/mode.json').read_bytes()), index)
    calls = json.loads(Path('/inputs/calls.json').read_bytes())
    roots = json.loads(Path('/inputs/imports.json').read_bytes())
    require(type(calls) is list and index < len(calls), 'FUNCTION_CALL_INDEX')
    call = calls[index]
    require(type(roots) is list and 1 <= len(roots) <= 4
            and all(type(root) is str and (not root or re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_/-]{0,127}', root))
                    and '..' not in root.split('/') for root in roots), 'FUNCTION_IMPORT_ROOTS')
    require(type(call) is dict and set(call) == {'case_id', 'module', 'function', 'arguments'}
            and re.fullmatch(r'[A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z][A-Za-z0-9_]*){0,7}', call['module'])
            and re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{0,63}', call['function'])
            and type(call['arguments']) is list, 'FUNCTION_CALL_SCHEMA')
    boundary = runpy.run_path('/inputs/failure_boundary.py')
    isolation = runpy.run_path('/inputs/function_policy.py')
    if domain['profile'] == 'FUNCTION_V1':
        isolation['restrict_function_process']()
    else:
        isolation['restrict_function_process'](profile=domain['profile'], index=domain['index'])
    project_roots = [str(Path(domain['root'], root)) for root in roots]
    sys.path[:0] = (project_roots + ['/work/dependencies'] if domain['profile'] == 'FUNCTION_V1'
                    else ['/work/dependencies'] + project_roots)
    try:
        with boundary['failure_boundary']('FUNCTION_CANDIDATE_FAILED'), redirect_stdout(sys.stderr):
            module = importlib.import_module(call['module'])
            function = getattr(module, call['function'])
            result = function(*call['arguments'])
            # JSON serialization belongs to this untrusted process too. Core accepts
            # only a bounded value checked against its independent expected answer.
            raw = json.dumps({'schema': 'aioa.python-function-return.v1', 'kind': 'returned', 'value': result},
                             sort_keys=True, separators=(',', ':'), ensure_ascii=domain['profile'] != 'FUNCTION_V1', allow_nan=False)
    except (ValueError, boundary['RepairBoundaryError']):
        raw = '{"schema":"aioa.python-function-return.v1","kind":"raised","type":"CandidateError"}'
    require(len(raw.encode()) + (0 if domain['profile'] == 'FUNCTION_V1' else 1) <= 8192,
            'FUNCTION_RESULT_BOUND')
    print(raw, flush=True)


if __name__ == '__main__':
    if len(sys.argv) == 2 and sys.argv[1] == 'pytest':
        run_pytest()
    else:
        run()
