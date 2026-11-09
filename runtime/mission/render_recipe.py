"""Explicit offline HTML bundle recipe and a host-side observation oracle.

The DTO is inert. Only the existing Core/broker release path can execute it.
Expected answers stay outside the credentialless guest.
"""
import base64
import binascii
import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path


def require(condition, code):
    if not condition:
        raise ValueError(code)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'),
                      ensure_ascii=False, allow_nan=False).encode()


@dataclass(frozen=True, slots=True)
class HtmlRenderRecipe:
    bundle: tuple = field(repr=False)
    viewport: tuple[int, int]
    expected_title: str = field(repr=False)
    expected_text: str = field(repr=False)

    def __post_init__(self):
        from runtime.secret_redaction import contains_sensitive_material

        require(type(self.bundle) is tuple and 1 <= len(self.bundle) <= 3, 'RENDER_BUNDLE')
        seen = set()
        total = 0
        for entry in self.bundle:
            require(type(entry) is tuple and len(entry) == 2, 'RENDER_BUNDLE')
            name, data = entry
            require(type(name) is str and name in ('index.html', 'style.css', 'app.js')
                    and name not in seen and type(data) is bytes and 0 < len(data) <= 32768,
                    'RENDER_BUNDLE')
            require(not contains_sensitive_material(data.decode('utf-8')), 'RENDER_SENSITIVE_BUNDLE')
            seen.add(name)
            total += len(data)
        require('index.html' in seen and total <= 65536, 'RENDER_BUNDLE')
        require(type(self.viewport) is tuple and len(self.viewport) == 2
                and all(type(value) is int and 0 < value <= 512 for value in self.viewport)
                and self.viewport[0] * self.viewport[1] <= 262144, 'RENDER_VIEWPORT')
        for value, limit in ((self.expected_title, 256), (self.expected_text, 2048)):
            require(type(value) is str and 0 < len(value.encode()) <= limit
                    and not contains_sensitive_material(value), 'RENDER_ORACLE_BOUND')

    @property
    def authority(self):
        return 'NONE'

    def manifest_bytes(self):
        return canonical({
            'schema': 'aioa.hermetic-html-recipe.v1', 'authority': 'NONE',
            'resource_profile': 'HEADLESS_RENDER_V2', 'network': 'OFF',
            'transport': 'CDP_PIPE', 'viewport': list(self.viewport),
            'bundle': {name: {'sha256': hashlib.sha256(data).hexdigest(), 'bytes': len(data)}
                       for name, data in self.bundle},
            'oracle_sha256': hashlib.sha256(canonical({
                'title': self.expected_title, 'body_text': self.expected_text})).hexdigest(),
        })

    @property
    def digest(self):
        return hashlib.sha256(self.manifest_bytes()).hexdigest()

    def recipe_spec(self):
        from runtime.mobile_gateway import chrome_console

        config = {'schema': 'aioa.hermetic-render-input.v1', 'recipe_digest': self.digest,
                  'viewport': list(self.viewport),
                  'bundle': json.loads(self.manifest_bytes())['bundle']}
        files = {'recipe.py': Path(__file__).with_name('render_worker.py').read_bytes(),
                 'chrome_pipe.py': Path(chrome_console.__file__).read_bytes(),
                 'render.json': canonical(config),
                 'fonts.conf': b'<?xml version="1.0"?><!DOCTYPE fontconfig SYSTEM "fonts.dtd">'
                               b'<fontconfig><dir>/usr/share/fonts/truetype/dejavu</dir>'
                               b'<cachedir>/work/font-cache</cachedir></fontconfig>'}
        files.update({'page-' + name: data for name, data in self.bundle})
        return {'files': files, 'expected': {'render-executed.txt': b'RENDER_PROCESS_FINISHED\n'}}

    def verify_observation(self, raw):
        from runtime.mission.render_observation import decode_png_summary

        require(type(raw) is bytes and 0 < len(raw) <= 16384, 'RENDER_OBSERVATION_BOUND')

        def pairs(items):
            require(len(items) == len(dict(items)), 'RENDER_OBSERVATION_DUPLICATE')
            return dict(items)

        try:
            value = json.loads(raw, object_pairs_hook=pairs,
                               parse_constant=lambda _: require(False, 'RENDER_OBSERVATION_NUMBER'))
        except (RecursionError, UnicodeError):
            raise ValueError('RENDER_OBSERVATION_JSON') from None
        require(type(value) is dict and set(value) == {
            'schema', 'recipe_digest', 'document', 'screenshot_base64', 'console_errors', 'transport'},
            'RENDER_OBSERVATION_SCHEMA')
        require(value['schema'] == 'aioa.hermetic-render-observation.v1'
                and value['recipe_digest'] == self.digest
                and type(value['console_errors']) is int and value['console_errors'] == 0
                and value['transport'] == {'kind': 'CDP_PIPE', 'network': 'OFF', 'profile': 'FRESH'},
                'RENDER_OBSERVATION_BINDING')
        require(value['document'] == {
            'href': 'file:///work/site/index.html', 'ready_state': 'complete',
            'title': self.expected_title, 'body_text': self.expected_text}, 'RENDER_DOCUMENT_ORACLE')
        encoded = value['screenshot_base64']
        require(type(encoded) is str and encoded.isascii() and len(encoded) <= 10924,
                'RENDER_SCREENSHOT_BOUND')
        try:
            image = base64.b64decode(encoded, validate=True)
        except binascii.Error:
            raise ValueError('RENDER_SCREENSHOT_ENCODING') from None
        require(0 < len(image) <= 8192, 'RENDER_SCREENSHOT_BOUND')
        summary = decode_png_summary(image, viewport=self.viewport)
        require(summary['visible_ink_pixels'] > 0 and summary['non_uniform'], 'RENDER_VISIBILITY_ORACLE')
        return {'status': 'PASS', 'authority': 'NONE', 'recipe_digest': self.digest,
                'screenshot': summary, 'console_errors': 0,
                'document_sha256': hashlib.sha256(canonical(value['document'])).hexdigest()}
