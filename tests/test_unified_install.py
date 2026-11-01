"""U4 exact project-only proposal; offline artifact readback is never install."""
import hashlib
import importlib
import importlib.util
import os
from pathlib import Path
import tempfile
import unittest


class InstallContractTests(unittest.TestCase):
    def api(self):
        self.assertIsNotNone(importlib.util.find_spec('runtime.mission.install_plan'),
                             'typed project dependency contract missing')
        return importlib.import_module('runtime.mission.install_plan')

    def payload(self):
        return {'schema':'aioa.dependency-plan.v1','manager':'pip','package':'aioa-offline-fixture',
            'version':'1.0.0','artifact_sha256':hashlib.sha256(b'offline-wheel-fixture').hexdigest(),
            'registry':'https://pypi.org/simple','license':'MIT','workspace':'fixture:sensorbridge',
            'venv_ref':'workspace:.venv','network':'OFF','timeout_seconds':20,
            'memory_bytes':268435456,'max_output_bytes':8192}

    def test_exact_plan_records_license_resources_and_disables_system_install(self):
        plan=self.api().DependencyInstallPlan.parse(self.payload())
        preview=plan.preview()
        self.assertEqual('NEEDS_HOST_APPROVAL',preview['approval_status'])
        self.assertEqual('DENY',preview['system_install']);self.assertFalse(preview['install_enabled'])
        self.assertEqual('MIT',preview['plan']['license'])

    def test_shell_absolute_paths_unpinned_versions_and_unknown_registry_deny(self):
        api=self.api()
        for key,value in (('manager','apt'),('version','latest'),('version','>=1'),('package','x;id'),
            ('registry','https://evil.invalid'),('workspace','/home/l'),('venv_ref','/usr'),
            ('license',''),('network','OPEN_WORLD'),('memory_bytes',2**40),('approved',True)):
            with self.subTest(key=key,value=value),self.assertRaises(ValueError):
                api.DependencyInstallPlan.parse({**self.payload(),key:value})

    def test_offline_readback_verifies_actual_fixture_bytes_without_claiming_install(self):
        api=self.api();plan=api.DependencyInstallPlan.parse(self.payload())
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);root.chmod(0o700);(root/'artifact.whl').write_bytes(b'offline-wheel-fixture')
            adapter=api.OfflineInstallerAdapter(root)
            result=adapter.inspect(plan,'artifact.whl')
            self.assertEqual('OFFLINE_FAKE_INSTALLER',result['mode'])
            self.assertFalse(result['installed']);self.assertTrue(result['artifact_readback_verified'])
            (root/'artifact.whl').write_bytes(b'tampered')
            with self.assertRaises(ValueError):adapter.inspect(plan,'artifact.whl')
            with self.assertRaises(ValueError):adapter.dispatch(plan)

    def test_symlink_and_hardlink_artifacts_deny(self):
        api=self.api();plan=api.DependencyInstallPlan.parse(self.payload())
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);root.chmod(0o700);(root/'real').write_bytes(b'offline-wheel-fixture')
            (root/'link').symlink_to(root/'real');os.link(root/'real',root/'hard')
            for path in ('link','hard','../real'):
                with self.subTest(path=path),self.assertRaises((ValueError,OSError)):
                    api.OfflineInstallerAdapter(root).inspect(plan,path)

    def test_proposal_uses_same_core_mission_records_and_cannot_run(self):
        self.api()
        from runtime.meta_hackathon.runtime_adapter import OfflineMetaComposition
        from runtime.core_admission import Capability
        with tempfile.TemporaryDirectory() as temp:
            host=OfflineMetaComposition(Path(temp),source_probe=lambda:('1'*40,'a'*64))
            self.addCleanup(host.close)
            self.assertTrue(callable(getattr(host.missions,'propose_install',None)),'same-Core installer proposal port missing')
            reader=host.core.local_operator(Capability.READ)
            view=host.missions.propose_install(self.payload(),'e'*32,reader)
            self.assertEqual('DEPENDENCY_INSTALL',view['operation']['operation_class'])
            self.assertFalse(view['install_plan']['install_enabled'])
            self.assertFalse(view['permissions']['install'])
            with self.assertRaises(ValueError):host.missions.run_agent(view['task_id'],view['preview_digest'],host.core.local_operator(Capability.OWNER_APPROVAL))
            host.close()


if __name__=='__main__':unittest.main()
