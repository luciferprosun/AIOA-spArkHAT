"""Pure pinned pytest data and advisory facts for host and existing guest worker.

No imports of Core, project code, pytest, package acquisition or execution.
The host-held independent oracle remains required for validation authority.
"""
import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path


def _require(condition, reason):
    if not condition:
        raise ValueError(reason)


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def _hash(raw):
    return hashlib.sha256(raw).hexdigest()


def _json_bytes(raw):
    def pairs(items):
        value = {}
        for key, item in items:
            _require(key not in value, 'PYTEST_SUITE_DUPLICATE_KEY')
            value[key] = item
        return value
    _require(type(raw) is bytes and 0 < len(raw) <= 524288, 'PYTEST_SUITE_MANIFEST_BOUND')
    return json.loads(raw.decode('utf-8'), object_pairs_hook=pairs,
                      parse_constant=lambda _: _require(False, 'PYTEST_SUITE_JSON_CONSTANT'))


_PYTEST_RESERVED_IMPORTS = frozenset({'pytest', '_pytest', 'py', 'pluggy',
                                      'iniconfig', 'packaging', 'pygments'})
_PYTEST_CONFIGURATION = '[pytest]\naddopts =\n'


@dataclass(frozen=True, slots=True)
class PytestSuite:
    """Inert pinned tests and advisory facts, never a substitute for the oracle."""

    files: tuple = field(repr=False)
    stages: tuple

    def __post_init__(self):
        TEST_STAGES = ('FAST_TESTS', 'TARGETED_TESTS', 'FINAL_TESTS')

        _require(type(self.files) is tuple and 1 <= len(self.files) <= 32
                 and all(type(row) is tuple and len(row) == 2 for row in self.files),
                 'PYTEST_TEST_FILES')
        names, seen, total = [], set(), 0
        for name, text in self.files:
            _require(type(name) is str and len(name) <= 192
                     and re.fullmatch(r'tests/[A-Za-z0-9_./-]+', name)
                     and all(part not in ('', '.', '..') for part in name.split('/'))
                     and len(name.split('/')) <= 16 and name.endswith(('.py', '.json', '.txt')),
                     'PYTEST_TEST_PATH')
            parts = name.split('/')
            _require(not any(Path(part).stem in _PYTEST_RESERVED_IMPORTS
                             or part.endswith('.data') for part in parts)
                     and parts[-1] not in ('setup.py', 'postinstall.py', 'sitecustomize.py', 'usercustomize.py'),
                     'PYTEST_TEST_IMPORT_COLLISION')
            folded = name.casefold()
            _require(folded not in seen
                     and not any(folded.startswith(old + '/') or old.startswith(folded + '/') for old in seen),
                     'PYTEST_TEST_COLLISION')
            seen.add(folded)
            names.append(name)
            _require(type(text) is str and '\0' not in text and len(text.encode('utf-8')) <= 65536,
                     'PYTEST_TEST_TEXT')
            total += len(text.encode('utf-8'))
        _require(tuple(names) == tuple(sorted(names)) and total <= 262144, 'PYTEST_TEST_BOUND')
        _require(type(self.stages) is tuple and len(self.stages) == 3
                 and all(type(row) is tuple and len(row) == 2 and type(row[0]) is str
                         for row in self.stages)
                 and tuple(row[0] for row in self.stages) == TEST_STAGES, 'PYTEST_TEST_STAGES')
        for _stage, nodes in self.stages:
            _require(type(nodes) is tuple and 1 <= len(nodes) <= 16
                     and all(type(node) is str and len(node) <= 256 for node in nodes),
                     'PYTEST_TEST_SELECTION')
            _require(nodes == tuple(sorted(set(nodes))), 'PYTEST_TEST_SELECTION')
            for node in nodes:
                _require(re.fullmatch(r'tests/[A-Za-z0-9_./-]+\.py::[A-Za-z][A-Za-z0-9_]*'
                                     r'(?:::[A-Za-z][A-Za-z0-9_]*){0,3}(?:\[[A-Za-z0-9_.:-]{1,64}\])?', node)
                         and node.split('::', 1)[0] in names
                         and Path(node.split('::', 1)[0]).name.startswith('test_'),
                         'PYTEST_TEST_NODE')
        _require(set(self.stages[0][1]) | set(self.stages[1][1]) <= set(self.stages[2][1]),
                 'PYTEST_FINAL_SELECTION_WEAKENED')
        _require(len(_json(self._payload())) <= 524288, 'PYTEST_SUITE_MANIFEST_BOUND')

    @property
    def authority(self):
        return 'NONE'

    def _payload(self):
        return {'schema': 'aioa.pytest-suite.v1', 'authority': 'NONE', 'network': 'OFF',
                'plugin_autoload': 'OFF', 'skip_xfail': 'DENY', 'configuration': _PYTEST_CONFIGURATION,
                'files': [{'path': name, 'text': text} for name, text in self.files],
                'stages': [{'stage': stage, 'node_ids': list(nodes)} for stage, nodes in self.stages]}

    def manifest_bytes(self):
        self.__post_init__()
        return _json(self._payload())

    @property
    def digest(self):
        return _hash(self.manifest_bytes())

    @classmethod
    def from_manifest(cls, raw):
        _require(type(raw) is bytes and 0 < len(raw) <= 524288, 'PYTEST_SUITE_MANIFEST_BOUND')
        try:
            row = _json_bytes(raw)
        except RecursionError:
            raise ValueError('PYTEST_SUITE_MANIFEST_BOUND') from None
        _require(type(row) is dict and set(row) == {
            'schema', 'authority', 'network', 'plugin_autoload', 'skip_xfail', 'configuration', 'files', 'stages'}
                 and row['schema'] == 'aioa.pytest-suite.v1' and row['authority'] == 'NONE'
                 and row['network'] == 'OFF' and row['plugin_autoload'] == 'OFF'
                 and row['skip_xfail'] == 'DENY' and row['configuration'] == _PYTEST_CONFIGURATION,
                 'PYTEST_SUITE_MANIFEST_SCHEMA')
        _require(type(row['files']) is list and len(row['files']) <= 32
                 and all(type(item) is dict and set(item) == {'path', 'text'} for item in row['files'])
                 and type(row['stages']) is list and len(row['stages']) == 3
                 and all(type(item) is dict and set(item) == {'stage', 'node_ids'}
                         and type(item['node_ids']) is list for item in row['stages']),
                 'PYTEST_SUITE_MANIFEST_SCHEMA')
        suite = cls(tuple((item['path'], item['text']) for item in row['files']),
                    tuple((item['stage'], tuple(item['node_ids'])) for item in row['stages']))
        _require(suite.manifest_bytes() == raw, 'PYTEST_SUITE_MANIFEST_CANONICAL')
        return suite

    def node_ids(self, stage):
        self.__post_init__()
        _require(type(stage) is str and stage in dict(self.stages), 'PYTEST_TEST_STAGE')
        return dict(self.stages)[stage]

    def workspace_archive_bytes(self):
        self.__post_init__()
        files = (('pytest.ini', _PYTEST_CONFIGURATION), *self.files)
        return _json({'schema': 'aioa.validation-workspace.v1',
                      'files': [{'path': name, 'mode': 0o600, 'text': text} for name, text in files]})

    def check_observation(self, value, stage):
        """A well-formed framework pass remains only an advisory guest fact."""
        expected = list(self.node_ids(stage))
        _require(type(value) is dict and set(value) == {
            'schema', 'suite_digest', 'stage', 'collected', 'results', 'exit_code'}
                 and type(value['schema']) is str and value['schema'] == 'aioa.pytest-framework-observation.v1'
                 and type(value['suite_digest']) is str and value['suite_digest'] == self.digest
                 and type(value['stage']) is str and value['stage'] == stage
                 and type(value['exit_code']) is int and value['exit_code'] in (0, 1),
                 'PYTEST_FRAMEWORK_BINDING')
        _require(type(value['collected']) is list
                 and all(type(node) is str for node in value['collected'])
                 and value['collected'] == expected and type(value['results']) is list
                 and len(value['results']) == len(expected), 'PYTEST_FRAMEWORK_SELECTION')
        passed = True
        for node, result in zip(expected, value['results'], strict=True):
            _require(type(result) is dict and set(result) == {'node_id', 'outcome'}
                     and type(result['node_id']) is str and result['node_id'] == node
                     and type(result['outcome']) is str and result['outcome'] in ('PASS', 'FAIL'),
                     'PYTEST_FRAMEWORK_RESULT')
            passed = passed and result['outcome'] == 'PASS'
        _require(value['exit_code'] == (0 if passed else 1), 'PYTEST_FRAMEWORK_EXIT')
        return passed
