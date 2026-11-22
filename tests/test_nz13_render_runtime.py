"""Runtime closure parser; no compiler, renderer or package install is executed."""
import importlib
import unittest


class RenderRuntimeClosureTests(unittest.TestCase):
    def module(self):
        try:
            return importlib.import_module('runtime.mission.render_runtime')
        except ModuleNotFoundError as exc:
            self.fail('Missing closed renderer runtime: ' + exc.name)

    def test_dependency_listing_is_normalized_to_exact_shared_library_paths(self):
        parser = self.module().parse_renderer_dependencies
        result = parser(' linux-vdso.so.1 (0x00000001)\n libm.so.6 => /lib/x86_64-linux-gnu/libm.so.6 (0x123)\n /lib64/ld-linux-x86-64.so.2 (0x456)\n')
        self.assertEqual(('/lib/x86_64-linux-gnu/libm.so.6', '/lib64/ld-linux-x86-64.so.2'), result)

    def test_missing_dependency_or_unrecognized_output_refuses_a_partial_closure(self):
        parser = self.module().parse_renderer_dependencies
        for output in ('libmissing.so => not found\n', 'unexpected output\n', '', 'statically linked\n'):
            with self.subTest(output=output), self.assertRaisesRegex(ValueError, 'RENDER_RUNTIME_DEPENDENCY'):
                parser(output)

    def test_user_local_paths_traversal_and_host_executable_dependencies_are_refused(self):
        parser = self.module().parse_renderer_dependencies
        for path in ('/tmp/libx.so', '/usr/local/lib/libx.so', '/home/l/libx.so',
                     '/lib/../home/libx.so', '/lib/x/../../home/libx.so', '/usr/bin/python3'):
            with self.subTest(path=path), self.assertRaisesRegex(ValueError, 'RENDER_RUNTIME_DEPENDENCY'):
                parser('libx.so => ' + path + ' (0x123)\n')

    def test_dependency_count_and_output_size_are_bounded(self):
        parser = self.module().parse_renderer_dependencies
        for output in ('x' * 32769, '\n'.join(f'libx.so => /lib/libx{i:d}.so (0x123)' for i in range(129))):
            with self.assertRaisesRegex(ValueError, 'RENDER_RUNTIME_DEPENDENCY'):
                parser(output)

    def test_fixed_renderer_inventory_excludes_profiles_credentials_and_startup_scripts(self):
        module = self.module()
        self.assertEqual(9, len(module.RENDERER_RUNTIME_FILES))
        self.assertIn('/opt/google/chrome/chrome', module.RENDERER_RUNTIME_FILES)
        self.assertIn('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf', module.RENDERER_RUNTIME_FILES)
        self.assertFalse(any('profile' in path or path.endswith(('.sh', '.pem', '.key'))
                             for path in module.RENDERER_RUNTIME_FILES))

    def test_renderer_builder_requires_an_exact_operator_recipe_before_any_filesystem_work(self):
        module = self.module()
        from pathlib import Path
        from unittest.mock import patch
        with patch.object(module, 'snapshot_renderer_runtime', side_effect=AssertionError('No capture')), \
                self.assertRaisesRegex(ValueError, 'RENDER_OPERATOR_RECIPE_REQUIRED'):
            module.prepare_html_render_sandbox(Path('/unused'), workspace='fixture', recipe={'argv': 'chrome'})

    def test_renderer_builder_rejects_dangling_scratch_link_before_snapshot(self):
        from pathlib import Path
        from tempfile import TemporaryDirectory
        from unittest.mock import patch

        from runtime.mission.render_recipe import HtmlRenderRecipe

        recipe = HtmlRenderRecipe(bundle=(('index.html', b'<p>Fixture</p>'),), viewport=(2, 1),
                                  expected_title='Fixture', expected_text='Fixture')
        module = self.module()
        with TemporaryDirectory() as directory:
            root = Path(directory) / 'scratch'
            root.symlink_to(Path(directory) / 'missing')
            with patch.object(module, 'snapshot_renderer_runtime') as capture:
                capture.side_effect = AssertionError('No capture')
                with self.assertRaisesRegex(ValueError, '^RENDER_PREPARATION_EXISTS$'):
                    module.prepare_html_render_sandbox(root, workspace='fixture', recipe=recipe)
            capture.assert_not_called()
