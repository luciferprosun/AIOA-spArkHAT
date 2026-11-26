"""Closed MobileMissionV1 wire format. No credentials, network or effects here."""
import base64
import hashlib
import ipaddress
import json
import re
from dataclasses import dataclass, field
from urllib.parse import urlsplit

from cryptography.exceptions import InvalidSignature, UnsupportedAlgorithm
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec

BASE = '/api/mobile/v1'
VIEW_BASE = '/api/mobile/v2'
BODY_LIMIT = 16384
RESPONSE_LIMIT = 65536
HEX32 = re.compile(r'[0-9a-f]{32}\Z')
HEX64 = re.compile(r'[0-9a-f]{64}\Z')
SHA40 = re.compile(r'[0-9a-f]{40}\Z')
TASK = re.compile(r'meta-[0-9a-f]{32}\Z')
AGENT_TASK = re.compile(r'agent-[0-9a-f]{32}\Z')
ERRORS = {400: 'INVALID_FRAME', 401: 'AUTH_DENIED', 403: 'SCOPE_DENIED',
          409: 'REPLAY_OR_READBACK_REQUIRED', 413: 'BOUNDS', 429: 'RATE_LIMITED',
          501: 'NOT_IMPLEMENTED', 503: 'REMOTE_DEPLOYMENT_BLOCKED_OR_SOURCE_CHANGED_OR_UNKNOWN'}


class MobileError(ValueError):
    def __init__(self, status=400):
        self.status = status
        self.code = ERRORS[status]
        super().__init__(self.code)


def _shape(value, depth=0):
    if depth > 16:
        raise MobileError()
    if isinstance(value, dict):
        if any(not isinstance(k, str) for k in value):
            raise MobileError()
        for k, v in value.items():
            k.encode('utf-8', 'strict')
            _shape(v, depth + 1)
    elif isinstance(value, list):
        for v in value:
            _shape(v, depth + 1)
    elif isinstance(value, str):
        value.encode('utf-8', 'strict')
    elif value is not None and type(value) not in (int, bool):
        raise MobileError()
    elif type(value) is int and abs(value) > 9007199254740991:
        raise MobileError()


def canonical(value):
    try:
        _shape(value)
        return json.dumps(value, sort_keys=True, separators=(',', ':'),
                          ensure_ascii=False, allow_nan=False).encode('utf-8')
    except (ValueError, TypeError, UnicodeError, RecursionError):
        raise MobileError() from None


def strict_json(raw,*,limit=BODY_LIMIT):
    if type(limit) is not int or limit not in (BODY_LIMIT,RESPONSE_LIMIT) or len(raw) > limit:
        raise MobileError(413)
    def pairs(items):
        result = {}
        for k, v in items:
            if k in result:
                raise MobileError()
            result[k] = v
        return result
    def reject(_):
        raise MobileError()
    try:
        value = json.loads(raw.decode('utf-8'), object_pairs_hook=pairs,
                           parse_float=reject, parse_constant=reject)
        if not isinstance(value, dict):
            raise MobileError()
        _shape(value)
        return value
    except (ValueError, UnicodeError, RecursionError):
        raise MobileError() from None


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def unbase64(value):
    try:
        if not isinstance(value, str) or len(value) > 1024:
            raise ValueError()
        raw = base64.b64decode(value, validate=True)
        if base64.b64encode(raw).decode('ascii') != value:
            raise ValueError()
        return raw
    except (ValueError, TypeError):
        raise MobileError(401) from None


def public_key(spki):
    try:
        key = serialization.load_der_public_key(unbase64(spki))
        if not isinstance(key, ec.EllipticCurvePublicKey) or not isinstance(key.curve, ec.SECP256R1):
            raise ValueError()
        if key.public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo) != unbase64(spki):
            raise ValueError()
        return key
    except (ValueError, TypeError, UnsupportedAlgorithm):
        raise MobileError(401) from None


@dataclass(frozen=True)
class Identity:
    key: ec.EllipticCurvePrivateKey = field(repr=False)

    def __post_init__(self):
        if not isinstance(self.key, ec.EllipticCurvePrivateKey) or not isinstance(self.key.curve, ec.SECP256R1):
            raise MobileError(401)

    @property
    def spki(self):
        return base64.b64encode(self.key.public_key().public_bytes(serialization.Encoding.DER,
                              serialization.PublicFormat.SubjectPublicKeyInfo)).decode('ascii')

    @property
    def audience(self):
        return digest(unbase64(self.spki))

    def sign(self, proof):
        return base64.b64encode(self.key.sign(canonical(proof), ec.ECDSA(hashes.SHA256()))).decode('ascii')


def verify(spki, signature, proof):
    try:
        public_key(spki).verify(unbase64(signature), canonical(proof), ec.ECDSA(hashes.SHA256()))
    except (InvalidSignature, ValueError, TypeError):
        raise MobileError(401) from None


def origin(value):
    try:
        p = urlsplit(value)
        if not isinstance(value, str) or not value.isascii() or p.scheme != 'https' or not p.hostname:
            raise ValueError()
        if p.username or p.password or p.path or p.query or p.fragment or p.port == 443:
            raise ValueError()
        host = p.hostname
        try:
            ipaddress.ip_address(host)
        except ValueError:
            pass
        else:
            raise ValueError()
        if not re.fullmatch(r'[a-z0-9](?:[a-z0-9.-]{0,251}[a-z0-9])?', host) or '.' not in host:
            raise ValueError()
        if any(not part or len(part) > 63 or part[0] == '-' or part[-1] == '-' for part in host.split('.')):
            raise ValueError()
        if value != 'https://' + host + (':' + str(p.port) if p.port else ''):
            raise ValueError()
        return value
    except (ValueError, TypeError, AttributeError):
        raise MobileError() from None


def route(method, path):
    if path.startswith(VIEW_BASE+'/'):
        suffix=path[len(VIEW_BASE):]
        chat_fixed={('POST','/chat'):'chat_send',('GET','/chat/threads'):'chat_threads',('POST','/chat/stop'):'chat_stop'}
        if (method,suffix) in chat_fixed:return chat_fixed[(method,suffix)],None
        for prefix,name in (('/chat/requests/','chat_request'),('/chat/threads/','chat_thread')):
            if method=='GET' and suffix.startswith(prefix) and HEX32.fullmatch(suffix[len(prefix):]):
                return name,suffix[len(prefix):]
        fixed={('GET','/status'):'agent_status',('POST','/propose'):'agent_propose',
            ('POST','/stop'):'agent_stop',('GET','/providers'):'agent_providers',
            ('POST','/install-proposal'):'agent_install'}
        suffix=path[len(VIEW_BASE):]
        if (method,suffix) in fixed:return fixed[(method,suffix)],None
        for prefix,name,pattern in (('/tasks/','agent_task',AGENT_TASK),
            ('/proposals/','agent_proposal',HEX32),('/status/pages/','agent_page',AGENT_TASK)):
            if method=='GET' and suffix.startswith(prefix) and pattern.fullmatch(suffix[len(prefix):]):
                return name,suffix[len(prefix):]
        raise MobileError(501 if suffix in ('/run','/approve','/install','/native_execute','/github_write','/meta_spend') else 400)
    fixed = {('POST','/pairing/begin'):'pairing_begin', ('POST','/pairing/status'):'pairing_status',
             ('POST','/pairing/complete'):'pairing_complete',('POST','/session/challenge'):'session_challenge',
             ('POST','/session/reconnect'):'session_reconnect',('GET', '/capabilities'): 'capabilities', ('POST', '/enrollment/redeem'): 'redeem',
             ('GET', '/status'): 'status', ('POST', '/preview'): 'preview',
             ('POST', '/stop'): 'stop', ('POST', '/session/revoke'): 'revoke'}
    if (method, path.removeprefix(BASE)) in fixed and path.startswith(BASE + '/'):
        return fixed[(method, path[len(BASE):])], None
    for prefix, name, pattern in (('/status/pages/', 'status_page', TASK),
                                  ('/tasks/', 'task', TASK), ('/evidence/', 'evidence', TASK),
                                  ('/proposals/', 'proposal', HEX32)):
        if method == 'GET' and path.startswith(BASE + prefix):
            value = path[len(BASE + prefix):]
            if pattern.fullmatch(value):
                return name, value
    raise MobileError(501 if path in {BASE+'/'+x for x in ('run','approve','chat','native_execute','meta_spend','github_write','owner_pairing_m12')} else 400)


def request_proof(method, path, body, *, token, nonce, issued_at, audience, source_sha, capsule_digest):
    return dict(schema='aioa.mobile.request-proof.v1', method=method, path=path,
                body_sha256=digest(body), token_sha256=digest(token.encode('ascii')),
                nonce=nonce, issued_at=issued_at, audience=audience,
                source_sha=source_sha, capsule_digest=capsule_digest)
