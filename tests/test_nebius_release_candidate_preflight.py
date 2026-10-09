import importlib.util,json,tempfile,unittest
from pathlib import Path
from unittest import mock
SCRIPT=Path(__file__).resolve().parents[1]/'scripts/nebius_release_candidate_preflight.py'
spec=importlib.util.spec_from_file_location('rc',SCRIPT);rc=importlib.util.module_from_spec(spec);spec.loader.exec_module(rc)
SHA='a'*40; HEAD='b'*40
class T(unittest.TestCase):
 def setUp(self):
  self.t=tempfile.TemporaryDirectory();self.addCleanup(self.t.cleanup);self.root=Path(self.t.name)
  for p in ['docs/release','docs/integration','docs/nebius','docs/security']:(self.root/p).mkdir(parents=True,exist_ok=True)
  manifest={'prepared_from_sha':SHA,'binding_scope':'PRE_COMMIT_BASIS','exact_post_commit_candidate_receipt':'REQUIRED_EXTERNAL','blocks':{f'{i:02d}':('BLOCKED_EXTERNAL' if i in (10,11) else 'PASS_LOCAL') for i in range(1,15)},'main_integration_candidate':'YES','main_integration_ready':'NO','live_provider_validation':'REQUIRED','public_judge_deploy':'REQUIRED','devpost_submission':'REQUIRED'}
  roadmap={'basis_sha':SHA,'basis_scope':'PRE_COMMIT_BASIS'}
  ready={'audited_candidate_sha':SHA,'audit_scope':'PRE_COMMIT_BASIS_MECHANICS','MAIN_INTEGRATION_READY':'NO'}
  live={'prepared_from_sha':SHA,'exact_candidate_binding_required_before_live':True,'live_validation_performed':False,'calls_authorized':0,'one_call_only':True,'retry':False,'fallback':False,'target':'FIXTURE_ONLY','authority':'ADVISORY_ONLY'}
  ids=['nebius_runtime','nvidia_model','personal_ai_track','significant_update','public_repo_mit','readme_setup','demo_url','video','feedback','judging_availability','ip_license','secret_audit','devpost_receipt']
  matrix={'candidate_sha':SHA,'requirements':[{'id':i,'status':('BLOCKED_EXTERNAL' if i in rc.EXTERNAL else 'PARTIAL'),'evidence_refs':[]} for i in ids]}
  for p,d in [('docs/release/NEBIUS_RELEASE_CANDIDATE.json',manifest),('docs/integration/NEBIUS_ROADMAP_STATUS.json',roadmap),('docs/integration/MAIN_INTEGRATION_READINESS.json',ready),('docs/nebius/LIVE_VALIDATION_PLAN.json',live),('docs/nebius/NEBIUS_HACKATHON_REQUIREMENTS_MATRIX.json',matrix)]:(self.root/p).write_text(json.dumps(d))
  for p in ['docs/release/NEBIUS_RELEASE_CANDIDATE.md','docs/release/START_HERE.md','docs/nebius/LIVE_VALIDATION_PLAN.md','docs/nebius/JUDGE_DEPLOYMENT_PACKAGE.md','docs/nebius/JUDGE_DEPLOYMENT_CHECKLIST.md','docs/security/DEPENDENCY_LICENSE_INVENTORY.md']:(self.root/p).write_text('x')
 def evaluate(self):
  def fakegit(root,*args):
   if args==('rev-parse','HEAD'): return HEAD
   raise AssertionError(args)
  with mock.patch.object(rc,'git',side_effect=fakegit), mock.patch.object(rc.subprocess,'run') as run:
   run.return_value.returncode=0
   return rc.validate(self.root)
 def test_valid(self): self.assertEqual(self.evaluate()['status'],'PASS_LOCAL_PREPARATION')
 def test_self_binding_missing_blocks(self):
  p=self.root/'docs/release/NEBIUS_RELEASE_CANDIDATE.json';d=json.loads(p.read_text());d['binding_scope']='FINAL_SELF_SHA';p.write_text(json.dumps(d));self.assertIn('manifest_non_self_referential',self.evaluate()['blockers'])
 def test_live_performed_blocks(self):
  p=self.root/'docs/nebius/LIVE_VALIDATION_PLAN.json';d=json.loads(p.read_text());d['live_validation_performed']=True;p.write_text(json.dumps(d));self.assertIn('no_live_call_claim',self.evaluate()['blockers'])
 def test_main_ready_blocks(self):
  p=self.root/'docs/integration/MAIN_INTEGRATION_READINESS.json';d=json.loads(p.read_text());d['MAIN_INTEGRATION_READY']='YES';p.write_text(json.dumps(d));self.assertIn('main_ready_no',self.evaluate()['blockers'])
 def test_external_verified_blocks(self):
  p=self.root/'docs/nebius/NEBIUS_HACKATHON_REQUIREMENTS_MATRIX.json';d=json.loads(p.read_text());next(x for x in d['requirements'] if x['id']=='demo_url')['status']='VERIFIED';p.write_text(json.dumps(d));self.assertIn('external_rows_blocked',self.evaluate()['blockers'])
 def test_unknown_status_blocks(self):
  p=self.root/'docs/release/NEBIUS_RELEASE_CANDIDATE.json';d=json.loads(p.read_text());d['blocks']['08']='MAGIC';p.write_text(json.dumps(d));self.assertIn('block_statuses_known',self.evaluate()['blockers'])
if __name__=='__main__': unittest.main()
