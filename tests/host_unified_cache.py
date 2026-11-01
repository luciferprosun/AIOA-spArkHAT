"""U8 private immutable sandbox cache, no restart/replay authority."""
from pathlib import Path
import json
import tempfile
import unittest


class SandboxCacheTests(unittest.TestCase):
    def test_home_private_descriptor_roundtrip_keeps_contract_path_guard(self):
        api=self.api()
        from runtime.memory_patch.contracts.serialization import canonical_json_bytes
        from runtime.memory_patch.errors import ContractValidationError
        from runtime.mission.project_recipe import prepare_sensorbridge_sandbox
        with tempfile.TemporaryDirectory(prefix='aioa-cache-host-home-',dir=Path.home()) as temp:
            root=Path(temp);root.chmod(0o700)
            config=prepare_sensorbridge_sandbox(root/'sandbox',workspace='workspace-sensorbridge')
            with self.assertRaises(ContractValidationError):
                canonical_json_bytes({'model_supplied_path':str(root/'private')})
            api.save_host_config(config)
            loaded=api.load_host_config(config.root,trusted_root=root)
            self.assertEqual(config.profile_digest,loaded.profile_digest)
            self.assertEqual(config.runtime(),loaded.runtime())
            self.assertEqual(config.inputs(),loaded.inputs())

    def api(self):
        from runtime.mission import sandbox_linux
        self.assertTrue(callable(getattr(sandbox_linux,'save_host_config',None)),'durable host cache descriptor missing')
        return sandbox_linux

    def test_descriptor_roundtrip_preserves_exact_profile_and_rejects_path_escape(self):
        api=self.api()
        from runtime.mission.project_recipe import prepare_sensorbridge_sandbox
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);root.chmod(0o700)
            config=prepare_sensorbridge_sandbox(root/'sandbox',workspace='workspace-sensorbridge')
            api.save_host_config(config)
            loaded=api.load_host_config(config.root,trusted_root=root)
            self.assertEqual(config.profile_digest,loaded.profile_digest)
            self.assertEqual(config.registry,loaded.registry)
            self.assertEqual(config.inputs(),loaded.inputs())
            path=config.root/'host-config.json';value=json.loads(path.read_text())
            next(iter(value['runtime'].values()))['snapshot']='/etc/passwd'
            path.write_text(json.dumps(value))
            with self.assertRaises(ValueError):api.load_host_config(config.root,trusted_root=root)

    def test_symlink_descriptor_is_rejected(self):
        api=self.api()
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);root.chmod(0o700);config=root/'cache';config.mkdir(mode=0o700)
            (config/'host-config.json').symlink_to('/etc/passwd')
            with self.assertRaises((OSError,ValueError)):api.load_host_config(config,trusted_root=root)


if __name__=='__main__':unittest.main()
