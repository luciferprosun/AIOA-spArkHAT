"""Proposal-only local browser contract. No executor or browser authority.

Core owns the registered session, task, STOP and epoch. This bounded contract
does READ validation only; a future certified browser must use Core START,
warrant, liability and independent readback before enabling any operation.
"""
from dataclasses import asdict, dataclass
import json
import re
from urllib.parse import urlsplit

from runtime.core_admission import Capability
from runtime.memory_patch.contracts.serialization import canonical_json_bytes
from runtime.mission.completion import TaskCompletionBinding
from runtime.mission.tools import CoreToolRoute
from runtime.mission.warrant import require
from lab.archaioa.faults import opaque_id


def digest(value):
    require(type(value) is str and re.fullmatch('[0-9a-f]{64}', value) is not None,
            'BROWSER_DIGEST')


def preview_origin(value):
    require(type(value) is str and len(value) <= 64, 'BROWSER_ORIGIN')
    try:
        parsed = urlsplit(value)
        port = parsed.port
        hostname = parsed.hostname
    except (ValueError, UnicodeError):
        raise ValueError('BROWSER_ORIGIN') from None
    require(parsed.scheme == 'http' and hostname == '127.0.0.1'
            and type(port) is int and 1024 <= port <= 65535
            and value == f'http://127.0.0.1:{port}', 'BROWSER_ORIGIN')
    return value


def preview_url(value, origin):
    require(type(value) is str and len(value) <= 256, 'BROWSER_URL')
    try:
        parsed = urlsplit(value)
    except (ValueError, UnicodeError):
        raise ValueError('BROWSER_URL') from None
    require(value.startswith(origin + '/') and not parsed.query and not parsed.fragment
            and re.fullmatch(r'/preview/[A-Za-z0-9_-]+\.html', parsed.path) is not None
            and value == origin + parsed.path, 'BROWSER_URL')
    return value


@dataclass(frozen=True, slots=True)
class PreviewScope:
    task_id: str
    session_id: str
    grant_digest: str
    epoch: int
    project_revision: str
    origin: str
    urls: tuple[str, ...]
    click_ids: tuple[str, ...] = ('#preview-check',)

    def __post_init__(self):
        opaque_id(self.task_id, 'task'); opaque_id(self.session_id, 'session')
        digest(self.grant_digest); digest(self.project_revision)
        require(type(self.epoch) is int and self.epoch > 0, 'BROWSER_EPOCH')
        preview_origin(self.origin)
        require(type(self.urls) is tuple and 1 <= len(self.urls) <= 4
                and len(set(self.urls)) == len(self.urls), 'BROWSER_URLS')
        for url in self.urls:
            preview_url(url, self.origin)
        require(type(self.click_ids) is tuple and len(self.click_ids) <= 4
                and all(type(s) is str and re.fullmatch(r'#preview-[a-z0-9-]{1,32}', s)
                        is not None for s in self.click_ids), 'BROWSER_SELECTORS')


@dataclass(frozen=True, slots=True)
class PageIdentity:
    page_id: str
    generation: int
    url: str

    def __post_init__(self):
        opaque_id(self.page_id, 'page')
        require(type(self.generation) is int and 1 <= self.generation <= 2**31,
                'BROWSER_PAGE')
        require(type(self.url) is str and len(self.url) <= 256, 'BROWSER_PAGE')


@dataclass(frozen=True, slots=True)
class BrowserPreviewRequest:
    task_id: str
    session_id: str
    grant_digest: str
    epoch: int
    project_revision: str
    page_id: str
    page_generation: int
    page_url: str
    action: str
    target_url: str = ''
    selector: str = ''
    timeout_ms: int = 1000

    def __post_init__(self):
        for name in ('task_id', 'session_id', 'page_id'):
            opaque_id(getattr(self, name), name)
        digest(self.grant_digest); digest(self.project_revision)
        require(type(self.epoch) is int and self.epoch > 0
                and type(self.page_generation) is int and self.page_generation > 0,
                'BROWSER_BINDING')
        require(self.action in ('navigate', 'click', 'read'), 'BROWSER_ACTION_DISABLED')
        require(all(type(v) is str and len(v) <= 256 for v in
                    (self.page_url, self.target_url, self.selector)), 'BROWSER_INPUT')
        require(type(self.timeout_ms) is int and 1 <= self.timeout_ms <= 2000,
                'BROWSER_TIMEOUT')
        require(len(canonical_json_bytes(asdict(self))) <= 2048, 'BROWSER_INPUT')

    @classmethod
    def parse(cls, value):
        require(type(value) is dict and set(value) == set(cls.__dataclass_fields__),
                'BROWSER_INPUT')
        require(len(canonical_json_bytes(value)) <= 2048, 'BROWSER_INPUT')
        return cls(**json.loads(canonical_json_bytes(value)))


@dataclass(frozen=True, slots=True, repr=False)
class DisabledBrowserPreview:
    route: CoreToolRoute
    scope: PreviewScope
    completion: TaskCompletionBinding

    def __post_init__(self):
        require(type(self.route) is CoreToolRoute and type(self.scope) is PreviewScope
                and type(self.completion) is TaskCompletionBinding
                and self.completion.scope == self.route.scope
                and self.completion.task_id == self.scope.task_id, 'BROWSER_CORE_BINDING')

    def validate(self, principal, value, current_page, current_project_revision):
        require(type(current_page) is PageIdentity, 'BROWSER_PAGE')
        request = BrowserPreviewRequest.parse(value)
        scope = self.scope
        require((request.task_id, request.session_id, request.grant_digest,
                 request.epoch, request.project_revision) ==
                (scope.task_id, scope.session_id, scope.grant_digest,
                 scope.epoch, scope.project_revision), 'BROWSER_SCOPE')
        require(current_project_revision == scope.project_revision, 'BROWSER_REVISION_DRIFT')
        require((request.page_id, request.page_generation, request.page_url) ==
                (current_page.page_id, current_page.generation, current_page.url),
                'BROWSER_PAGE_DRIFT')
        preview_url(current_page.url, scope.origin)
        require(current_page.url in scope.urls, 'BROWSER_PAGE_DRIFT')
        if request.action == 'navigate':
            preview_url(request.target_url, scope.origin)
            require(request.target_url in scope.urls and not request.selector, 'BROWSER_TARGET')
        elif request.action == 'click':
            require(request.selector in scope.click_ids and not request.target_url, 'BROWSER_TARGET')
        else:
            require(not request.selector and not request.target_url, 'BROWSER_TARGET')

        def read(tx):
            _, _, grant = self.route._session(tx, scope.session_id)
            job = self.route._native_job(tx, self.completion)
            require(grant.digest == scope.grant_digest and grant.epoch == scope.epoch
                    and grant.completion_digest == self.completion.digest
                    and 'PROJECT_WRITE' in grant.capabilities
                    and job is not None and job.get('completion_binding') == self.completion.to_dict(),
                    'BROWSER_CORE_BINDING')
        self.route._run(principal, Capability.READ, read)
        return request

    def request(self, principal, value, current_page, current_project_revision):
        self.validate(principal, value, current_page, current_project_revision)
        return {'schema': 'aioa.browser-preview.v1', 'status': 'UNAVAILABLE',
                'reason': 'REAL_MANAGED_BROWSER_NOT_ACCEPTED', 'real_browser': False,
                'authority': 'NONE', 'dispatch': False, 'auto_retry': False,
                'evidence_level': 'CONTRACT_ONLY', 'D4': 'BLOCKED_ENVIRONMENT'}
