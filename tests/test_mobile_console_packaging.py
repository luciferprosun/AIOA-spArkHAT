"""The installed console must contain every local asset used by its HTML."""
import tomllib
import unittest
from html.parser import HTMLParser
from pathlib import Path


class _Assets(HTMLParser):
    def __init__(self):
        super().__init__()
        self.paths = set()

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        value = attrs.get('src') if tag == 'script' else (
            attrs.get('href') if tag == 'link' and attrs.get('rel') == 'stylesheet' else None)
        if value and value.startswith('/') and not value.startswith('//'):
            self.paths.add('web' + value)


class ConsolePackagingTests(unittest.TestCase):
    def test_installed_console_contains_its_local_assets(self):
        root = Path(__file__).resolve().parents[1]
        parser = _Assets()
        parser.feed((root / 'web/index.html').read_text())
        config = tomllib.loads((root / 'pyproject.toml').read_text())
        packaged = set(config['tool']['setuptools']['data-files']['share/aioa-sparkhat/web'])
        self.assertTrue(parser.paths)
        self.assertEqual(parser.paths - packaged, set(), 'HTML assets missing from installed wheel')
        for asset in parser.paths:
            self.assertTrue((root / asset).is_file(), asset)
