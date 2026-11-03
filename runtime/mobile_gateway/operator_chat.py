"""Same-Core chat operations on the existing UID-authenticated operator port.

Financial approval is private-socket only. The web adapter has a separate closed
allowlist of non-financial operations and must never forward chat_approve.
"""
import secrets
import json
from runtime.core_admission import Capability
from runtime.memory_patch.contracts.serialization import canonical_sha256
from . import wire

READ_OPS=frozenset(('chat_catalog','chat_threads','chat_thread','chat_request','chat_propose','chat_stop','chat_review'))

def dispatch(host,owner,value):
    if not host.chat_enabled:raise wire.MobileError(501)
    host.core.require(owner,Capability.OWNER_APPROVAL,scope=host.missions.scope)
    service=host.missions;reader=host.core.local_operator(Capability.READ);op=value['op']
    fields={'chat_catalog':{'op'},'chat_threads':{'op'},'chat_thread':{'op','thread_id'},
        'chat_request':{'op','request_id'},'chat_review':{'op','request_id'},'chat_stop':{'op','request_id'},
        'chat_propose':{'op','payload'},'chat_approve':{'op','request_id','review_digest'}}
    if op not in fields or set(value)!=fields[op]:raise wire.MobileError(400)
    if op=='chat_catalog':
        return {'schema':'aioa.chat.catalog.v1','provider_id':'meta_model_api','model_id':'muse-spark-1.3',
            'mode':'LIVE_PENDING_EXACT_OWNER_APPROVAL','chat':True,'save_knowledge':False,'max_budget_usd':'0.05',
            'billing_status':'UNVERIFIED','mission_read':'BLOCKED_NATIVE_WORKER_NOT_BOUND',
            'github_write':False,'native_execute':False,'source_sha':host.source[0],'capsule_digest':host.source[1],
            'model_calls':host.model_calls()}
    if op=='chat_threads':return service.chat_threads(reader)
    if op=='chat_thread':return service.chat_thread(value['thread_id'],reader)
    if op=='chat_request':return service.chat_request(value['request_id'],reader)
    if op=='chat_review':return service.chat_review(value['request_id'],reader)
    if op=='chat_stop':return service.chat_stop(value['request_id'],reader)
    if op=='chat_approve':return service.chat_approve(value['request_id'],value['review_digest'],owner)
    payload=value['payload'];device=host.identity.audience
    if type(payload) is not dict:raise wire.MobileError(400)
    threads=service.chat_threads(reader)['threads']
    existing=next((t for t in threads if t['thread_id']==payload.get('thread_id')),None)
    if existing:device=existing['device_id']
    return service.chat_propose(payload,reader,device_id=device,session_id=canonical_sha256(host.instance_id)[:32],
        nonce=secrets.token_hex(16),actor='LINUX_OWNER')

def financial_review(state_dir,request_id,*,approve=False):
    """Explicit native human decision, never a flag inside model/HTTP content."""
    import subprocess
    from runtime.webapp import mobile_operator_client
    from runtime.meta_hackathon.runtime_adapter import _desktop_operator_uid
    if type(request_id) is not str or not wire.HEX32.fullmatch(request_id):raise SystemExit('CHAT_REQUEST_ID_REQUIRED')
    result=mobile_operator_client(state_dir,{'op':'chat_review','request_id':request_id})
    if result.get('ok') is not True:raise SystemExit('CHAT_REVIEW_DENIED_OR_UNKNOWN')
    review=result['data']
    public={k:review[k] for k in ('task_id','request_id','request_digest','source_sha','capsule_digest','model_id',
        'max_budget_usd','cost_estimate_usd','policy_epoch','endpoint','max_attempts','review_digest','prompt','request_payload')}
    if not approve:
        print(json.dumps(public,ensure_ascii=False,indent=2));return
    _desktop_operator_uid()
    text=('AIOA — JEDNA PŁATNA WIADOMOŚĆ META\n\n'+json.dumps(public,ensure_ascii=False,indent=2)+
        '\n\nPotwierdzasz użycie standardowego Meta Model API z maksymalnym kosztem 0.05 USD. '
        'Stan rozliczeń konta pozostaje UNVERIFIED. Jedna próba, bez automatycznego ponowienia. '
        'To nie jest zgoda na narzędzia, GitHub WRITE ani dalsze wiadomości.')
    completed=subprocess.run(['/usr/bin/zenity','--text-info','--title=AIOA: dokładna zgoda na koszt Muse',
        '--width=850','--height=650','--checkbox=Zatwierdzam tylko tę wiadomość i jej limit kosztu',
        '--ok-label=Zatwierdź jedną próbę','--cancel-label=Anuluj','--timeout=180'],
        input=text,text=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=190,check=False)
    if completed.returncode!=0:raise SystemExit('CHAT_OWNER_CANCELLED_NO_CALL')
    result=mobile_operator_client(state_dir,{'op':'chat_approve','request_id':request_id,'review_digest':review['review_digest']})
    print(json.dumps({'ok':result.get('ok') is True,'request_id':request_id,'state':result.get('data',{}).get('state'),
        'automatic_retry':False},ensure_ascii=False))
