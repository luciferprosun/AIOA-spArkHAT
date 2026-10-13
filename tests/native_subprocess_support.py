"""Pinned local fixtures for fresh native interpreters; no inherited import paths."""
import hashlib
import json
from pathlib import Path
import sys


FIXTURES = ('test_dual_governor', 'mission_completion_support', 'nv03_support')
_BOOTSTRAP = r'''
import hashlib
import importlib
import importlib.util
import json
from pathlib import Path
import sys

pinned = json.loads(sys.argv.pop(1))
root, tests = Path(pinned['root']), Path(pinned['tests'])
if root != root.resolve() or tests != root / 'tests' or tests != tests.resolve():
    raise ValueError('NATIVE_SOURCE_PATH_DRIFT')
sys.path[:0] = [str(tests), str(root)]
runtime_spec = importlib.util.find_spec('runtime')
if runtime_spec is None or runtime_spec.origin != str(root / 'runtime' / '__init__.py'):
    raise ValueError('NATIVE_RUNTIME_ORIGIN_DRIFT')
import runtime  # Its existing bootstrap binds legacy imports to this runtime directory.

def verify(name, origin):
    path = tests / (name + '.py')
    if path.is_symlink() or path.resolve() != path or origin != str(path):
        raise ValueError('NATIVE_FIXTURE_ORIGIN_DRIFT')
    if hashlib.sha256(path.read_bytes()).hexdigest() != pinned['fixtures'][name]:
        raise ValueError('NATIVE_FIXTURE_BYTES_DRIFT')

for name in pinned['fixtures']:
    spec = importlib.util.find_spec(name)
    verify(name, None if spec is None else spec.origin)
for name in pinned['fixtures']:
    module = importlib.import_module(name)
    verify(name, module.__spec__.origin)
    verify(name, module.__file__)
exec(compile(pinned['code'], '<native-restart-probe>', 'exec'), {'__name__': '__main__'})
'''


def native_command(test_file, code, *arguments):
    """Keep python -c argv semantics and bind only this repository's test fixtures."""
    tests = Path(__file__).resolve().parent
    if Path(test_file).resolve().parent != tests:
        raise ValueError('NATIVE_CALLER_PATH_DRIFT')
    fixtures = {}
    for name in FIXTURES:
        path = tests / (name + '.py')
        if path.is_symlink() or path.resolve() != path:
            raise ValueError('NATIVE_FIXTURE_ORIGIN_DRIFT')
        fixtures[name] = hashlib.sha256(path.read_bytes()).hexdigest()
    pinned = {'root': str(tests.parent), 'tests': str(tests),
              'fixtures': fixtures, 'code': code}
    return [sys.executable, '-I', '-B', '-c', _BOOTSTRAP,
            json.dumps(pinned), *map(str, arguments)]
