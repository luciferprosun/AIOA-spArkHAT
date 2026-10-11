"""Positive payload inventory and real-filesystem exclusion/security checks."""
import importlib.util,os,subprocess,tempfile,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('deb_builder',ROOT/'scripts/build_deb_candidate.py')
builder=importlib.util.module_from_spec(spec);spec.loader.exec_module(builder)

class DebContentTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        for name in (*builder.LICENSES,'scripts/check_changed_secrets.py'):
            path=self.root/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes((ROOT/name).read_bytes())
        self.names=sorted([*builder.LICENSES,'runtime/main.py','runtime/mission/operator_console.py','lab/archaioa/contracts.py'])
        for name in self.names:
            path=self.root/name;path.parent.mkdir(parents=True,exist_ok=True)
            if name not in builder.LICENSES:path.write_bytes(b'# MIT owned fixture source\nvalue=5\n')
    def inventory(self):return builder.source_inventory(self.root,self.names)
    def add(self,name,raw=b'owned fixture'):
        path=self.root/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(raw)
        self.names=sorted([*self.names,name]);return path

    def test_licensed_owned_source_is_inventoried_with_exact_hash(self):
        inventory=self.inventory();self.assertEqual(len(self.names),len(inventory))
        item=next(i for i in inventory if i['path']=='runtime/main.py')
        self.assertEqual(builder.sha((self.root/'runtime/main.py').read_bytes()),item['sha256'])
        self.assertEqual('MIT',item['license'])

    def test_real_checked_in_allowlist_has_complete_notice_and_core_closure(self):
        names=(ROOT/'packaging/deb_source_allowlist.txt').read_text().splitlines()
        inventory=builder.source_inventory(ROOT,names)
        self.assertGreater(len(inventory),200)
        self.assertEqual(len(names),len(inventory))
        self.assertTrue(all(i['license']=='MIT' for i in inventory))
        self.assertTrue(all(b'/home/l/' not in (ROOT/i['path']).read_bytes()
                            and str(ROOT).encode() not in (ROOT/i['path']).read_bytes()
                            for i in inventory))

    def test_env_and_git_internals_denied(self):
        for name in ('.env','.git/config','runtime/.env'):
            with self.subTest(name=name),self.assertRaises(ValueError):builder.regular_bytes(self.root,name)

    def test_developer_venv_and_user_state_denied(self):
        for name in ('runtime/.venv/bin/python','runtime/venv/config.py','runtime/state/user.py',
                     'runtime/logs/user.py','runtime/screenshots/user.py'):
            with self.subTest(name=name),self.assertRaises(ValueError):builder.regular_bytes(self.root,name)

    def test_archives_knowledge_media_and_tests_cannot_enter_payload(self):
        for name in ('archive/dev.py','runtime/knowledge/source.pdf','runtime/test.pdf','tests/test.py'):
            with self.subTest(name=name),self.assertRaises(ValueError):
                builder.source_inventory(self.root,sorted([*self.names,name]))

    def test_fixture_tokens_and_undeclared_optional_reader_excluded(self):
        for name in ('runtime/critical_loop/fixture.py','runtime/tools/web_reader.py',
                     'runtime/tools/build_rhcsa_library.py'):
            with self.subTest(name=name),self.assertRaisesRegex(ValueError,'SOURCE_NOT_IN_POLICY'):
                builder.source_inventory(self.root,sorted([*self.names,name]))

    def test_file_symlink_denied(self):
        path=self.root/'runtime/main.py';path.unlink();path.symlink_to(self.root/'LICENSE')
        with self.assertRaisesRegex(ValueError,'PACKAGE_SYMLINK_DENIED'):self.inventory()

    def test_parent_directory_symlink_denied(self):
        target=self.root/'owned';target.mkdir();(target/'alias.py').write_bytes(b'value=5')
        (self.root/'runtime/alias').symlink_to(target,target_is_directory=True)
        with self.assertRaisesRegex(ValueError,'PACKAGE_SYMLINK_DENIED'):
            builder.regular_bytes(self.root,'runtime/alias/alias.py')

    def test_hardlink_denied(self):
        os.link(self.root/'runtime/main.py',self.root/'alias.py')
        with self.assertRaisesRegex(ValueError,'PACKAGE_FILE_DENIED'):self.inventory()

    def test_fifo_denied_without_blocking(self):
        path=self.root/'runtime/main.py';path.unlink();os.mkfifo(path)
        with self.assertRaisesRegex(ValueError,'PACKAGE_FILE_DENIED'):self.inventory()

    def test_oversized_source_denied(self):
        (self.root/'runtime/main.py').write_bytes(b'x'*1048577)
        with self.assertRaisesRegex(ValueError,'PACKAGE_FILE_DENIED'):self.inventory()

    def test_secret_looking_source_denied_with_no_value_echo(self):
        canary='ghp_'+'A'*36
        (self.root/'runtime/main.py').write_text('value='+repr(canary))
        with self.assertRaisesRegex(ValueError,'PACKAGE_SECRET_DENIED') as caught:self.inventory()
        self.assertNotIn(canary,str(caught.exception))

    def test_fine_grained_github_and_provider_keys_are_denied(self):
        for canary in ('github_'+'pat_'+'A'*40,'sk-'+'A'*24,'Bearer '+'A'*24):
            (self.root/'runtime/main.py').write_text('value='+repr(canary))
            with self.subTest(kind=canary[:3]),self.assertRaisesRegex(ValueError,'PACKAGE_SECRET_DENIED'):
                self.inventory()

    def test_missing_notice_blocks_inventory(self):
        self.names.remove('LICENSE')
        with self.assertRaisesRegex(ValueError,'LICENSE_CLOSURE_REQUIRED'):self.inventory()

    def test_unknown_license_blocks_inventory(self):
        (self.root/'LICENSE').write_bytes(b'Unknown rights')
        with self.assertRaisesRegex(ValueError,'LICENSE_CLOSURE_REQUIRED'):self.inventory()

    def test_core_module_missing_blocks_closure(self):
        self.names.remove('lab/archaioa/contracts.py')
        with self.assertRaisesRegex(ValueError,'CORE_CLOSURE_REQUIRED'):self.inventory()

    def test_duplicate_and_unsorted_allowlists_denied(self):
        for names in (self.names+['LICENSE'],list(reversed(self.names))):
            with self.assertRaisesRegex(ValueError,'SOURCE_ALLOWLIST'):builder.source_inventory(self.root,names)

    def test_absolute_traversal_and_noncanonical_paths_denied(self):
        for name in ('/etc/passwd','runtime/../LICENSE','runtime//main.py','runtime/main.py/..'):
            with self.subTest(name=name),self.assertRaises(ValueError):builder.regular_bytes(self.root,name)

    def test_dirty_source_cannot_build_or_create_output(self):
        subprocess.run(['/usr/bin/git','init','--quiet',self.root],check=True,capture_output=True,
                       env={'PATH':'/usr/bin:/bin','GIT_CONFIG_GLOBAL':'/dev/null','GIT_CONFIG_NOSYSTEM':'1'})
        output=self.root.parent/(self.root.name+'-output')
        with self.assertRaisesRegex(ValueError,'CLEAN_SOURCE_REQUIRED'):builder.build(self.root,output)
        self.assertFalse(output.exists())

    def test_actual_os_runtime_dependency_closure_is_version_pinned(self):
        records=builder.os_lock();names={p['name'] for p in records}
        self.assertTrue({'python3.12','libpython3.12-stdlib','libc6'}<=names)
        self.assertTrue(all(p['version'] and p['delivery']=='OS_PROVIDED_NOT_BUNDLED' for p in records))
        self.assertTrue(all(p['architecture'] in ('amd64','all') for p in records))
