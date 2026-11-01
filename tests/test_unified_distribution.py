"""Cross-check shipped web assets against the product HTML entry point."""
from html.parser import HTMLParser
from pathlib import Path
import tomllib
import unittest


class DistributionWebTests(unittest.TestCase):
    def test_every_local_entry_page_asset_is_in_the_single_distribution(self):
        root=Path(__file__).resolve().parents[1]
        class Assets(HTMLParser):
            def __init__(self):super().__init__();self.paths=set()
            def handle_starttag(self,tag,attrs):
                values=dict(attrs);path=values.get('src') if tag=='script' else values.get('href') if tag=='link' else None
                if path and path.startswith('/') and not path.startswith('//'):self.paths.add('web/'+path[1:])
        html=Assets();html.feed((root/'web/index.html').read_text())
        metadata=tomllib.loads((root/'pyproject.toml').read_text())
        shipped=set(metadata['tool']['setuptools']['data-files']['share/aioa-sparkhat/web'])
        self.assertFalse(html.paths-shipped,'entry page references assets missing from the installed distribution')


if __name__=='__main__':unittest.main()
