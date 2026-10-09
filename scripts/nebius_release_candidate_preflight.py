#!/usr/bin/env python3
"""Fail-closed local release-candidate preparation consistency check.

Checked-in preparation docs deliberately bind an ancestor basis SHA, not their own
future commit SHA. Exact post-commit candidate binding must be sealed externally.
This tool never calls providers, deploys, submits, or grants authority.
"""
import argparse,json,re,subprocess
from pathlib import Path
HEX40=re.compile(r'^[0-9a-f]{40}$')
ALLOWED={'PASS_IMPLEMENTED','PASS_LOCAL','PASS_LOCAL_FIXTURE','PASS_LOCAL_SEALED','PARTIAL_BY_DESIGN','BLOCKED_EXTERNAL','DEFERRED_POST_SUBMISSION','SHADOW','SPEC_ONLY'}
EXTERNAL={'public_repo_mit','demo_url','video','judging_availability','ip_license','devpost_receipt'}
def load(p):
    d=json.loads(Path(p).read_text())
    if type(d) is not dict: raise ValueError('NOT_OBJECT')
    return d
def git(root,*args):
    return subprocess.check_output(['git','-C',str(root),*args],text=True,timeout=5).strip()
def validate(root):
    root=Path(root); h=git(root,'rev-parse','HEAD')
    m=load(root/'docs/release/NEBIUS_RELEASE_CANDIDATE.json')
    r=load(root/'docs/integration/NEBIUS_ROADMAP_STATUS.json')
    i=load(root/'docs/integration/MAIN_INTEGRATION_READINESS.json')
    l=load(root/'docs/nebius/LIVE_VALIDATION_PLAN.json')
    x=load(root/'docs/nebius/NEBIUS_HACKATHON_REQUIREMENTS_MATRIX.json')
    basis=m.get('prepared_from_sha')
    c={}
    c['head_format']=bool(HEX40.fullmatch(h))
    c['basis_format']=bool(HEX40.fullmatch(basis or ''))
    try: c['basis_is_ancestor']=subprocess.run(['git','-C',str(root),'merge-base','--is-ancestor',basis,h],timeout=5).returncode==0
    except Exception: c['basis_is_ancestor']=False
    c['manifest_non_self_referential']=m.get('binding_scope')=='PRE_COMMIT_BASIS' and m.get('exact_post_commit_candidate_receipt')=='REQUIRED_EXTERNAL'
    c['roadmap_same_basis']=r.get('basis_sha')==basis and r.get('basis_scope')=='PRE_COMMIT_BASIS'
    c['readiness_same_basis']=i.get('audited_candidate_sha')==basis and i.get('audit_scope')=='PRE_COMMIT_BASIS_MECHANICS'
    c['live_same_basis']=l.get('prepared_from_sha')==basis and l.get('exact_candidate_binding_required_before_live') is True
    c['matrix_same_basis']=x.get('candidate_sha')==basis and x.get('binding_scope')=='PREPARATION_BASELINE_NOT_FINAL_SELF_SHA'
    b=m.get('blocks')
    c['blocks_complete']=type(b) is dict and set(b)=={f'{n:02d}' for n in range(1,15)}
    c['block_statuses_known']=c['blocks_complete'] and all(v in ALLOWED for v in b.values())
    c['main_candidate_yes']=m.get('main_integration_candidate')=='YES'
    c['main_ready_no']=m.get('main_integration_ready')=='NO' and i.get('MAIN_INTEGRATION_READY')=='NO'
    c['no_live_call_claim']=l.get('live_validation_performed') is False and l.get('calls_authorized')==0
    c['one_call_plan']=l.get('one_call_only') is True and l.get('retry') is False and l.get('fallback') is False
    c['fixture_target']=l.get('target')=='FIXTURE_ONLY'
    c['advisory_only']=l.get('authority')=='ADVISORY_ONLY'
    c['external_gates_explicit']=all(m.get(k)=='REQUIRED' for k in ('live_provider_validation','public_judge_deploy','devpost_submission'))
    rows=x.get('requirements');c['matrix_rows']=type(rows) is list and all(type(q) is dict for q in rows)
    byid={q.get('id'):q for q in rows} if c['matrix_rows'] else {}
    c['external_rows_blocked']=all(byid.get(k,{}).get('status')=='BLOCKED_EXTERNAL' for k in EXTERNAL)
    docs=['docs/release/NEBIUS_RELEASE_CANDIDATE.md','docs/release/START_HERE.md','docs/nebius/LIVE_VALIDATION_PLAN.md','docs/nebius/JUDGE_DEPLOYMENT_PACKAGE.md','docs/nebius/JUDGE_DEPLOYMENT_CHECKLIST.md','docs/security/DEPENDENCY_LICENSE_INVENTORY.md']
    c['required_docs_present']=all((root/p).is_file() for p in docs)
    blockers=[k for k,v in c.items() if not v]
    return {'schema':'aioa.nebius-release-candidate-preflight.v2','current_head':h,'prepared_from_sha':basis,'status':'PASS_LOCAL_PREPARATION' if not blockers else 'BLOCKED','checks':c,'blockers':blockers,'exact_post_commit_candidate_receipt_required':True,'authority':'NONE','provider_calls':0,'deployment_performed':False,'submission_performed':False,'main_mutated':False}
def main():
    a=argparse.ArgumentParser();a.add_argument('--root',type=Path,default=Path(__file__).resolve().parents[1]);o=a.parse_args()
    try: rep=validate(o.root)
    except Exception as e: rep={'schema':'aioa.nebius-release-candidate-preflight.v2','status':'BLOCKED','blockers':['INVALID_REPOSITORY_OR_DOCUMENTS'],'error_type':type(e).__name__,'authority':'NONE','provider_calls':0,'deployment_performed':False,'submission_performed':False,'main_mutated':False}
    print(json.dumps(rep,sort_keys=True));return 0 if rep['status']=='PASS_LOCAL_PREPARATION' else 1
if __name__=='__main__': raise SystemExit(main())
