"""Generate checked-in public colors for Compose resources and existing Linux Web."""
import argparse
import json
import re
from pathlib import Path

ANDROID = Path('clients/android/app/src/main/res/values/cosmic_colors.xml')
WEB = Path('web/cosmic_tokens.css')
NAMES = ('background','surface','primary','secondary','text','muted','warning','success','danger')

def render(value):
    colors = value['colors']
    if set(colors) != set(NAMES) or any(not isinstance(colors[n], str) or
            not re.fullmatch(r'#[0-9A-Fa-f]{6}', colors[n]) for n in NAMES):
        raise ValueError('INVALID_COSMIC_COLORS')
    xml = '<?xml version="1.0" encoding="utf-8"?>\n<!-- Generated from docs/design/cosmic.tokens.json -->\n<resources>\n'
    xml += ''.join(f'    <color name="cosmic_{name}">{colors[name]}</color>\n' for name in NAMES)
    xml += '</resources>\n'
    css = '/* Generated from docs/design/cosmic.tokens.json. Fonts: cosmic_fonts_ofl.txt. */\n:root {\n'
    css += ''.join(f'  --cosmic-{name}: {colors[name]};\n' for name in NAMES)
    css += '}\n'
    return {ANDROID: xml, WEB: css}

def generate(root, value, check=False):
    outputs = render(value)  # Validate all input before any output.
    if check:
        return all((root / path).is_file() and (root / path).read_text() == text for path, text in outputs.items())
    for path, text in outputs.items():
        destination = root / path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(text)
    return True

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    value = json.loads((root / 'docs/design/cosmic.tokens.json').read_text())
    return 0 if generate(root, value, args.check) else 1

if __name__ == '__main__':
    raise SystemExit(main())
