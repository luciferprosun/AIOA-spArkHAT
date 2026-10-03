"""Execute the real panel renderer offline; unknown counts must stay unknown."""
import json
from pathlib import Path
import subprocess
import unittest


class PersonalAIDemoUITests(unittest.TestCase):
    def render(self, payload):
        source = (Path(__file__).resolve().parents[1]/'web/app.js').read_text()
        start = source.index('function renderPersonalAI(')
        end = source.index('async function refreshPersonalAI()', start)
        harness = '''const state = {};
        const nodes = {};
        const elements = new Proxy({}, {get: (_, key) => nodes[key] ||= {
          textContent: '', disabled: false, replaceChildren() {}, appendChild() {}}});
        const document = {createElement: () => ({})};
        ''' + source[start:end] + '\nrenderPersonalAI(' + json.dumps(payload) + ''');
        console.log(JSON.stringify({effects: nodes.personalAIEffects.textContent,
          guard: nodes.personalAIGuard.textContent}));'''
        result = subprocess.run(['node', '-e', harness], capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, 'REAL_RENDERER_EXECUTION_FAILED')
        return json.loads(result.stdout)

    def test_unknown_readback_never_displays_zero_effects(self):
        for pending in (False, True):
            with self.subTest(pending=pending):
                rendered = self.render({'effects': {'apply_count': None, 'duplicate_count': None},
                    'service_guard': {'state': 'EXECUTED', 'outcome': 'UNKNOWN',
                                      'reconciliation_pending': pending}})
                self.assertIn('UNKNOWN', rendered['effects'])
                self.assertNotIn('0 applied', rendered['effects'])
                self.assertIn('UNKNOWN', rendered['guard'])
                if pending:
                    self.assertIn('RECONCILIATION PENDING', rendered['guard'])

    def test_measured_zero_and_one_remain_exact(self):
        for count in (0, 1):
            rendered = self.render({'effects': {'apply_count': count, 'duplicate_count': 0},
                                    'service_guard': {'state': 'APPROVED'}})
            self.assertEqual(rendered['effects'], f'{count} applied · 0 duplicate')


if __name__ == '__main__':
    unittest.main()
