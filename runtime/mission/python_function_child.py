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


def run():
    status = Path('/proc/self/status').read_text()
    require('NoNewPrivs:\t1' in status and 'Seccomp:\t2' in status
            and Path('/bootstrap').is_file()
            and os.statvfs('/inputs/function_child.py').f_flag & os.ST_RDONLY,
            'SANDBOX_ONLY_RECIPE')
    require(len(sys.argv) == 2 and re.fullmatch(r'[0-9]|1[0-5]', sys.argv[1]), 'FUNCTION_CALL_INDEX')
    calls = json.loads(Path('/inputs/calls.json').read_bytes())
    roots = json.loads(Path('/inputs/imports.json').read_bytes())
    call = calls[int(sys.argv[1])]
    require(type(roots) is list and 1 <= len(roots) <= 4
            and all(type(root) is str and (not root or re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_/-]{0,127}', root))
                    and '..' not in root.split('/') for root in roots), 'FUNCTION_IMPORT_ROOTS')
    require(type(call) is dict and set(call) == {'case_id', 'module', 'function', 'arguments'}
            and re.fullmatch(r'[A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z][A-Za-z0-9_]*){0,7}', call['module'])
            and re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{0,63}', call['function'])
            and type(call['arguments']) is list, 'FUNCTION_CALL_SCHEMA')
    boundary = runpy.run_path('/inputs/failure_boundary.py')
    isolation = runpy.run_path('/inputs/function_policy.py')
    isolation['restrict_function_process']()
    sys.path[:0] = [str(Path('/work/project', root)) for root in roots] + ['/work/dependencies']
    try:
        with boundary['failure_boundary']('FUNCTION_CANDIDATE_FAILED'), redirect_stdout(sys.stderr):
            module = importlib.import_module(call['module'])
            function = getattr(module, call['function'])
            result = function(*call['arguments'])
            # JSON serialization belongs to this untrusted process too. Core accepts
            # only a bounded value checked against its independent expected answer.
            raw = json.dumps({'schema': 'aioa.python-function-return.v1', 'kind': 'returned', 'value': result},
                             sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False)
    except (ValueError, boundary['RepairBoundaryError']):
        raw = '{"schema":"aioa.python-function-return.v1","kind":"raised","type":"CandidateError"}'
    require(len(raw.encode()) <= 8192, 'FUNCTION_RESULT_BOUND')
    print(raw, flush=True)


if __name__ == '__main__':
    run()
