"""Build and test wheel/sdist imports outside the source import path.

Run separately from runtime unit tests: this acceptance test creates fresh build
and installation directories. --isolate-filesystem additionally hides checkouts
with bubblewrap for local release certification. CI always uses isolated Python
and checks that imports come from each new installation, without Textual.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path


def clean_environment():
    return {
        'PATH': '/usr/bin:/bin', 'LANG': 'C.UTF-8', 'LC_ALL': 'C.UTF-8',
        'PYTHONNOUSERSITE': '1', 'PYTHONDONTWRITEBYTECODE': '1',
        'PIP_CONFIG_FILE': '/dev/null', 'PIP_DISABLE_PIP_VERSION_CHECK': '1',
        'PIP_NO_CACHE_DIR': '1', 'GIT_CONFIG_NOSYSTEM': '1',
        'GIT_CONFIG_GLOBAL': '/dev/null', 'GIT_OPTIONAL_LOCKS': '0',
    }


def execute(command, *, cwd, log):
    result = subprocess.run(
        list(map(str, command)), cwd=cwd, env=clean_environment(),
        stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT, text=True, timeout=300,
    )
    log.write_text(result.stdout, encoding='utf-8')
    if result.returncode:
        raise RuntimeError(f'Packaging acceptance failed; see {log}:\n{result.stdout}')
    return result.stdout


def build(kind, source, destination, log):
    destination.mkdir()
    code = f'from setuptools.build_meta import build_{kind}; import sys; build_{kind}(sys.argv[1])'
    execute([sys.executable, '-B', '-c', code, destination], cwd=source, log=log)
    suffix = '*.whl' if kind == 'wheel' else '*.tar.gz'
    artifact, = destination.glob(suffix)
    return artifact


def import_check(venv, source, staging, *, isolate_filesystem, log):
    command = []
    if isolate_filesystem:
        if shutil.which('bwrap') is None:
            raise RuntimeError('bubblewrap is required for filesystem isolation')
        command = [
            'bwrap', '--die-with-parent', '--new-session', '--unshare-net',
            '--ro-bind', '/', '/', '--tmpfs', '/home', '--tmpfs', '/media',
            '--tmpfs', '/run', '--tmpfs', '/tmp', '--dev', '/dev', '--proc', '/proc',
            '--ro-bind', str(Path(sys.base_prefix).resolve()), str(Path(sys.base_prefix).resolve()),
            '--ro-bind', str(venv), str(venv), '--chdir', '/tmp', '--',
        ]
    code = '''
import importlib.util, json, os, pathlib, sys
venv, source, staging = map(pathlib.Path, sys.argv[1:4])
filesystem_isolated = sys.argv[4] == 'yes'
assert 'PYTHONPATH' not in os.environ
assert importlib.util.find_spec('textual') is None
assert not any(pathlib.Path(p).resolve().is_relative_to(source) for p in sys.path if p)
if filesystem_isolated:
    assert not source.exists(), 'checkout is accessible'
    assert not staging.exists(), 'build source is accessible'
    assert not (venv.parent / 'sdist-source').exists(), 'sdist source is accessible'
from tui import assistant
assert callable(assistant.operator_request)
assert pathlib.Path(assistant.__file__).resolve().is_relative_to(venv)
assert 'site-packages' in assistant.__file__
assert not any(name == 'textual' or name.startswith('textual.') for name in sys.modules)
print(json.dumps({'STATUS': 'PASS', 'python': sys.version.split()[0],
    'adapter': assistant.__file__, 'Textual_installed': False,
    'PYTHONPATH_present': False, 'source_on_import_path': False,
    'source_checkout_hidden': filesystem_isolated}))
'''
    command += [venv / 'bin/python', '-I', '-B', '-c', code, venv, source,
                staging, 'yes' if isolate_filesystem else 'no']
    return json.loads(execute(command, cwd=venv, log=log))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--isolate-filesystem', action='store_true')
    args = parser.parse_args()
    source, output = args.source.resolve(), args.output.resolve()
    if output.is_relative_to(source):
        raise ValueError('Acceptance output must be outside the checkout')
    output.mkdir(parents=True)
    staging = output / 'build-source'
    staging.mkdir()
    tracked = execute(['git', 'ls-files', '-z'], cwd=source, log=output / 'tracked-files.log').split('\0')
    for name in filter(None, tracked):
        path = source / name
        if not path.is_file() or path.is_symlink():
            raise ValueError(f'Expected a regular tracked source file: {name}')
        target = staging / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
    wheel = build('wheel', staging, output / 'wheel', output / 'wheel-build.log')
    sdist = build('sdist', staging, output / 'sdist', output / 'sdist-build.log')
    extracted = output / 'sdist-source'
    extracted.mkdir()
    with tarfile.open(sdist) as archive:
        archive.extractall(extracted, filter='data')
    sdist_source, = extracted.iterdir()
    sdist_wheel = build('wheel', sdist_source, output / 'sdist-wheel', output / 'sdist-wheel-build.log')
    results = []
    for kind, artifact in [('wheel', wheel), ('sdist', sdist_wheel)]:
        venv = output / ('installed-' + kind)
        execute([sys.executable, '-B', '-m', 'venv', '--without-pip', venv], cwd=output, log=output / (kind + '-venv.log'))
        execute([sys.executable, '-B', '-m', 'pip', '--isolated', '--python',
                 venv / 'bin/python', 'install', '--no-index', '--no-deps',
                 '--no-compile', artifact], cwd=output, log=output / (kind + '-install.log'))
        result = import_check(venv, source, staging, isolate_filesystem=args.isolate_filesystem,
                              log=output / (kind + '-import.log'))
        result.update({'distribution': kind, 'wheel': str(artifact),
                       'wheel_sha256': hashlib.sha256(artifact.read_bytes()).hexdigest()})
        results.append(result)
    record = {'STATUS': 'PASS', 'results': results, 'sdist': str(sdist),
              'sdist_sha256': hashlib.sha256(sdist.read_bytes()).hexdigest()}
    (output / 'result.json').write_text(json.dumps(record, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(record))


if __name__ == '__main__':
    main()
