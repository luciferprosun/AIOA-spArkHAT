"""Operator recipe/oracle contracts; PNG fixtures are codec inputs, not browser proof."""
import base64
import hashlib
import importlib
import json
import struct
import unittest
import zlib


def png():
    def chunk(name, data):
        return struct.pack('>I', len(data)) + name + data + struct.pack('>I', zlib.crc32(name + data))
    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', 2, 1, 8, 2, 0, 0, 0))
            + chunk(b'IDAT', zlib.compress(b'\x00\x00\x00\x00\xff\xff\xff')) + chunk(b'IEND', b''))


class HermeticRenderRecipeTests(unittest.TestCase):
    def module(self):
        try:
            return importlib.import_module('runtime.mission.render_recipe')
        except ModuleNotFoundError as exc:
            self.fail('Missing operator render recipe: ' + exc.name)

    def recipe(self, **overrides):
        values = {'bundle': (('index.html', b'<!doctype html><title>Fixture</title><p>Visible</p>'),),
                  'viewport': (2, 1), 'expected_title': 'Fixture', 'expected_text': 'Visible'}
        values.update(overrides)
        return self.module().HtmlRenderRecipe(**values)

    def observation(self, recipe):
        return {'schema': 'aioa.hermetic-render-observation.v1', 'recipe_digest': recipe.digest,
                'document': {'href': 'file:///work/site/index.html', 'ready_state': 'complete',
                             'title': 'Fixture', 'body_text': 'Visible'},
                'screenshot_base64': base64.b64encode(png()).decode(), 'console_errors': 0,
                'transport': {'kind': 'CDP_PIPE', 'network': 'OFF', 'profile': 'FRESH'}}

    def encoded(self, value):
        return json.dumps(value, sort_keys=True, separators=(',', ':')).encode()

    def test_recipe_has_no_execution_authority_and_pins_the_bundle_and_oracle(self):
        recipe = self.recipe()
        self.assertEqual('NONE', recipe.authority)
        manifest = json.loads(recipe.manifest_bytes())
        self.assertEqual('HEADLESS_RENDER_V1', manifest['resource_profile'])
        self.assertEqual('OFF', manifest['network'])
        self.assertEqual(hashlib.sha256(recipe.bundle[0][1]).hexdigest(), manifest['bundle']['index.html']['sha256'])
        self.assertNotIn('expected_text', manifest)
        self.assertEqual(recipe.digest, hashlib.sha256(recipe.manifest_bytes()).hexdigest())
        self.assertNotEqual(recipe.digest, self.recipe(expected_text='Different trusted oracle').digest)

    def test_recipe_inputs_pin_existing_cdp_code_and_never_send_expected_answers_to_guest(self):
        recipe = self.recipe()
        spec = recipe.recipe_spec()
        self.assertEqual({'files', 'expected'}, set(spec))
        self.assertIn('chrome_pipe.py', spec['files'])
        self.assertIn(b'class Pipe:', spec['files']['chrome_pipe.py'])
        guest = json.loads(spec['files']['render.json'])
        self.assertNotIn('expected_text', guest)
        self.assertNotIn('expected_title', guest)
        self.assertEqual({'render-executed.txt': b'RENDER_PROCESS_FINISHED\n'}, spec['expected'])

    def test_bundle_rejects_arbitrary_paths_scripts_and_hidden_files(self):
        self.module()
        for name in ('../index.html', '/index.html', '.env', 'postinstall.sh', 'recipe.py', 'sub/index.html'):
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, 'RENDER_BUNDLE'):
                self.recipe(bundle=(('index.html', b'<p>Fixture</p>'), (name, b'fixture')))

    def test_duplicate_mutable_and_sensitive_bundles_are_refused(self):
        self.module()
        cases = [ [('index.html', b'<p>Fixture</p>')],
                  (('index.html', b'a'), ('index.html', b'b')),
                  (('index.html', b'ghp_' + b'A' * 36),) ]
        for bundle in cases:
            with self.subTest(kind=type(bundle).__name__), self.assertRaises(ValueError):
                self.recipe(bundle=bundle)

    def test_viewport_and_oracle_bounds_are_closed(self):
        self.module()
        for viewport in ((True, 1), (0, 1), (1025, 1), (512, 513), [2, 1]):
            with self.subTest(viewport=viewport), self.assertRaises(ValueError):
                self.recipe(viewport=viewport)
        with self.assertRaises(ValueError):
            self.recipe(expected_text='x' * 2049)

    def test_host_oracle_decodes_png_bytes_before_accepting_visible_render(self):
        recipe = self.recipe()
        result = recipe.verify_observation(self.encoded(self.observation(recipe)))
        self.assertEqual('PASS', result['status'])
        self.assertEqual('NONE', result['authority'])
        self.assertEqual(hashlib.sha256(png()).hexdigest(), result['screenshot']['sha256'])
        self.assertEqual(1, result['screenshot']['visible_ink_pixels'])
        self.assertTrue(result['screenshot']['non_uniform'])

    def test_guest_pass_claim_or_unknown_fields_cannot_replace_render_evidence(self):
        recipe = self.recipe()
        for value in ({'status': 'PASS'}, {**self.observation(recipe), 'status': 'PASS'}):
            with self.subTest(keys=list(value)), self.assertRaisesRegex(ValueError, 'RENDER_OBSERVATION'):
                recipe.verify_observation(self.encoded(value))

    def test_wrong_document_stale_digest_or_console_error_refuses_success(self):
        recipe = self.recipe()
        cases = [ ('recipe_digest', '0' * 64), ('console_errors', 1), ('console_errors', False),
                  ('transport', {'kind': 'TCP', 'network': 'OFF', 'profile': 'FRESH'}) ]
        for key, value in cases:
            observation = self.observation(recipe)
            observation[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                recipe.verify_observation(self.encoded(observation))
        for key, value in (('href', 'https://example.org/'), ('title', 'Wrong'), ('ready_state', 'loading'), ('body_text', 'Wrong')):
            observation = self.observation(recipe)
            observation['document'][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                recipe.verify_observation(self.encoded(observation))

    def test_corrupt_oversized_or_false_screenshot_is_refused(self):
        recipe = self.recipe()
        for raw in (b'not a png', png()[:-1], b'x' * 8193):
            observation = self.observation(recipe)
            observation['screenshot_base64'] = base64.b64encode(raw).decode()
            with self.subTest(size=len(raw)), self.assertRaises(ValueError):
                recipe.verify_observation(self.encoded(observation))

    def test_duplicate_json_keys_and_nonfinite_values_are_denied(self):
        recipe = self.recipe()
        for raw in (b'{"schema":1,"schema":2}', b'{"console_errors":NaN}'):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                recipe.verify_observation(raw)
