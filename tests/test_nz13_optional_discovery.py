"""Discovery without the optional domain extra must skip, never import-fail."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class OptionalDomainDiscoveryTests(unittest.TestCase):
    def test_cloudops_behavior_module_is_discoverable_without_optional_dependencies(self):
        import runtime

        project = Path(runtime.__file__).resolve().parents[1]
        tests = Path(__file__).resolve().parent
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            # Expose only project packages, excluding site-packages and their
            # dist-info even when this test is run against an installed wheel.
            for name in ('runtime', 'lab'):
                if (project / name).is_dir():
                    (root / name).symlink_to(project / name, target_is_directory=True)
            code = r'''
import json,sys,unittest
sys.path[:0]=sys.argv[1:3]
import runtime
from nonzero_cloudops import module_descriptor
assert module_descriptor()['available'] is False
assert 'pydantic' not in sys.modules and 'uuid6' not in sys.modules
loader=unittest.TestLoader()
suite=loader.discover(sys.argv[2],pattern='test_nz13_cloudops_contracts.py')
result=unittest.TestResult();suite.run(result)
record={'cases':result.testsRun,'error':len(result.errors),'fail':len(result.failures),
        'skip':len(result.skipped),'loader_errors':len(loader.errors)}
print(json.dumps(record))
assert record['cases']>1 and record['skip']==record['cases']
assert record['error']==record['fail']==record['loader_errors']==0
assert 'pydantic' not in sys.modules and 'uuid6' not in sys.modules
'''
            completed = subprocess.run(
                [sys.executable, '-I', '-S', '-B', '-c', code, str(root), str(tests)],
                cwd=root, env={'PATH': os.defpath, 'HOME': str(root), 'TMPDIR': str(root),
                               'LANG': 'C.UTF-8', 'PYTHONDONTWRITEBYTECODE': '1'},
                capture_output=True, text=True, timeout=30, check=False,
            )
            self.assertEqual(completed.returncode, 0,
                             'No-extra discovery must skip domain cases without an import error')
            record = json.loads(completed.stdout)
            self.assertGreater(record['cases'], 1)
            self.assertEqual(record['cases'], record['skip'])
            self.assertEqual((record['error'], record['fail'], record['loader_errors']), (0, 0, 0))
