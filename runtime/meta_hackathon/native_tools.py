"""Same-Core native READ receipts and truthful capability projections.

Remote effects remain unqualified and disabled. The existing owner-wide UNKNOWN
barrier and local network-OFF execution contracts are deliberately unchanged.
"""
import time
import json
from contextlib import contextmanager

from runtime.core_admission import Capability
from runtime.memory_patch.persistence.ports import RecordKind
from runtime.memory_patch.errors import MemoryPatchError, ErrorCode
from runtime.mobile_gateway import wire
from runtime.mobile_gateway.service import plain
from runtime.mcp_bridge import native_read


def chat_read_context(host,request_id):
    """Resolve an exact existing receipt, never caller-supplied tool output.

    Public metadata and bounded file excerpts remain untrusted data even though
    Core verified their provenance. No URL or file path comes from the model.
    """
    host._require_qualified_operator()
    native_read._require(type(request_id) is str and wire.HEX32.fullmatch(request_id),'CHAT_READ_REFERENCE_INVALID')
    row=host.mobile._get('native-tool-read-'+request_id)
    native_read._require(row is not None and row.payload.get('state')=='TOOL_READ_VERIFIED','CHAT_READ_NOT_VERIFIED')
    result=plain(row.payload['result']);receipt=result['receipt'];data=result['data']
    wire.verify(host.identity.spki,result['signature'],receipt)
    operation=receipt.get('operation')
    native_read._require(operation in ('github.repository', *native_read.CONTEXT_REPOSITORIES), 'CHAT_READ_BINDING_MISMATCH')
    expected={'schema':'aioa.native-tool-read-receipt.v1','request_id':request_id,'operation':operation,
        'effect':'READ','authority':'LOCAL_NATIVE_OWNER_READ','transport':'LIVE_GITHUB_GET',
        'source_sha':host.source[0],'capsule_digest':host.source[1],'core_instance_id':host.instance_id,
        'owner_scope_digest':host.mobile.owner_scope_digest,'automatic_retry':False}
    native_read._require(all(receipt.get(k)==v for k,v in expected.items()),'CHAT_READ_BINDING_MISMATCH')
    observed=receipt.get('observed_at');now=int(time.time())
    native_read._require(type(observed) is int and observed<=now<observed+300,'CHAT_READ_EXPIRED')
    native_read.validate_context_data(operation,data)
    native_read._require(wire.digest(wire.canonical(data))==receipt.get('data_sha256'),'CHAT_READ_DATA_MISMATCH')
    return {'schema':'aioa.chat.read-context.v1','trust':'UNTRUSTED_READ_DATA','request_id':request_id,
        'operation':operation,'observed_at':observed,'expires_at':observed+300,
        'source_sha':host.source[0],'capsule_digest':host.source[1],
        'data_sha256':receipt['data_sha256'],'receipt_sha256':wire.digest(wire.canonical(receipt)),'data':data}


def registry(host):
    owner=host.operator_principal()
    from runtime.critical_loop.preset import build_native_cpl_preview
    memory=host.runtime.memory_patch_status()
    unknown = 0
    governor = getattr(host.missions, '_chat_governor', None)
    if governor is not None:
        state = governor.inspect(host.core.local_operator(Capability.READ))
        unknown = sum(e['state'] == 'UNKNOWN' for e in state['reservations'].values())
    def observations(tx):
        rows=tx.scan(RecordKind.OPERATION,limit=128,states=('TOOL_READ_VERIFIED',))
        results=[plain(row.payload['result']) for row in rows]
        return [r['receipt'] for r in results if r['receipt'].get('transport')=='LIVE_GITHUB_GET'
                and r['receipt'].get('source_sha')==host.source[0]
                and r['receipt'].get('capsule_digest')==host.source[1]
                and r['receipt'].get('core_instance_id')==host.instance_id]
    reads=host.mobile._run(Capability.READ,observations)
    github={'status':'NOT_RUN','enabled':True,'repository':native_read.REPOSITORY}
    if reads:
        last=max(reads,key=lambda r:r['observed_at'])
        github.update(status='VERIFIED_READ',request_id=last['request_id'],observed_at=last['observed_at'],
                      data_sha256=last['data_sha256'])
    from .github_write import authorization
    github_auth=authorization(host)
    chat={'status':'BLOCKED_PROFILE','enabled':False,'provider':'meta_model_api','model':'muse-spark-1.3'}
    if host.chat_enabled:
        from runtime.mobile_gateway.operator_chat import dispatch as chat_dispatch
        catalog=chat_dispatch(host,owner,{'op':'chat_catalog'})
        chat.update(status=catalog['blocking_reason'] or ('LIVE_OWNER_SESSION'
            if catalog['session']['state']=='ACTIVE' else 'OWNER_APPROVAL_REQUIRED'),
            enabled=catalog['chat'],mode=catalog['mode'],session=catalog['session'])
    return {
        'chat': chat,
        'github_read': github,
        'command_advice': {'status':'ADVISORY_ONLY','enabled':True,'execution_authorized':False},
        'critic_transform_preview': {'status':'CPT_DRAFT_PREVIEW_ONLY','enabled':True,
            'execution_authorized':False,'provider_calls':0,'prompt_text_persisted':False},
        'mail_preview': {'status':'DRAFT_PREVIEW_ONLY','enabled':True,'send_enabled':False,
            'send_status':'BLOCKED_GMAIL_CORE_TRANSPORT_NOT_BOUND'},
        'github_write': {'status': 'BLOCKED_OWNER_LIABILITY_UNKNOWN' if unknown else
                         'BLOCKED_EXTERNAL' if not github_auth['configured'] else 'EXACT_OWNER_APPROVAL_REQUIRED',
                         'enabled': False, 'unknown_liabilities': unknown,'authorization':github_auth,
                         'adapter':'CORE_CREATE_ONLY_CANDIDATE','qualification':'NOT_LIVE_VERIFIED'},
        'worker': {'status': 'BLOCKED_NATIVE_WORKER_NOT_CERTIFIED', 'enabled': False},
        'memory': {'status':'INTEGRATED_INERT','enabled':False,
            'blocking_reason':'MEMORY_CONSENT_REQUIRED',
            'core_records':{'status':'CORE_RECORDS_SQLITE','persistent':True},
            'semantic_memory':{'enabled':memory['enabled'],'status':memory['backend_status']},
            'cockroach':{'status':'NOT_BOUND','enabled':False},'save_knowledge':False},
        'cpl': {'status': 'BLOCKED_NATIVE_CPL_NOT_BOUND', 'enabled': False, 'provider_calls': 0,
                'preview_status':'READ_ONLY_ADVISORY','preview_enabled':True,
                'contract': 'cpl-1plus3plus1-v1', 'expected_generation_requests': 5,
                'authority': 'ADVISORY_ONLY', 'automatic_retry': False,'preview':build_native_cpl_preview()},
    }


@contextmanager
def _read_lock(lock, deadline):
    if not lock.acquire(timeout=min(1, native_read._remaining(deadline))):
        raise wire.MobileError(409)
    try:yield
    finally:lock.release()


def dispatch(host, owner, value):
    deadline=time.monotonic()+native_read.READ_TIMEOUT_SECONDS
    host.core.require(owner, Capability.OWNER_APPROVAL, scope=host.missions.scope)
    host._require_qualified_operator()
    if value['op'] == 'tool_proposal':
        return proposal(host, value)
    if value['op'] == 'tool_readback':
        if set(value) != {'op', 'request_id'} or type(value['request_id']) is not str or not wire.HEX32.fullmatch(value['request_id']):
            raise wire.MobileError(400)
        row = host.mobile._get('native-tool-read-'+value['request_id'])
        if row is None:
            return {'state': 'NOT_FOUND', 'request_id': value['request_id'], 'automatic_retry': False}
        data = plain(row.payload)
        if data['state']=='TOOL_READ_VERIFIED':return data['result']
        result={'state':'UNKNOWN','request_id':value['request_id'],'automatic_retry':False}
        if data.get('failure',{}).get('code')=='TOOL_READ_TIMEOUT':
            result['error_code']='TOOL_READ_TIMEOUT'
        return result
    if set(value) != {'op', 'request_id', 'operation'}:
        raise wire.MobileError(400)
    request, operation = value['request_id'], value['operation']
    if (type(request) is not str or not wire.HEX32.fullmatch(request)
            or type(operation) is not str or operation not in native_read.OPERATIONS):
        raise wire.MobileError(400)
    key = 'native-tool-read-'+request
    binding = {'request_id': request, 'operation': operation,
               'source_sha': host.source[0], 'capsule_digest': host.source[1]}
    try:
        return _perform_read(host,key,binding,operation,deadline)
    except (ValueError,MemoryPatchError) as error:
        cause=error.__cause__ if isinstance(error,MemoryPatchError) and error.code==ErrorCode.TRANSACTION_FAILED else error
        if type(cause) is ValueError and cause.args==('TOOL_READ_TIMEOUT',):
            _record_timeout(host,key,binding)
        raise


def _record_timeout(host,key,binding):
    """Same uncertain request/AUDIT/OUTBOX; never change VERIFIED or retry IO."""
    def failed(tx):
        host._require_qualified_operator()
        row=tx.get(RecordKind.OPERATION,key)
        if row is not None and row.payload['state']=='TOOL_READ_PENDING' and plain(row.payload['binding'])==binding:
            at=int(time.time())
            payload=plain(row.payload);payload.pop('schema',None)
            host.mobile._record(tx,key,{**payload,'failure':{
                'code':'TOOL_READ_TIMEOUT','stage':'BOUNDED_READ_RECIPE',
                'observed_at':at,'automatic_retry':False}},row,at=at)
    # Recheck native authority, but not the intentionally expired IO deadline.
    # An uncertain diagnostic commit is retained as UNKNOWN without retry here.
    host.mobile._run(Capability.COMMIT,failed)


def _perform_read(host,key,binding,operation,deadline):
    with _read_lock(host.missions._lock,deadline):
        host.operator_principal()
        def reserve(tx):
            prior = tx.get(RecordKind.OPERATION, key)
            if prior is not None:
                payload = plain(prior.payload)
                if payload.get('binding') != binding:
                    raise wire.MobileError(409)
                if payload['state'] != 'TOOL_READ_VERIFIED':
                    raise wire.MobileError(409)
                return payload['result']
            host.mobile._record(tx, key, {'state': 'TOOL_READ_PENDING', 'binding': binding}, at=int(time.time()))
            return None
        prior = host.mobile._run(Capability.COMMIT, reserve)
        if prior is not None:
            return prior  # Historical observation, never repeat an external GET.
        from .runtime_adapter import ROOT
        value = native_read.read(operation, ROOT, check=host._require_qualified_operator,
                                 deadline=deadline)  # Never inside retryable transaction.
        host._require_qualified_operator()  # Recheck expiry, qualified TLS and exact source after IO.
        native_read._remaining(deadline)
        wire.canonical(value)
        now = int(time.time())
        receipt = {'schema': 'aioa.native-tool-read-receipt.v1', **binding,
                   'task_id': 'read-'+binding['request_id'], 'effect': 'READ', 'authority': 'LOCAL_NATIVE_OWNER_READ',
                   'core_instance_id': host.instance_id, 'owner_scope_digest': host.mobile.owner_scope_digest,
                   'observed_at': now, 'data_sha256': wire.digest(wire.canonical(value['data'])),
                   'transport': value['transport'], 'automatic_retry': False}
        result = {'data': value['data'], 'receipt': receipt, 'signature': host.identity.sign(receipt)}
        if len(wire.canonical(result)) > 48000:
            raise wire.MobileError(413)
        def complete(tx):
            host._require_qualified_operator()
            native_read._remaining(deadline)
            row = tx.get(RecordKind.OPERATION, key)
            if row is None or row.payload['state'] != 'TOOL_READ_PENDING' or plain(row.payload['binding']) != binding:
                raise wire.MobileError(409)
            host.mobile._record(tx, key, {'state': 'TOOL_READ_VERIFIED', 'binding': binding, 'result': result}, row, at=now)
        host.mobile._run(Capability.COMMIT, complete)
        return result


def proposal(host, value):
    """Parse current verified Muse output as data. It grants zero authority."""
    if set(value) != {'op', 'request_id', 'chat_request_id'} or any(
            type(value[k]) is not str or not wire.HEX32.fullmatch(value[k]) for k in ('request_id', 'chat_request_id')):
        raise wire.MobileError(400)
    with host.missions._lock:
        # Durable readback precedes the expiring, in-memory Muse text. A replay
        # after restart must not mint another proposal or repeat external IO.
        from .github_write import view
        prior = host.mobile._get('native-github-'+value['request_id'])
        if prior is not None:
            if prior.payload.get('source_chat_request_id') != value['chat_request_id']:
                raise wire.MobileError(409)
            return view(host, value['request_id'])
        source = host.mobile._get('native-github-source-'+value['chat_request_id'])
        if source is not None:
            return view(host, source.payload['operation_id'])
        message = host.missions.chat_request(value['chat_request_id'], host.core.local_operator(Capability.READ))
        if (message.get('state') != 'SUCCEEDED' or message.get('live_verified') is not True
                or message.get('current_source') is not True or not isinstance(message.get('receipt'), dict)
                or type(message.get('reply')) is not str
                or message.get('source_sha') != host.source[0] or message.get('capsule_digest') != host.source[1]
                or message['receipt'].get('response_sha256') != wire.digest(message['reply'].encode('utf-8'))):
            raise wire.MobileError(409)
        raw = wire.strict_json(message['reply'].encode('utf-8'),limit=wire.RESPONSE_LIMIT)
        if raw.get('schema')=='aioa.muse.github-change.v1':
            from .github_write import propose
            return propose(host,value,message)
        if (set(raw) != {'operation', 'target_repo', 'title', 'body'} or raw['operation'] != 'issue.create'
                or raw['target_repo'] != native_read.REPOSITORY
                or any(type(raw[k]) is not str or not raw[k].strip() or len(raw[k].encode('utf-8')) > maximum
                       for k, maximum in (('title', 160), ('body', 4000)))):
            raise wire.MobileError(400)
        now = int(time.time())
        item = {'schema': 'aioa.tool-proposal.advisory.v1', 'request_id': value['request_id'],
                'task_id': 'proposal-'+value['request_id'], 'thread_id': message['thread_id'],
                'source_chat_request_id': value['chat_request_id'],
                'source_reply_sha256': message['receipt']['response_sha256'],
                'source_sha': host.source[0], 'capsule_digest': host.source[1],
                'scope': host.mobile.owner_scope_digest, 'target_repo': native_read.REPOSITORY,
                'repository_id': native_read.REPOSITORY_ID, 'operation': 'issue.create',
                'arguments': {'title': raw['title'], 'body': raw['body']}, 'effects': ['REMOTE_MUTATION'],
                'requested_capabilities': ['GITHUB_ISSUE_CREATE'], 'approval_digest': None,
                'idempotency_key': value['request_id'], 'budget_cap_usd': '0.00',
                'created_at': now, 'expires_at': now+300}
        # The new code/PR route does not implement the legacy issue actuator.
        # Its credential/readiness status must not imply issue execution exists.
        unknown=registry(host)['github_write']['unknown_liabilities']
        result = {'proposal': item, 'proposal_digest': wire.digest(wire.canonical(item)),
                  'execution_authorized': False, 'status':
                  'BLOCKED_OWNER_LIABILITY_UNKNOWN' if unknown else 'BLOCKED_REMOTE_START_NOT_BOUND'}
        result['signature'] = host.identity.sign(result)
        key = 'native-tool-proposal-'+value['request_id']
        host._require_qualified_operator()
        def save(tx):
            host._require_qualified_operator()
            prior = tx.get(RecordKind.OPERATION, key)
            if prior is not None:
                old = plain(prior.payload['result'])
                if old['proposal']['source_chat_request_id'] != value['chat_request_id']:
                    raise wire.MobileError(409)
                return old
            host.mobile._record(tx, key, {'state': 'TOOL_PROPOSAL_ADVISORY', 'result': result}, at=now)
            return result
        return host.mobile._run(Capability.COMMIT, save)
