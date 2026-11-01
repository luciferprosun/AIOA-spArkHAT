"""U2 real fixture files/processes, using the existing Linux sandbox broker."""
import importlib
import tempfile
from pathlib import Path
import unittest


class WorkspaceRecipeTests(unittest.TestCase):
    def api(self):
        api = importlib.import_module('runtime.mission.project_recipe')
        self.assertTrue(callable(getattr(api, 'SensorBridgePlan', None)),
                        'registered SensorBridge recipe missing')
        return api

    def test_plan_pins_sources_and_exact_create_append_rename_manifest(self):
        api = self.api(); plan = api.SensorBridgePlan('fixture:sensorbridge')
        self.assertEqual('NONE', plan.authority)
        self.assertEqual({'sensorbridge.py', 'test_sensorbridge.py', 'README.md'},
                         set(plan.files()))
        spec = plan.recipe_spec(api.ProjectSeed('fixture:sensorbridge', 0, None))
        self.assertIn('recipe.py', spec['files'])
        self.assertIn('test-log.txt', spec['expected'])
        self.assertIn(b'PASS 5', spec['expected']['test-log.txt'])

    def test_no_user_absolute_path_or_existing_revision_can_be_selected(self):
        api = self.api()
        for name in ('/home/l', '../escape', 'fixture:../escape', 'fixture:x/y'):
            with self.subTest(name=name), self.assertRaises(ValueError): api.SensorBridgePlan(name)
        plan = api.SensorBridgePlan('fixture:sensorbridge')
        with self.assertRaises(ValueError): plan.recipe_spec(api.ProjectSeed('fixture:sensorbridge', 1, b'user work'))

    def test_preparation_is_host_only_pins_system_runtime_without_installing(self):
        api = self.api()
        self.assertTrue(callable(getattr(api, 'prepare_sensorbridge_sandbox', None)))
        with tempfile.TemporaryDirectory() as temp:
            config = api.prepare_sensorbridge_sandbox(Path(temp)/'prepared', workspace='workspace-fixture')
            self.assertEqual('OFF', config.registry.recipes[0].payload('w','t','s')['network_profile'])
            self.assertEqual({'recipe:sensorbridge-v1'}, {r.recipe_id for r in config.registry.recipes})
            self.assertTrue(all(Path(v['snapshot']).is_relative_to(Path(temp)) for v in config.runtime().values()))


if __name__ == '__main__': unittest.main()
