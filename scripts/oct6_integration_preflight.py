#!/usr/bin/env python3
"""Offline, read-only integration inventory. No fetch, tests or Git mutations."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

FROZEN_MAIN = 'd26266e54ee940d7ada30aa02783dc697618a72c'
EVIDENCE = [
    'evidence/personal_ai_vertical_slice/manifest_final_20261003T135440Z.json',
    'evidence/cloud_activation/live_smoke_20261003T130702Z.json',
    'evidence/personal_ai_vertical_slice/fixture_demo_20261003T132724Z.json',
]
TEST_COMMANDS = [
    'python3 -m unittest tests.test_oct6_integration_preflight -v',
    'PYTHONPATH=runtime:tests:. python3 -m unittest tests.test_nebius_provider tests.test_nebius_routing tests.test_nebius_safe_diagnostics -v',
    'python3 scripts/run_prompt03_regressions.py',
    'python3 scripts/check_changed_secrets.py --base main',
]


class PreflightError(RuntimeError):
    pass


def inspect(root: Path, *, expected_main: str = FROZEN_MAIN,
            evidence: list[str] | None = None, expected_origin_main: str | None = None,
            target_sha: str | None = None) -> dict:
    """Read local refs only; expected_main is an immutable SHA, never a Git option."""
    if any(value is not None and not re.fullmatch(r'[0-9a-f]{40}', value)
           for value in (expected_main, expected_origin_main, target_sha)):
        raise ValueError('expected_main must be a full lowercase commit SHA')
    root = root.resolve()
    env = dict(os.environ, GIT_OPTIONAL_LOCKS='0', GIT_TERMINAL_PROMPT='0')

    def git(*args: str) -> str:
        try:
            result = subprocess.run(['git', '-C', str(root), *args], env=env,
                                    capture_output=True, check=True, timeout=15)
        except (OSError, subprocess.SubprocessError) as error:
            raise PreflightError('LOCAL_GIT_READ_FAILED') from error
        return result.stdout.decode('utf-8', 'replace').rstrip('\n')

    branch = git('branch', '--show-current')
    head, main, origin = [git('rev-parse', '--verify', ref) for ref in
                          ('HEAD^{commit}', 'refs/heads/main^{commit}', 'refs/remotes/origin/main^{commit}')]
    expected_origin_main = expected_origin_main or expected_main
    target = git('rev-parse', '--verify', f'{target_sha}^{{commit}}') if target_sha else main
    base = git('merge-base', target, head)
    source_unique, main_unique = map(int, git('rev-list', '--left-right', '--count', f'{head}...{target}').split())
    dirty = bool(git('status', '--porcelain=v1', '-z', '--untracked-files=all'))
    source_files = sorted(filter(None, git('diff', '--name-only', '-z', base, head).split('\0')))
    target_files = sorted(filter(None, git('diff', '--name-only', '-z', base, target).split('\0')))
    commits = []
    for sha in git('rev-list', '--reverse', f'{target}..{head}').splitlines():
        parents = git('rev-list', '--parents', '-n', '1', sha).split()[1:]
        # First-parent merge diff includes changes hidden by default merge log formatting.
        files = sorted(filter(None, git('diff', '--name-only', '-z', parents[0], sha).split('\0')))
        commits.append({'sha': sha, 'subject': git('show', '-s', '--format=%s', sha),
                        'parents': parents, 'files': files, 'merge': len(parents) > 1})
    checks = []
    for relative in EVIDENCE if evidence is None else evidence:
        path = root / relative
        valid = path.is_file() and not path.is_symlink() and path.resolve().is_relative_to(root)
        checks.append({'path': relative, 'valid': valid,
                       'sha256': hashlib.sha256(path.read_bytes()).hexdigest() if valid else None})
    blockers = []
    if branch != 'nebius-personal-ai':
        blockers.append('WRONG_BRANCH')
    if main != expected_main:
        blockers.append('MAIN_CHANGED')
    if origin != expected_origin_main:
        blockers.append('ORIGIN_MAIN_CHANGED')
    if dirty:
        blockers.append('DIRTY_WORKTREE')
    if any(not row['valid'] for row in checks):
        blockers.append('MISSING_EVIDENCE')
    overlap = sorted(set(source_files) & set(target_files))
    return {'schema': 'aioa.oct6-preflight.v1', 'status': 'BLOCKED' if blockers else 'PASS',
            'scope': 'LOCAL_READ_ONLY_NO_INTEGRATION_AUTHORIZATION', 'branch': branch,
            'head': head, 'main': main, 'origin_main': origin, 'expected_main': expected_main,
            'expected_origin_main': expected_origin_main, 'target_sha': target, 'merge_base': base, 'dirty': dirty, 'unique_commits': commits,
            'source_changed_files': source_files, 'target_changed_files': target_files,
            'changed_file_overlap': overlap, 'divergence': {'source_unique': source_unique, 'main_unique': main_unique},
            'evidence': checks, 'selected_test_commands': TEST_COMMANDS,
            'blockers': blockers,
            'warning': 'Zero textual overlap against frozen main does not establish semantic compatibility with the future base.'}


def render_human(report: dict) -> str:
    return '\n'.join([
        f"Preflight: {report['status']}", f"Branch: {report['branch']}",
        f"HEAD: {report['head']}", f"main: {report['main']}",
        f"origin/main: {report['origin_main']}", f"Merge-base: {report['merge_base']}", f"Target: {report['target_sha']}",
        f"Dirty: {report['dirty']}", f"Divergence: {report['divergence']}",
        f"Unique commits: {len(report['unique_commits'])}",
        f"Changed-file overlap: {report['changed_file_overlap']}",
        f"Evidence: {sum(row['valid'] for row in report['evidence'])}/{len(report['evidence'])}",
        f"Blockers: {report['blockers']}", report['warning'],
        'Selected test commands (not executed):', *report['selected_test_commands'],
    ])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--expected-main', default=FROZEN_MAIN,
                        help='Full captured target SHA; post-unlock must be explicitly supplied')
    parser.add_argument('--expected-origin-main', help='Captured origin/main full SHA; defaults to expected-main')
    parser.add_argument('--target-sha', help='Captured immutable active target SHA for divergence/overlap')
    parser.add_argument('--format', choices=('json', 'human', 'both'), default='json')
    args = parser.parse_args()
    try:
        report = inspect(args.root, expected_main=args.expected_main,
                         expected_origin_main=args.expected_origin_main, target_sha=args.target_sha)
    except (ValueError, PreflightError):
        print(json.dumps({'status': 'BLOCKED', 'category': 'INVALID_INPUT_OR_LOCAL_GIT_READ'}))
        return 2
    if args.format in ('human', 'both'):
        print(render_human(report))
    if args.format in ('json', 'both'):
        print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report['status'] == 'PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
