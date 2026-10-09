#!/usr/bin/env python3
"""Offline submission-evidence admission. This never submits or authorizes effects.

A local hash establishes integrity, not external truth. Human-supplied external
receipts still require independent review before publication. No credentials,
provider transport or network are used.
"""
import argparse
from datetime import datetime,timezone
import hashlib
import importlib.util
import ipaddress
import json
from pathlib import Path
import re
import stat
import subprocess
from urllib.parse import urlsplit

MANDATORY=('nebius_runtime','nvidia_model','personal_ai_track','significant_update','public_repo_mit','readme_setup','demo_url','video','feedback','judging_availability','ip_license','secret_audit','devpost_receipt')
MODEL='nvidia/Nemotron-3_5-Lightning'
_scan_spec=importlib.util.spec_from_file_location('unchanged_secret_scan',Path(__file__).with_name('check_changed_secrets.py'))
_scanner=importlib.util.module_from_spec(_scan_spec);_scan_spec.loader.exec_module(_scanner)
STATUSES={'VERIFIED','PARTIAL','BLOCKED_EXTERNAL','UNKNOWN'}
FORBIDDEN={'approval_token','effect_warrant','private_key','api_key','access_token','password','can_execute','permission_granted'}

def _need(ok):
    if not ok:raise ValueError('INVALID_EVIDENCE')
def _hex(value,n):return type(value) is str and re.fullmatch('[0-9a-f]{'+str(n)+'}',value) is not None

def _unique(items):
    result={}
    for key,value in items:
        _need(key not in result);result[key]=value
    return result

def _claims(value):
    if type(value) is dict:
        _need(not (set(value)&FORBIDDEN))
        for v in value.values():_claims(v)
    elif type(value) is list:
        for v in value:_claims(v)

def _read(root,relative):
    path=Path(relative)
    _need(type(relative) is str and not path.is_absolute() and bool(path.parts)
          and all(not p.startswith('.') and p not in ('ssh','gnupg','credentials') for p in path.parts)
          and path.suffix=='.json')
    current=root
    for part in path.parts:
        current=current/part;_need(not current.is_symlink())
    info=current.stat();_need(stat.S_ISREG(info.st_mode) and info.st_size<=65536)
    raw=current.read_bytes();_need(len(raw)<=65536 and not _scanner.scan_text(raw.decode("utf-8")))
    return raw,json.loads(raw,object_pairs_hook=_unique)

def _public_url(value,hosts=None):
    if type(value) is not str or len(value)>2048:return False
    u=urlsplit(value)
    try:
        port=u.port
    except ValueError:return False
    if port not in (None,443) or u.netloc.endswith(':'):return False
    if u.scheme!='https' or not u.hostname or u.username or u.password:return False
    host=u.hostname.lower().rstrip(".")
    if host in ('localhost','example.org','example.com','example.net','invalid','test','example') or host.endswith(('.localhost','.local','.invalid','.test','.example','.example.org','.example.com','.example.net')):return False
    try:
        if not ipaddress.ip_address(host).is_global:return False
    except ValueError:
        if (not re.fullmatch(r"[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?",host)
                or not re.fullmatch(r"[a-z]{2,63}",host.rsplit(".",1)[-1]) or "." not in host):return False
    return hosts is None or host in hosts

def _details(key,d):
    fields={
        'nebius_runtime':{'mode','provider','model','finish_reason','fallback','product_flow','provider_request_id','authority','transport_scope','live_validated','live_calls','execution_authority'},
        'nvidia_model':{'model','source_url','license'},
        'personal_ai_track':{'track','owner_scoped_memory','human_only_effect_approval','replay_verified'},
        'significant_update':{'since','statement_sha256','git_change_manifest_sha256'},
        'public_repo_mit':{'url','visibility','license','published_sha'},
        'readme_setup':{'setup_test','setup_manifest_sha256'},
        'demo_url':{'url','access','observed_status','mode'},
        'video':{'url','duration_seconds','spoken_names'},
        'feedback':{'draft_sha256','complete'},
        'judging_availability':{'through','access','human_undertaking_ref'},
        'ip_license':{'human_review','review_manifest_sha256','unresolved_items'},
        'secret_audit':{'tracked_scan','history_scan','unresolved_findings','scan_manifest_sha256'},
        'devpost_receipt':{'platform','state','receipt_id','project_url'}}
    _need(type(d) is dict and set(d)==fields[key]);_claims(d)
    if key=='nebius_runtime':
        _need(d.get('mode')=='LIVE' and d.get('provider')=='nebius' and d.get('model')==MODEL
              and d.get('finish_reason')=='stop' and d.get('fallback') is False and d.get('authority')=='NONE'
              and d.get('transport_scope')=='LIVE' and d.get('live_validated') is True
              and type(d.get('live_calls')) is int and d['live_calls']==1 and d.get('execution_authority') is False
              and d.get('product_flow')=='PERSONAL_AI' and type(d.get('provider_request_id')) is str and bool(d['provider_request_id']))
    elif key=='nvidia_model':_need(d.get('model')==MODEL and _public_url(d.get('source_url'),{'huggingface.co','build.nvidia.com','nvidia.com'}) and d.get('license')=='OpenMDW-1.1')
    elif key=='personal_ai_track':_need(d.get('track')=='Personal AI' and all(d.get(k) is True for k in ('owner_scoped_memory','human_only_effect_approval','replay_verified')))
    elif key=='significant_update':_need(d.get('since')=='2026-08-26' and _hex(d.get('statement_sha256'),64) and _hex(d.get('git_change_manifest_sha256'),64))
    elif key=='public_repo_mit':_need(_public_url(d.get('url'),{'github.com','gitlab.com','bitbucket.org'}) and d.get('visibility')=='PUBLIC' and d.get('license')=='MIT' and _hex(d.get('published_sha'),40))
    elif key=='readme_setup':_need(d.get('setup_test')=='PASS' and _hex(d.get('setup_manifest_sha256'),64))
    elif key=='demo_url':_need(_public_url(d.get('url')) and d.get('access')=='FREE_UNRESTRICTED' and type(d.get('observed_status')) is int and d['observed_status']==200 and d.get('mode')=='LIVE_PROVIDER_FIXTURE_TARGET')
    elif key=='video':_need(_public_url(d.get('url'),{'www.youtube.com','youtube.com','youtu.be'}) and type(d.get('duration_seconds')) in (int,float) and 0<d['duration_seconds']<180 and d.get('spoken_names')==['Nebius Token Factory','NVIDIA Nemotron'])
    elif key=='feedback':_need(d.get('complete') is True and _hex(d.get('draft_sha256'),64))
    elif key=='judging_availability':
        through=datetime.fromisoformat(d['through']);_need(through.tzinfo is not None and through>=datetime(2026,12,15,20,tzinfo=timezone.utc)
            and d.get('access')=='FREE_UNRESTRICTED' and type(d.get('human_undertaking_ref')) is str and bool(d['human_undertaking_ref']))
    elif key=='ip_license':_need(d.get('human_review')=='PASS' and type(d.get('unresolved_items')) is int and d['unresolved_items']==0 and _hex(d.get('review_manifest_sha256'),64))
    elif key=='secret_audit':_need(d.get('tracked_scan')=='PASS' and d.get('history_scan')=='PASS' and type(d.get('unresolved_findings')) is int and d['unresolved_findings']==0 and _hex(d.get('scan_manifest_sha256'),64))
    elif key=='devpost_receipt':_need(d.get('platform')=='Devpost' and d.get('state')=='Submitted' and type(d.get('receipt_id')) is str and bool(d['receipt_id']) and _public_url(d.get('project_url'),{'devpost.com','nebiusglobalaihackathon.devpost.com'}))

def validate(matrix,root,*,candidate_sha):
    blockers=[];checked=[]
    try:
        _need(type(matrix) is dict and set(matrix)=={'schema','candidate_sha','requirements'} and matrix['schema']=='aioa.nebius-requirements.v1')
        _need(_hex(candidate_sha,40) and matrix['candidate_sha']==candidate_sha)
        rows=matrix['requirements'];_need(type(rows) is list and len(rows)==len(MANDATORY))
        _need(all(type(r) is dict for r in rows) and {r['id'] for r in rows}==set(MANDATORY))
        root=Path(root);_need(root.is_dir() and not root.is_symlink());_claims(matrix)
        for row in rows:
            key=row['id']
            try:
                _need(set(row)=={'id','status','evidence_refs'} and row['status'] in STATUSES and row['status']=='VERIFIED')
                refs=row['evidence_refs'];_need(type(refs) is list and 1<=len(refs)<=8)
                for ref in refs:
                    _need(type(ref) is dict and set(ref)=={'path','sha256'} and _hex(ref['sha256'],64))
                    raw,evidence=_read(root,ref['path']);_need(hashlib.sha256(raw).hexdigest()==ref['sha256'])
                    _need(type(evidence) is dict and set(evidence)=={'schema','requirement_id','candidate_sha','status','details'})
                    _need(evidence['schema']=='aioa.nebius-submission-evidence.v1' and evidence['requirement_id']==key
                          and evidence['candidate_sha']==candidate_sha and evidence['status']=='PASS')
                    _details(key,evidence['details'])
                    if key=='public_repo_mit':_need(evidence['details']['published_sha']==candidate_sha)
                checked.append(key)
            except (ValueError,KeyError,TypeError,OSError,OverflowError):blockers.append(key)
    except (ValueError,KeyError,TypeError,OSError):blockers=['INVALID_MATRIX_OR_CANDIDATE']
    return {'schema':'aioa.nebius-submission-preflight.v1','status':'BLOCKED' if blockers else 'READY_TO_SUBMIT',
            'blockers':blockers,'validated_requirements':checked,'authority':'NONE','submission_performed':False,
            'network_calls':0,'external_truth':'REFERENCED_EVIDENCE_REQUIRES_INDEPENDENT_HUMAN_REVIEW'}

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--root',type=Path,default=Path(__file__).resolve().parents[1]);p.add_argument('--matrix',default='docs/nebius/NEBIUS_HACKATHON_REQUIREMENTS_MATRIX.json');a=p.parse_args()
    try:
        _,matrix=_read(a.root,a.matrix)
        sha=subprocess.check_output(['git','-C',str(a.root),'rev-parse','HEAD'],text=True,timeout=5).strip()
        report=validate(matrix,a.root,candidate_sha=sha)
    except (OSError,ValueError,subprocess.SubprocessError):report={'status':'BLOCKED','blockers':['INVALID_MATRIX_OR_REPOSITORY'],'authority':'NONE','submission_performed':False}
    print(json.dumps(report,sort_keys=True));return 0 if report['status']=='READY_TO_SUBMIT' else 1
if __name__=='__main__':raise SystemExit(main())
