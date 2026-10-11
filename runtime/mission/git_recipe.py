"""Inert plans for one synthetic Git fixture; existing Core/U06 owns effects."""
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re

GIT_BINARY = '/lib/git-core/git'
GIT_SHA256 = '2a8c18fbf43da9f692d75474c72bea9dfd796c260b0f3dfe456376abc3bbd668'
BASE_BRANCH = 'fixture/base'
BASE_MESSAGE = b'U09 offline base fixture\n'
COMMIT_MESSAGE = b'U09 offline fixture commit\n'
IDENT = b'AIOA Offline Fixture <fixture@example.invalid> 946684800 +0000'


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def git_object(kind, data):
    # SHA1 is Git object identity only; canonical plan/profile authority uses SHA256.
    return hashlib.sha1(kind.encode() + b' ' + str(len(data)).encode() + b'\0' + data).hexdigest()


def objects(content, message, parent=None):
    blob = git_object('blob', content)
    source_tree = git_object('tree', b'100644 app.py\0' + bytes.fromhex(blob))
    tree = git_object('tree', b'40000 src\0' + bytes.fromhex(source_tree))
    commit = b'tree ' + tree.encode() + b'\n'
    if parent is not None:
        commit += b'parent ' + parent.encode() + b'\n'
    commit += b'author ' + IDENT + b'\ncommitter ' + IDENT + b'\n\n' + message
    return {'blob': blob, 'tree': tree, 'commit': git_object('commit', commit)}


def validate_ref(value):
    require(type(value) is str and re.fullmatch(r'synthetic:[A-Za-z0-9][A-Za-z0-9_-]{0,47}', value),
            'SYNTHETIC_REPOSITORY_REQUIRED')


def validate_content(value):
    require(type(value) is bytes and re.fullmatch(rb'value=-?[0-9]{1,6}\n', value), 'FIXED_GIT_SOURCE_REQUIRED')
    number = int(value[6:-1])
    require(value == b'value=' + str(number).encode() + b'\n', 'FIXED_GIT_SOURCE_REQUIRED')


@dataclass(frozen=True, slots=True)
class SyntheticGitSeed:
    repo_ref: str
    revision: int
    content: bytes
    branch: str = BASE_BRANCH

    def __post_init__(self):
        validate_ref(self.repo_ref); validate_content(self.content)
        require(type(self.revision) is int and self.revision == 1 and self.branch == BASE_BRANCH,
                'INVALID_SYNTHETIC_GIT_SEED')


@dataclass(frozen=True, slots=True)
class SyntheticGitPlan:
    repo_ref: str
    expected_revision: int
    base: bytes
    replacement: bytes
    branch: str

    def __post_init__(self):
        validate_ref(self.repo_ref); validate_content(self.base); validate_content(self.replacement)
        require(type(self.expected_revision) is int and self.expected_revision == 1, 'INVALID_GIT_REVISION')
        require(type(self.branch) is str and re.fullmatch(r'fixture/approved-[A-Za-z0-9][A-Za-z0-9-]{0,31}', self.branch),
                'UNAPPROVED_GIT_BRANCH')
        require(self.base != self.replacement, 'EMPTY_GIT_CHANGE')

    @property
    def base_head(self):
        return objects(self.base, BASE_MESSAGE)['commit']

    @property
    def commit_head(self):
        return objects(self.replacement, COMMIT_MESSAGE, self.base_head)['commit']

    def plan_bytes(self):
        return canonical({'schema': 'aioa.synthetic-git-plan.v1', 'repo_ref': self.repo_ref,
            'expected_revision': self.expected_revision, 'base_branch': BASE_BRANCH, 'branch': self.branch,
            'base_sha256': sha256(self.base), 'source_sha256': sha256(self.replacement),
            'base_head': self.base_head, 'commit_head': self.commit_head,
            'diff_sha256': sha256(self.diff_bytes()), 'git_sha256': GIT_SHA256})

    @property
    def digest(self):
        return sha256(self.plan_bytes())

    @property
    def target_fingerprint(self):
        return 'sha256:' + sha256(canonical({'repo_ref': self.repo_ref, 'revision': self.expected_revision,
            'branch': BASE_BRANCH, 'head': self.base_head, 'source_sha256': sha256(self.base)}))

    def diff_bytes(self):
        old, new = objects(self.base, BASE_MESSAGE)['blob'], objects(self.replacement, COMMIT_MESSAGE)['blob']
        return (b'diff --git a/src/app.py b/src/app.py\nindex ' + old.encode() + b'..' + new.encode() +
                b' 100644\n--- a/src/app.py\n+++ b/src/app.py\n@@ -1 +1 @@\n-' + self.base + b'+' + self.replacement)

    def commit_preview(self):
        return {'authority': 'NONE', 'repo_ref': self.repo_ref, 'expected_revision': self.expected_revision,
                'expected_head': self.base_head, 'base_branch': BASE_BRANCH, 'proposed_branch': self.branch,
                'proposed_commit': self.commit_head, 'plan_digest': self.digest, 'diff': self.diff_bytes().decode()}

    def github_preview(self):
        return {'schema': 'aioa.github-preview-fixture.v1', 'action': 'PREVIEW_ONLY', 'authority': 'NONE',
                'remote_effects': 0, 'repository': 'luciferprosun/AIOA-spArkHAT',
                'pr': {'base': 'INERT_FIXTURE_BASE', 'head': 'INERT_FIXTURE_HEAD',
                       'title': 'OFFLINE FIXTURE: controlled commit preview'},
                'ci': {'status': 'INERT_FIXTURE', 'provider_calls': 0}, 'plan_digest': self.digest}

    def result_bytes(self):
        return canonical({'schema': 'aioa.synthetic-git-result.v1', 'repo_ref': self.repo_ref,
                'revision': 2, 'plan_digest': self.digest, 'base_head': self.base_head, 'head': self.commit_head,
                'tree': objects(self.replacement, COMMIT_MESSAGE, self.base_head)['tree'], 'branch': self.branch,
                'status': 'CLEAN', 'branches': sorted((BASE_BRANCH, self.branch)),
                'log': [self.commit_head, self.base_head], 'diff_sha256': sha256(self.diff_bytes()),
                'source_sha256': sha256(self.replacement)})

    def recipe_spec(self, seed):
        require(type(seed) is SyntheticGitSeed, 'TRUSTED_GIT_SEED_REQUIRED')
        return {'files': {'recipe.py': Path(__file__).with_name('git_worker.py').read_bytes(),
                         'contract.py': Path(__file__).read_bytes(), 'plan.json': self.plan_bytes(),
                         'seed.json': canonical({'repo_ref': seed.repo_ref, 'revision': seed.revision,
                                                 'branch': seed.branch, 'source_sha256': sha256(seed.content)}),
                         'approved-base.txt': self.base, 'before.txt': seed.content, 'after.txt': self.replacement,
                         'base-message.txt': BASE_MESSAGE, 'commit-message.txt': COMMIT_MESSAGE},
                'expected': {'source.py': self.replacement, 'diff.patch': self.diff_bytes(),
                             'git-result.json': self.result_bytes(), 'github-preview.json': canonical(self.github_preview())}}
