"""Check the generator boundary, not screenshots or the text of its source."""
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'scripts/design/generate_cosmic_tokens.py'

class CosmicTokenTests(unittest.TestCase):
    def generator(self):
        self.assertTrue(SCRIPT.is_file(), 'shared Cosmic token generator is missing')
        spec = importlib.util.spec_from_file_location('cosmic_tokens', SCRIPT)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_untrusted_css_value_is_rejected_before_creating_output(self):
        module = self.generator()
        value = json.loads((ROOT / 'docs/design/cosmic.tokens.json').read_text())
        for bad in ['#000000; background:url(https://example.invalid)', '#fff', 'red', None]:
            value['colors']['primary'] = bad
            with self.subTest(value=bad), self.assertRaises(ValueError):
                module.render(value)

    def test_generation_detects_drift_without_overwriting_it(self):
        module = self.generator()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            value = json.loads((ROOT / 'docs/design/cosmic.tokens.json').read_text())
            self.assertTrue(module.generate(root, value, check=False))
            self.assertTrue(module.generate(root, value, check=True))
            file = root / module.ANDROID
            file.write_text('operator edit')
            self.assertFalse(module.generate(root, value, check=True))
            self.assertEqual('operator edit', file.read_text())

    def test_enabled_text_and_status_chip_colors_have_normal_text_contrast(self):
        colors=json.loads((ROOT/'docs/design/cosmic.tokens.json').read_text())['colors']
        def rgb(value):return [int(value[index:index+2],16)/255 for index in (1,3,5)]
        def luminance(value):
            linear=[v/12.92 if v<=.04045 else ((v+.055)/1.055)**2.4 for v in value]
            return sum(a*b for a,b in zip(linear,(.2126,.7152,.0722)))
        def contrast(fg,bg):
            a,b=sorted((luminance(fg),luminance(bg)))
            return (b+.05)/(a+.05)
        for background in ('background','surface'):
            bg=rgb(colors[background])
            for name in ('text','muted','primary','success','warning','danger'):
                fg=rgb(colors[name])
                with self.subTest(background=background,text=name):
                    self.assertGreaterEqual(contrast(fg,bg),4.5)
                    # StatusChip paints a12% status tint beneath its full-color label.
                    if name in ('primary','success','warning','danger'):
                        chip=[.12*f+.88*b for f,b in zip(fg,bg)]
                        self.assertGreaterEqual(contrast(fg,chip),4.5)
