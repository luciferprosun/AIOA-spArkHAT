"""Actual legacy entry points must refuse effects before handlers or prompts."""
from pathlib import Path
from types import SimpleNamespace
import hashlib
import tempfile
import unittest
from unittest.mock import patch
from tools.executor import ExecutionEngine, ToolSpec
from tools.memory import MemoryStore
from commands.local_commands import build_command_registry


class PublicToolBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.project=Path(self.tmp.name)/'project';self.project.mkdir()
        self.memory=MemoryStore(self.project,self.project)
        self.engine=ExecutionEngine(self.project,self.memory)

    def test_ungranted_actual_filesystem_write_does_not_create_target(self):
        target=Path(self.tmp.name)/'outside'
        result=self.engine.execute({'action':'create_folder','path':str(target),
            'approved':True,'requires_confirmation':False},require_approval=False)
        self.assertFalse(result['success']);self.assertFalse(target.exists())
        self.assertEqual('UNSUPPORTED_EFFECT_ROUTE',result['error'])

    def test_scan_is_a_write_and_never_creates_report(self):
        result=self.engine.execute({'action':'scan_project','path':str(self.project)},require_approval=False)
        self.assertFalse(result['success']);self.assertFalse((self.project/'project_scan.json').exists())

    def test_all_browser_actions_denied_before_lazy_launch(self):
        calls=[]
        for name in list(self.engine.tools):
            if not name.startswith('browser_'):continue
            self.engine.tools[name]=ToolSpec(name,lambda action:calls.append(action) or {'success':True},'spy target')
            result=self.engine.execute({'action':name,'requires_confirmation':False},require_approval=False)
            self.assertFalse(result['success'])
        self.assertEqual([],calls)

    def test_shell_denied_before_prompt_and_process_launch(self):
        calls=[]
        self.engine.tools['shell_execute']=ToolSpec('shell_execute',lambda a:calls.append(a) or {'success':True},'spy')
        with patch.object(self.engine,'_request_approval',side_effect=AssertionError('prompt must not authorize')):
            result=self.engine.execute({'action':'shell_execute','command':'true','requires_confirmation':True})
        self.assertFalse(result['success']);self.assertEqual([],calls)

    def test_scemda_is_denied_before_private_archive_extraction(self):
        registry=build_command_registry();runtime=SimpleNamespace(project_dir=self.project)
        calls=[]
        with patch('commands.local_commands.ensure_scemda_addon',side_effect=lambda *_:calls.append(1)):
            result=registry.execute('/scemda',runtime)
        self.assertNotEqual(0,result.exit_code);self.assertEqual([],calls)
        self.assertFalse((self.project/'addons').exists())

    def test_worker_mutation_denied_but_safe_status_remains(self):
        calls=[];runtime=SimpleNamespace(worker_memory=SimpleNamespace(
            clear_worker_memory=lambda:calls.append(1),summarize_worker_state=lambda:{'safe':'fixture'}))
        registry=build_command_registry()
        self.assertNotEqual(0,registry.execute('/worker clear',runtime).exit_code)
        self.assertEqual(0,registry.execute('/worker memory',runtime).exit_code)
        self.assertEqual([],calls)

    def test_read_without_exact_host_allowlist_denied(self):
        secret=self.project/'private.txt';secret.write_text('PRIVATE_SENTINEL')
        result=self.engine.execute({'action':'read_file','path':'private.txt'},require_approval=False)
        self.assertFalse(result['success']);self.assertNotIn('PRIVATE_SENTINEL',str(result))

    def test_exact_approved_read_and_search_cannot_read_changed_content_or_alias(self):
        import inspect
        self.assertIn('readable_files',inspect.signature(ExecutionEngine).parameters,
                      'No exact public input policy for reads')
        public=self.project/'public.txt';public.write_text('safe public fixture\n')
        engine=ExecutionEngine(self.project,self.memory,
            readable_files={'public.txt':hashlib.sha256(public.read_bytes()).hexdigest()})
        result=engine.execute({'action':'read_file','path':'public.txt'})
        self.assertEqual('safe public fixture\n',result['content'])
        result=engine.execute({'action':'search_in_project','path':'.','pattern':'public'})
        self.assertTrue(result['success']);self.assertEqual(1,len(result['matches']))
        public.write_text('PRIVATE_SENTINEL')
        result=engine.execute({'action':'read_file','path':'public.txt'})
        self.assertFalse(result['success']);self.assertNotIn('PRIVATE_SENTINEL',str(result))

    def test_public_reads_deny_symlink_hardlink_fifo_and_parent_root_alias(self):
        import os
        from tools.admission import PublicFileReads, ReadDenied
        public=self.project/'public.txt';public.write_text('approved')
        digest=hashlib.sha256(public.read_bytes()).hexdigest()
        link=self.project/'link.txt';link.symlink_to(public)
        os.link(public,self.project/'hard.txt');os.mkfifo(self.project/'fifo.txt')
        policy=PublicFileReads(self.project,{n:digest for n in ('public.txt','link.txt','hard.txt','fifo.txt')})
        for name in policy.files:
            with self.subTest(name=name),self.assertRaises(ReadDenied):policy.read(name)
        # Parent symlink must not become an ambient root alias, even for an approved file.
        (self.project/'hard.txt').unlink()
        alias=Path(self.tmp.name)/'alias';alias.symlink_to(self.project,target_is_directory=True)
        child=self.project/'child';child.mkdir();(child/'public.txt').write_text('approved')
        alias_policy=PublicFileReads(alias/'child',{'public.txt':digest})
        with self.assertRaises(ReadDenied):alias_policy.read('public.txt')

    def test_approved_real_read_accepts_atime_only_change(self):
        import os
        from tools.admission import PublicFileReads
        public=self.project/'public.txt';public.write_text('approved')
        policy=PublicFileReads(self.project,{'public.txt':hashlib.sha256(b'approved').hexdigest()})
        fstat=os.fstat;calls=[]
        def changed_access_time(fd):
            original=fstat(fd);fields=list(original)
            fields[7]+=len(calls)+1
            calls.append(1)
            return os.stat_result(fields)
        with patch('tools.admission.os.fstat',side_effect=changed_access_time):
            self.assertEqual('approved',policy.read('public.txt'))
        self.assertEqual(2,len(calls))

    def test_status_explicitly_reports_unsupported_host_effects(self):
        from commands.local_commands import cmd_status
        runtime=SimpleNamespace(memory_store=self.memory,desktop_dir=self.project,
            provider_manager=SimpleNamespace(describe=lambda:'FIXTURE',fallback_order=[]),
            hat_store=SimpleNamespace(active_hat=lambda:None))
        view=cmd_status('',runtime)
        self.assertIn('UNSUPPORTED_EFFECT_ROUTE',view.message)
        self.assertNotIn('local URL bootstrap: enabled',view.message)
