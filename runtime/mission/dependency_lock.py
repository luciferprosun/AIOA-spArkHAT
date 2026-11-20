"""Closed, inert pure-Python wheel inputs for the existing sandbox recipes.

No resolver, network, package import, setup script, host installation or authority.
The intentionally small supported format is documented by the recipe profile.
"""
import base64
import csv
import hashlib
import io
import json
import re
import stat
import sys
import zipfile
from dataclasses import dataclass, field
from email import policy
from email.parser import BytesParser
from types import MappingProxyType

MAX_BYTES = 1048576
MAX_MEMBERS = 256


def _require(condition, code='WHEEL_LOCK_DENIED'):
    if not condition:
        raise ValueError(code)


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'),
                      ensure_ascii=True, allow_nan=False).encode()


def _headers(raw, *, framework=False):
    _require(type(raw) is bytes and 0 < len(raw) <= 16384 and b'\0' not in raw)
    try:
        raw.decode('utf-8')
        value = BytesParser(policy=policy.default).parsebytes(raw)
        keys = [key.lower() for key in value]
        if framework:
            repeatable = {'project-url', 'classifier', 'requires-dist', 'license-file', 'provides-extra'}
            _require(not value.defects and len(keys) <= 128 and not value.is_multipart()
                     and all(keys.count(key) <= (32 if key in repeatable else 1) for key in set(keys)))
        else:
            _require(not value.defects and len(keys) == len(set(keys))
                     and len(keys) <= 32 and not value.is_multipart())
        return value
    except (ValueError, UnicodeError):
        raise ValueError('WHEEL_METADATA_DENIED') from None


def _wheel_members(raw, package, version, *, framework_pin=None):
    info_root = package + '-' + version + '.dist-info'
    required = {info_root + '/' + name for name in ('METADATA', 'WHEEL', 'RECORD')}
    framework = framework_pin is not None
    if framework:
        _require(type(framework_pin) is _FrameworkPin, 'FRAMEWORK_POLICY_REQUIRED')
    max_members, max_unpacked = (512, 5 * 1048576) if framework else (MAX_MEMBERS, MAX_BYTES)
    _require(raw.startswith(b'PK\x03\x04') and raw[-22:-18] == b'PK\x05\x06'
             and raw[-2:] == b'\0\0', 'WHEEL_ARCHIVE_DENIED')
    members = {}
    folded = set()
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            entries = archive.infolist()
            _require(not archive.comment and 3 <= len(entries) <= max_members)
            total = 0
            for entry in entries:
                name = entry.filename
                _require(type(name) is str and len(name.encode()) <= 192
                         and re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_./-]*', name)
                         and name.casefold() not in folded
                         and all(part not in ('', '.', '..') for part in name.split('/')),
                         'WHEEL_MEMBER_PATH_DENIED')
                folded.add(name.casefold())
                parts = name.split('/')
                is_metadata = name in required
                if framework:
                    package_file = (parts[0] in framework_pin.roots and len(parts) >= 2
                                    and name.endswith(('.py', '.typed', '.json', '.txt', '.dat')))
                    top_level_module = name in framework_pin.roots and name.endswith('.py')
                    metadata_file = (len(parts) >= 2 and parts[0] == info_root
                                     and (name in required or parts[-1] in {
                                         'entry_points.txt', 'top_level.txt', 'LICENSE', 'LICENSE.txt',
                                         'AUTHORS', 'AUTHORS.txt', 'INSTALLER', 'REQUESTED'}
                                          or len(parts) == 3 and parts[1] == 'licenses'
                                          and parts[-1].startswith(('LICENSE', 'AUTHORS'))))
                    _require(package_file or top_level_module or metadata_file, 'WHEEL_MEMBER_UNSUPPORTED')
                else:
                    _require(is_metadata or len(parts) >= 2 and parts[0] == package
                             and all(re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_.-]*', part) for part in parts)
                             and name.endswith(('.py', '.json', '.txt', '.dat')),
                             'WHEEL_MEMBER_UNSUPPORTED')
                _require(parts[-1] not in ('setup.py', 'postinstall.py', 'sitecustomize.py', 'usercustomize.py')
                         and '.data' not in parts and not name.endswith('.pth'),
                         'WHEEL_STARTUP_HOOK_DENIED')
                mode = entry.external_attr >> 16
                kind_ok = (stat.S_IFMT(mode) in (0, stat.S_IFREG) if framework else stat.S_ISREG(mode))
                modes = (0o600, 0o644, 0o664) if framework else (0o600, 0o644)
                _require(entry.create_system == 3 and kind_ok
                         and stat.S_IMODE(mode) in modes
                         and not entry.extra and not entry.comment
                         and entry.flag_bits & ~0x808 == 0
                         and entry.extract_version <= 20
                         and entry.compress_type in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED)
                         and 0 <= entry.file_size <= 262144
                         and entry.file_size <= max(1, entry.compress_size) * 256,
                         'WHEEL_MEMBER_TYPE_DENIED')
                total += entry.file_size
                _require(total <= max_unpacked, 'WHEEL_UNCOMPRESSED_BOUND')
                content = archive.read(entry)
                _require(len(content) == entry.file_size)
                if name.endswith('.py'):
                    _require(b'\0' not in content, 'WHEEL_SOURCE_ENCODING_DENIED')
                    content.decode('utf-8')
                members[name] = content
    except (OSError, ValueError, RuntimeError, zipfile.BadZipFile, UnicodeError, NotImplementedError):
        raise ValueError('WHEEL_ARCHIVE_DENIED') from None
    roots = framework_pin.roots if framework else (package,)
    root_entries = {root if root.endswith('.py') else root + '/__init__.py' for root in roots}
    _require(required <= set(members) and root_entries <= set(members), 'WHEEL_PACKAGE_REQUIRED')
    metadata = _headers(members[info_root + '/METADATA'], framework=framework)
    _require(re.sub('[-_.]+', '-', metadata.get('Name', '')).lower() == package.replace('_', '-')
             and metadata.get('Version') == version, 'WHEEL_METADATA_DENIED')
    if framework:
        _require(metadata.get('Metadata-Version') == framework_pin.metadata_version
                 and tuple(metadata.get_all('Dynamic', [])) == framework_pin.dynamic
                 and tuple(metadata.get_all('Provides-Extra', [])) == framework_pin.extras
                 and metadata.get('Requires-Python') == framework_pin.requires_python,
                 'FRAMEWORK_METADATA_DENIED')
    else:
        _require(metadata.get('Metadata-Version') in ('2.1', '2.2', '2.3', '2.4')
                 and not any(key in metadata for key in ('Requires-Dist', 'Dynamic', 'Provides-Extra')),
                 'WHEEL_METADATA_DENIED')
    wheel = _headers(members[info_root + '/WHEEL'])
    _require(wheel.get('Wheel-Version') == '1.0' and wheel.get('Root-Is-Purelib') == 'true'
             and wheel.get('Tag') == 'py3-none-any', 'WHEEL_TAG_DENIED')
    try:
        rows = list(csv.reader(io.StringIO(members[info_root + '/RECORD'].decode('utf-8')), strict=True))
        _require(len(rows) == len(members) and all(len(row) == 3 for row in rows)
                 and len({row[0] for row in rows}) == len(rows)
                 and {row[0] for row in rows} == set(members), 'WHEEL_RECORD_DENIED')
        for name, digest, size in rows:
            if name == info_root + '/RECORD':
                _require(digest == size == '', 'WHEEL_RECORD_DENIED')
            else:
                content = members[name]
                expected = base64.urlsafe_b64encode(hashlib.sha256(content).digest()).rstrip(b'=').decode()
                _require(digest == 'sha256=' + expected and size == str(len(content)), 'WHEEL_RECORD_DENIED')
    except (ValueError, UnicodeError, csv.Error):
        raise ValueError('WHEEL_RECORD_DENIED') from None
    return tuple(sorted(members.items()))


@dataclass(frozen=True, slots=True)
class LockedWheel:
    distribution: str
    version: str
    filename: str
    sha256: str
    content: bytes = field(repr=False)

    def __post_init__(self):
        _require(type(self.distribution) is str and len(self.distribution) <= 64
                 and re.fullmatch(r'[a-z][a-z0-9]*(?:-[a-z0-9]+)*', self.distribution))
        _require(type(self.version) is str and re.fullmatch(r'[0-9]+(?:\.[0-9]+){0,3}', self.version)
                 and len(self.version) <= 32)
        package = self.distribution.replace('-', '_')
        _require(package not in sys.stdlib_module_names | {'runtime', 'tui', 'aioa_cloudops_agent',
                 'sitecustomize', 'usercustomize', '__main__'}, 'WHEEL_RESERVED_PACKAGE')
        _require(type(self.filename) is str
                 and self.filename == package + '-' + self.version + '-py3-none-any.whl',
                 'WHEEL_FILENAME_DENIED')
        _require(type(self.content) is bytes and 0 < len(self.content) <= MAX_BYTES,
                 'WHEEL_BYTES_BOUND')
        _require(type(self.sha256) is str and re.fullmatch('[a-f0-9]{64}', self.sha256)
                 and hashlib.sha256(self.content).hexdigest() == self.sha256, 'WHEEL_HASH_MISMATCH')
        _wheel_members(self.content, package, self.version)

    def members(self):
        self.__post_init__()
        return _wheel_members(self.content, self.distribution.replace('-', '_'), self.version)

    def manifest(self):
        self.__post_init__()
        return {'distribution': self.distribution, 'version': self.version,
                'filename': self.filename, 'sha256': self.sha256, 'bytes': len(self.content)}


@dataclass(frozen=True, slots=True)
class PythonWheelLock:
    wheels: tuple

    def __post_init__(self):
        _require(type(self.wheels) is tuple and 1 <= len(self.wheels) <= 3
                 and all(type(wheel) is LockedWheel for wheel in self.wheels), 'WHEEL_LOCK_BOUND')
        _require(tuple(wheel.distribution for wheel in self.wheels)
                 == tuple(sorted({wheel.distribution for wheel in self.wheels})), 'WHEEL_LOCK_ORDER')
        paths = set()
        for wheel in self.wheels:
            members = wheel.members()
            names = {name.casefold() for name, _ in members}
            _require(not paths.intersection(names), 'WHEEL_LOCK_COLLISION')
            paths.update(names)

    @property
    def authority(self):
        return 'NONE'

    def manifest_bytes(self):
        self.__post_init__()
        return _json({'schema': 'aioa.python-wheel-lock.v1', 'authority': 'NONE', 'network': 'OFF',
                      'wheels': [wheel.manifest() for wheel in self.wheels]})

    @property
    def digest(self):
        return hashlib.sha256(self.manifest_bytes()).hexdigest()

    def inputs(self):
        return {'python-wheel-lock.json': self.manifest_bytes(),
                **{wheel.filename: wheel.content for wheel in self.wheels}}



@dataclass(frozen=True, slots=True)
class _FrameworkPin:
    version: str
    filename: str
    sha256: str
    size: int
    roots: tuple
    metadata_version: str
    dynamic: tuple
    extras: tuple
    requires_python: str


# Fixed public data, not a resolver or approval registry. Package code is never
# imported by this validator. Only the isolated reviewed recipe may use it.
_FRAMEWORK_PINS = MappingProxyType({
    'iniconfig': _FrameworkPin('2.3.1', 'iniconfig-2.3.1-py3-none-any.whl', '9121e2c1fdb355232495be3194c8dfe87ccc2d5dee45947b78e68f499790d7a7', 7552, ('iniconfig',), '2.4', ('license-file',), (), '>=3.10'),
    'packaging': _FrameworkPin('26.3', 'packaging-26.3-py3-none-any.whl', 'd7193f7c8e4e93f444fde0262bf90af30e16fa0ad0ad44cb553c87339b23cd1c', 129956, ('packaging',), '2.4', (), (), '>=3.9'),
    'pluggy': _FrameworkPin('1.7.0', 'pluggy-1.7.0-py3-none-any.whl', '7dd7b0d8832ba3cb632c306926ded123429211b83641b35dc5c41ad2d34f9bec', 27082, ('pluggy',), '2.4', ('license-file',), (), '>=3.10'),
    'pygments': _FrameworkPin('2.21.0', 'pygments-2.21.0-py3-none-any.whl', '2363c69b61c4a97c838da3b130dcd6468f4848992b21a82f2a63ec34377137d9', 1250147, ('pygments',), '2.5', (), ('plugins', 'windows-terminal'), '>=3.9'),
    'pytest': _FrameworkPin('9.2.0', 'pytest-9.2.0-py3-none-any.whl', '07acdcf88ec174f907dc01af70bf52d49b014bbab03faeeade31c96b18c2e588', 411776, ('_pytest', 'pytest', 'py.py'), '2.4', ('license-file',), ('dev',), '>=3.10'),
})


@dataclass(frozen=True, slots=True)
class FrameworkWheel:
    distribution: str
    version: str
    filename: str
    sha256: str
    content: bytes = field(repr=False)

    def __post_init__(self):
        _require(type(self.distribution) is str and self.distribution in _FRAMEWORK_PINS,
                 'FRAMEWORK_DISTRIBUTION_DENIED')
        pin = _FRAMEWORK_PINS[self.distribution]
        _require(type(self.version) is str and type(self.filename) is str
                 and type(self.sha256) is str
                 and (self.version, self.filename, self.sha256) == (pin.version, pin.filename, pin.sha256),
                 'FRAMEWORK_PIN_MISMATCH')
        _require(type(self.content) is bytes and len(self.content) == pin.size
                 and len(self.content) <= 2 * MAX_BYTES
                 and hashlib.sha256(self.content).hexdigest() == pin.sha256, 'FRAMEWORK_BYTES_MISMATCH')
        _wheel_members(self.content, self.distribution.replace('-', '_'), self.version, framework_pin=pin)

    def members(self):
        self.__post_init__()
        return _wheel_members(self.content, self.distribution.replace('-', '_'), self.version,
                              framework_pin=_FRAMEWORK_PINS[self.distribution])

    def manifest(self):
        self.__post_init__()
        return {'distribution': self.distribution, 'version': self.version, 'filename': self.filename,
                'sha256': self.sha256, 'bytes': len(self.content)}


@dataclass(frozen=True, slots=True)
class PytestWheelLock:
    wheels: tuple

    def __post_init__(self):
        _require(type(self.wheels) is tuple and len(self.wheels) == 5
                 and all(type(wheel) is FrameworkWheel for wheel in self.wheels), 'FRAMEWORK_LOCK_BOUND')
        _require(tuple(wheel.distribution for wheel in self.wheels) == tuple(sorted(_FRAMEWORK_PINS)),
                 'FRAMEWORK_LOCK_CLOSURE')
        _require(sum(len(wheel.content) for wheel in self.wheels) <= 2 * MAX_BYTES, 'FRAMEWORK_LOCK_BYTES')
        paths = set()
        total = count = 0
        for wheel in self.wheels:
            for name, data in wheel.members():
                folded = name.casefold()
                _require(folded not in paths
                         and not any(folded.startswith(path + '/') or path.startswith(folded + '/') for path in paths),
                         'FRAMEWORK_LOCK_COLLISION')
                paths.add(folded)
                total += len(data)
                count += 1
                _require(total <= 8 * MAX_BYTES and count <= 512, 'FRAMEWORK_LOCK_UNPACK_BOUND')

    @property
    def authority(self):
        return 'NONE'

    def manifest_bytes(self):
        self.__post_init__()
        return _json({'schema': 'aioa.pytest-wheel-lock.v1', 'authority': 'NONE', 'network': 'OFF',
                      'target': 'LINUX_CPYTHON_3_12', 'extras': [],
                      'wheels': [wheel.manifest() for wheel in self.wheels]})

    @property
    def digest(self):
        return hashlib.sha256(self.manifest_bytes()).hexdigest()

    def inputs(self):
        return {'python-wheel-lock.json': self.manifest_bytes(),
                **{wheel.filename: wheel.content for wheel in self.wheels}}
