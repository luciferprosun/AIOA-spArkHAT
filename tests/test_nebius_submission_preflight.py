"""Offline admission is evidence completeness, never publication authority."""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

SCRIPT=Path(__file__).resolve().parents[1]/'scripts/nebius_submission_preflight.py'
spec=importlib.util.spec_from_file_location('submission_check',SCRIPT) if SCRIPT.exists() else None
check=importlib.util.module_from_spec(spec) if spec else None
if check:spec.loader.exec_module(check)
SHA='a'*40
IDS=('nebius_runtime','nvidia_model','personal_ai_track','significant_update','public_repo_mit','readme_setup','demo_url','video','feedback','judging_availability','ip_license','secret_audit','devpost_receipt')

class SubmissionAdmissionTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(check,'Required offline submission validator is absent')
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        self.matrix={'schema':'aioa.nebius-requirements.v1','candidate_sha':SHA,'requirements':[]}
        details={
          'nebius_runtime':{'mode':'LIVE','provider':'nebius','model':'nvidia/Nemotron-3_5-Lightning','finish_reason':'stop','fallback':False,'product_flow':'PERSONAL_AI','provider_request_id':'test-receipt','authority':'NONE','transport_scope':'LIVE','live_validated':True,'live_calls':1,'execution_authority':False},
          'nvidia_model':{'model':'nvidia/Nemotron-3_5-Lightning','source_url':'https://huggingface.co/nvidia/NVIDIA-Nemotron-3.5-Lightning-30B-A3B-BF16','license':'OpenMDW-1.1'},
          'personal_ai_track':{'track':'Personal AI','owner_scoped_memory':True,'human_only_effect_approval':True,'replay_verified':True},
          'significant_update':{'since':'2026-08-26','statement_sha256':'b'*64,'git_change_manifest_sha256':'c'*64},
          'public_repo_mit':{'url':'https://github.com/luciferprosun/AIOA-spArkHAT','visibility':'PUBLIC','license':'MIT','published_sha':SHA},
          'readme_setup':{'setup_test':'PASS','setup_manifest_sha256':'b'*64},
          'demo_url':{'url':'https://judge.aioa-public.org','access':'FREE_UNRESTRICTED','observed_status':200,'mode':'LIVE_PROVIDER_FIXTURE_TARGET'},
          'video':{'url':'https://www.youtube.com/watch?v=test','duration_seconds':165,'spoken_names':['Nebius Token Factory','NVIDIA Nemotron']},
          'feedback':{'draft_sha256':'b'*64,'complete':True},
          'judging_availability':{'through':'2026-12-15T12:00:00-08:00','access':'FREE_UNRESTRICTED','human_undertaking_ref':'owner-reviewed-plan'},
          'ip_license':{'human_review':'PASS','review_manifest_sha256':'b'*64,'unresolved_items':0},
          'secret_audit':{'tracked_scan':'PASS','history_scan':'PASS','unresolved_findings':0,'scan_manifest_sha256':'b'*64},
          'devpost_receipt':{'platform':'Devpost','state':'Submitted','receipt_id':'test-receipt','project_url':'https://nebiusglobalaihackathon.devpost.com/submissions/test'}}
        for key in IDS:
            receipt={'schema':'aioa.nebius-submission-evidence.v1','requirement_id':key,'candidate_sha':SHA,'status':'PASS','details':details[key]}
            path=self.root/('evidence/'+key+'.json');path.parent.mkdir(exist_ok=True);path.write_text(json.dumps(receipt))
            self.matrix['requirements'].append({'id':key,'status':'VERIFIED','evidence_refs':[{'path':str(path.relative_to(self.root)),'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}]})
    def verify(self):return check.validate(self.matrix,self.root,candidate_sha=SHA)
    def row(self,key):return next(r for r in self.matrix['requirements'] if r['id']==key)
    def mutate_receipt(self,key,field,value):
        row=self.row(key);p=self.root/row['evidence_refs'][0]['path'];r=json.loads(p.read_text());r['details'][field]=value;p.write_text(json.dumps(r));row['evidence_refs'][0]['sha256']=hashlib.sha256(p.read_bytes()).hexdigest()
    def test_complete_typed_evidence(self):self.assertEqual(self.verify()['status'],'READY_TO_SUBMIT')
    def test_missing_mandatory_cannot_be_hidden(self):self.matrix['requirements'].pop();self.assertEqual(self.verify()['status'],'BLOCKED')
    def test_partial_is_blocked(self):self.row('demo_url')['status']='PARTIAL';self.assertEqual(self.verify()['status'],'BLOCKED')
    def test_test_transport_never_live(self):self.mutate_receipt('nebius_runtime','transport_scope','TEST');self.assertEqual(self.verify()['status'],'BLOCKED')
    def test_effect_authority_claim_rejected(self):self.mutate_receipt('nebius_runtime','execution_authority',True);self.assertEqual(self.verify()['status'],'BLOCKED')
    def test_invalid_placeholder_hostname(self):self.mutate_receipt('demo_url','url','https://judge.invalid');self.assertEqual(self.verify()['status'],'BLOCKED')
    def test_reserved_hostname_variants_fail_closed(self):
        for url in ('https://example.net','https://judge.invalid.','https://demo.example.org.','https://localhost.','https://judge'):
            with self.subTest(url=url):
                self.mutate_receipt('demo_url','url',url);self.assertEqual(self.verify()['status'],'BLOCKED')
    def test_browser_ipv4_aliases_fail_closed(self):
        for url in ('https://0x7f.1','https://0x7f.0.0.1','https://0177.1','https://2130706433','https://%30x7f.1'):
            with self.subTest(url=url):
                self.mutate_receipt('demo_url','url',url);self.assertEqual(self.verify()['status'],'BLOCKED')
    def test_invalid_or_nonstandard_https_ports_fail_closed(self):
        for url in ('https://github.com:bogus/owner/repo','https://judge.aioa-public.org:999999/','https://judge.aioa-public.org:/','https://judge.aioa-public.org:8443/'):
            with self.subTest(url=url):
                self.mutate_receipt('demo_url','url',url);self.assertEqual(self.verify()['status'],'BLOCKED')
    def test_malformed_receipt_details_fail_closed(self):
        row=self.row('public_repo_mit');p=self.root/row['evidence_refs'][0]['path'];data=json.loads(p.read_text());data['details']=[];p.write_text(json.dumps(data));row['evidence_refs'][0]['sha256']=hashlib.sha256(p.read_bytes()).hexdigest();self.assertEqual(self.verify()['status'],'BLOCKED')
    def test_hash_tampering(self):self.row('feedback')['evidence_refs'][0]['sha256']='d'*64;self.assertEqual(self.verify()['status'],'BLOCKED')
    def test_fixture_never_live(self):self.mutate_receipt('nebius_runtime','mode','FIXTURE');self.assertEqual(self.verify()['status'],'BLOCKED')
    def test_incomplete_provider_completion(self):self.mutate_receipt('nebius_runtime','finish_reason','length');self.assertEqual(self.verify()['status'],'BLOCKED')
    def test_loopback_not_judge_url(self):self.mutate_receipt('demo_url','url','http://127.0.0.1:4311');self.assertEqual(self.verify()['status'],'BLOCKED')
    def test_video_180_seconds_not_under_three_minutes(self):self.mutate_receipt('video','duration_seconds',180);self.assertEqual(self.verify()['status'],'BLOCKED')
    def test_draft_not_submitted_receipt(self):self.mutate_receipt('devpost_receipt','state','Draft');self.assertEqual(self.verify()['status'],'BLOCKED')
    def test_wrong_candidate(self):self.matrix['candidate_sha']='d'*40;self.assertEqual(self.verify()['status'],'BLOCKED')
    def test_duplicate_unknown_requirement(self):self.matrix['requirements'].append(copy.deepcopy(self.matrix['requirements'][0]));self.assertEqual(self.verify()['status'],'BLOCKED')
    def test_symlink_reference(self):
        p=self.root/'evidence/feedback.json';p.rename(self.root/'evidence/original.json');p.symlink_to(self.root/'evidence/original.json');self.assertEqual(self.verify()['status'],'BLOCKED')
    def test_secret_store_path_never_read(self):self.row('feedback')['evidence_refs'][0]['path']='.env';self.assertEqual(self.verify()['status'],'BLOCKED')
