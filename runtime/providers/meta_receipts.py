"""Redacted call observations in the existing scoped Core records.

These records cannot approve, reserve, settle or retry an operation. Authority
continues to live in CoreWarrantLedger/CoreDualGovernor. No new store is opened.
"""
import json
import re
from decimal import Decimal
from datetime import timezone

from runtime.core_admission import Capability
from runtime.memory_patch.contracts.serialization import canonical_json_bytes, canonical_sha256
from runtime.memory_patch.persistence.ports import RecordKind, StoredRecord
from runtime.mission.warrant import CoreWarrantLedger

KIND = 'aioa.meta.api-attempt.v1'
STATES = ('ADMITTED', 'IN_FLIGHT', 'COMPLETED', 'FAILED', 'UNKNOWN', 'STOPPED')
FILTER = tuple(KIND+':'+s for s in STATES)
RECEIPT_FIELDS = frozenset(('schema','provider_id','model_id','request_digest','tool_call_id',
    'usage','environment','live_verified','cost_estimate_usd','cost_kind','authority','fallback',
    'binding','attempt_id','attempt','policy_epoch','warrant_digest','nonce_digest'))
BINDING_FIELDS = frozenset(('task_id','task_digest','owner_scope_digest','source_sha','provider_id',
    'model_id','deadline','budget_usd','allowed_origins','correlation_id','capsule_digest','stopped',
    'max_output_tokens','timeout_seconds','input_token_bound','max_attempts'))
CHAT_BINDING_FIELDS=(BINDING_FIELDS-{'allowed_origins'})|{'schema','device_id','thread_id','request_id',
    'session_id','nonce','actor','history_digest','prompt_sha256','context_sha256'}
CHAT_RECEIPT_FIELDS=(RECEIPT_FIELDS-{'tool_call_id'})|{'provider_request_id','response_sha256'}
ERROR_CODES = frozenset(('META_AUTH_DENIED','META_BILLING_OWNER_CHECK_REQUIRED','META_BILLING_UNAVAILABLE',
    'META_BUDGET_DENIED','META_BUDGET_EXCEEDED_UNKNOWN','META_CREDENTIAL_ECHO_DENIED','META_CREDENTIAL_IN_PAYLOAD',
    'META_EXACT_HUMAN_APPROVAL_REQUIRED','META_GOVERNOR_NOT_ACTIVE','META_INCOMPLETE_UNKNOWN',
    'META_KEY_UNAVAILABLE','META_MODEL_MISMATCH','META_MODEL_NOT_ADMITTED','META_NATIVE_AUTHORITY_NOT_BOUND',
    'META_NETWORK_UNKNOWN','META_PLAN_SCOPE_DENIED','META_RATE_LIMITED','META_REQUEST_ALREADY_CONSUMED',
    'META_REQUEST_DENIED','META_RESERVATION_BINDING_MISMATCH','META_RESPONSE_INVALID_UNKNOWN',
    'META_RESPONSE_LIMIT_UNKNOWN','META_SOURCE_BINDING_REQUIRED','META_SPEND_BINDING_MISMATCH',
    'META_SPEND_CURRENCY_MISMATCH','META_STOPPED','META_TASK_EXPIRED','META_TIMEOUT_UNKNOWN','META_UNAVAILABLE',
    'META_USAGE_DENIED','META_CONTRACT_REJECTED','META_CHAT_RESPONSE_INVALID_UNKNOWN','META_ADMISSION_ACK_UNKNOWN'))


def plain(value):
    return json.loads(canonical_json_bytes(value))


def require(ok):
    if not ok: raise ValueError('META_RECEIPT_INTEGRITY')


def cost(value):
    require(type(value) is str and re.fullmatch(r'(?:0(?:\.[0-9]{1,12})?|\.[0-9]{1,12})',value))
    amount=Decimal(value);require(0<=amount<=Decimal('.05'))
    return amount


def declared_budget(value,*,chat):
    if not chat:return cost(value)
    require(type(value) is str and re.fullmatch(r'(?:0|[1-9][0-9]{0,2})(?:\.[0-9]{1,9})?',value))
    amount=Decimal(value);require(0<amount<=Decimal('148'))
    return amount


def hex_digest(value,size=64,prefix=''):
    require(type(value) is str and re.fullmatch(re.escape(prefix)+'[a-f0-9]{'+str(size)+'}',value))


def public_binding(value,scope):
    from runtime.browser_agent.chrome_read_adapter import public_url
    from runtime.meta_hackathon.contracts import utc_timestamp
    chat=type(value) is dict and value.get('schema')=='aioa.meta.chat-binding.v1'
    require(type(value) is dict and set(value)==(CHAT_BINDING_FIELDS if chat else BINDING_FIELDS))
    for name in ('task_digest','owner_scope_digest','capsule_digest'):hex_digest(value[name])
    hex_digest(value['source_sha'],40)
    for name in ('task_id','correlation_id'):
        require(type(value[name]) is str and re.fullmatch(r'[A-Za-z0-9_-]{1,128}',value[name]))
    require(value['owner_scope_digest']==canonical_sha256(scope)
        and value['model_id']=='muse-spark-1.3' and value['provider_id']=='meta_model_api'
        and value['stopped'] is False and type(value['max_attempts']) is int and value['max_attempts']==1)
    require(type(value['max_output_tokens']) is int and 1<=value['max_output_tokens']<=512
        and type(value['timeout_seconds']) is int and 1<=value['timeout_seconds']<=15
        and type(value['input_token_bound']) is int and 1<=value['input_token_bound']<=16896)
    utc_timestamp(value['deadline'])
    require(declared_budget(value['budget_usd'],chat=chat and value['actor']=='LINUX_OWNER')>0)
    if chat:
        from runtime.providers.meta_model_api import MetaChatTask
        for name in ('device_id','history_digest','prompt_sha256','context_sha256'):hex_digest(value[name])
        for name in ('thread_id','request_id','session_id','nonce'):hex_digest(value[name],32)
        task=MetaChatTask(value['task_id'],value['owner_scope_digest'],value['source_sha'],value['deadline'],
            value['device_id'],value['thread_id'],value['request_id'],value['session_id'],value['nonce'],value['actor'])
        require(task.digest==value['task_digest'] and value['correlation_id']==value['request_id'])
    else:
        origins=value['allowed_origins']
        require(type(origins) is list and 1<=len(origins)<=3 and len(set(origins))==len(origins))
        for origin in origins:public_url(origin+'/',tuple(origins))
    return value


def _rows(tx):
    rows = tx.scan(RecordKind.OPERATION, limit=1024, states=FILTER)
    require(len(rows) < 1024)
    return tuple(r for r in rows if r.payload.get('schema') == KIND)


class MetaCallRecords:
    """CAS observation writes; receives already-admitted native composition."""
    def __init__(self, binding):
        self.binding = binding
        self.ledger = binding.ledger

    def admit(self, request):
        identity = 'meta-api-attempt-'+request.digest
        data = {'schema': KIND, 'state': KIND+':ADMITTED', 'attempt_id': identity,
            'attempt': 1, 'request_digest': request.digest, 'binding': request.public_binding(),
            'policy_epoch': self.binding.warrant.lease_epoch,
            'warrant_digest': self.binding.warrant.digest(),
            'nonce_digest': canonical_sha256(self.binding.warrant.nonce),
            'approval_record_id': self.ledger._key(self.binding.warrant),
            'operation_digest': self.binding.reservation.request_digest,
            'reservation_id': self.binding.reservation.request_id,
            'input_bound': len(canonical_json_bytes(request.payload()))+512,
            'output_bound': request.max_output_tokens,
            'cost_estimate': str(request.estimate()), 'settled_cost': None,
            'http_status': None, 'error_code': None,
            'created_at': self.ledger.clock().astimezone(timezone.utc).isoformat().replace('+00:00','Z')}
        def write(tx):
            # Existing immutable identity and CAS provide the durable retry barrier.
            require(tx.get(RecordKind.OPERATION, identity) is None)
            rows = _rows(tx)
            data['sequence'] = max((r.payload['sequence'] for r in rows), default=0)+1
            tx.insert(StoredRecord(RecordKind.OPERATION, identity, self.ledger.scope, 1, data))
        self.ledger._run(self.binding.principal, Capability.COMMIT, write)
        return identity

    def change(self, request, state, *, result=None, http_status=None, error_code=None):
        require(state in STATES and state != 'ADMITTED')
        identity = 'meta-api-attempt-'+request.digest
        def write(tx):
            row = tx.get(RecordKind.OPERATION, identity)
            require(row is not None and row.payload.get('schema') == KIND)
            data = plain(row.payload)
            require(data['binding'] == request.public_binding()
                and data['warrant_digest'] == self.binding.warrant.digest())
            before = data['state'].removeprefix(KIND+':')
            require(before in ('ADMITTED', 'IN_FLIGHT') or before == 'COMPLETED' and state == 'UNKNOWN')
            require(state != 'IN_FLIGHT' or before == 'ADMITTED')
            if result is not None:
                require(state == 'COMPLETED' and result.request_digest == request.digest)
                receipt = result.receipt()
                receipt.update(attempt_id=identity, attempt=1, policy_epoch=data['policy_epoch'],
                               warrant_digest=data['warrant_digest'], nonce_digest=data['nonce_digest'])
                tx.insert(StoredRecord(RecordKind.RECEIPT, 'meta-api-'+request.digest,
                                      self.ledger.scope, 1, receipt))
            data.update(state=KIND+':'+state, http_status=http_status, error_code=error_code)
            tx.replace(StoredRecord(RecordKind.OPERATION, identity, self.ledger.scope,
                                   row.revision+1, data), expected_revision=row.revision)
        self.ledger._run(self.binding.principal, Capability.COMMIT, write)


class MetaReceiptView:
    """Read-only Core projection; abandoned pending records remain UNKNOWN."""
    def __init__(self, ledger, *, governor=None, source_reader):
        require(type(ledger) is CoreWarrantLedger and callable(source_reader))
        if governor is not None:
            from runtime.mission.governor import CoreDualGovernor
            require(type(governor) is CoreDualGovernor and governor.core is ledger.core
                    and governor.runner is ledger.runner and governor.policy.scope == ledger.scope)
        self.ledger, self.governor, self.source_reader = ledger, governor, source_reader

    def _validate(self,row,receipt,approval,reader,governor,current_source,active_attempt_id,*,historical=False):
        from runtime.providers.meta_model_api import spend_operation, INPUT_PRICE, OUTPUT_PRICE,session_chat_warrant
        from runtime.meta_hackathon.contracts import utc_timestamp
        data=plain(row.payload);binding=public_binding(data['binding'],self.ledger.scope)
        hex_digest(data['request_digest']);hex_digest(data['operation_digest']);hex_digest(data['nonce_digest'])
        hex_digest(data['warrant_digest'],prefix='sha256:')
        require(row.record_id==data['attempt_id']=='meta-api-attempt-'+data['request_digest']
            and type(data['attempt']) is int and data['attempt']==1 and data['state'] in FILTER
            and type(data['sequence']) is int and 1<=data['sequence']<=1023
            and type(data['policy_epoch']) is int and data['policy_epoch']>0
            and (historical or current_source==(binding['source_sha'],binding['capsule_digest']))
            and binding['model_id'] in reader.model_binding_ids)
        require(data['http_status'] is None or type(data['http_status']) is int and 100<=data['http_status']<=599)
        require(data['error_code'] is None or data['error_code'] in ERROR_CODES)
        utc_timestamp(data['created_at'])
        require(data['settled_cost'] is None and type(data['input_bound']) is int
            and type(data['output_bound']) is int and data['input_bound']==binding['input_token_bound']
            and data['output_bound']==binding['max_output_tokens'])
        estimate=(Decimal(binding['input_token_bound'])*INPUT_PRICE+Decimal(binding['max_output_tokens'])*OUTPUT_PRICE)/1000000
        require(cost(data['cost_estimate'])==estimate)
        operation=spend_operation(data['request_digest'],binding)
        require(canonical_sha256(operation)==data['operation_digest'])
        entry=governor['reservations'].get(data['reservation_id'])
        require((governor['epoch']>=data['policy_epoch'] if historical else governor['epoch']==data['policy_epoch']) and entry is not None
            and entry['epoch']==data['policy_epoch'] and entry['task_id']==binding['task_id']
            and entry['provider_id']==binding['provider_id'] and entry['model_id']==binding['model_id']
            and entry['request_digest']==data['operation_digest'])
        warrant,approval_data=approval
        require(warrant.digest()==data['warrant_digest'] and canonical_sha256(warrant.nonce)==data['nonce_digest']
            and warrant.operation_hash=='sha256:'+data['operation_digest']
            and warrant.operation_class==operation['operation_class'] and warrant.task_id==binding['task_id']
            and warrant.lease_epoch==data['policy_epoch'] and warrant.authority_scope.monetary_ceiling.currency=='USD')
        state=data['state'].removeprefix(KIND+':')
        if state in ('ADMITTED','IN_FLIGHT') and active_attempt_id!=data['attempt_id']:state='UNKNOWN'
        projected={'call_state':state,'cost_estimate':data['cost_estimate'],'budget_ledger_state':entry['state'],
            'last_attempt':{k:data[k] for k in ('attempt_id','attempt','request_digest','policy_epoch','http_status','error_code','created_at')}}
        value=None
        if state=='COMPLETED':
            session_pending=(binding.get('schema')=='aioa.meta.chat-binding.v1' and binding['actor']=='LINUX_OWNER'
                and session_chat_warrant(warrant) and entry['state']=='DISPATCHED')
            require(receipt is not None and approval_data['consumption'] is not None
                and (entry['state'] in ('UNKNOWN','COMMITTED') or session_pending))
            chat=binding.get('schema')=='aioa.meta.chat-binding.v1'
            fields=CHAT_RECEIPT_FIELDS if chat else RECEIPT_FIELDS
            value=plain(receipt.payload);require(set(value)==fields)
            require(value['schema']==('aioa.meta.chat-receipt.v1' if chat else 'aioa.meta.api-receipt.v1') and value['request_digest']==data['request_digest']
                and value['binding']==binding and type(value['policy_epoch']) is int
                and value['policy_epoch']==data['policy_epoch'] and type(value['attempt']) is int
                and value['attempt_id']==data['attempt_id'] and value['attempt']==1
                and value['warrant_digest']==data['warrant_digest'] and value['nonce_digest']==data['nonce_digest']
                and value['model_id']==binding['model_id'] and value['provider_id']==binding['provider_id']
                and value['environment']=='META_API_LIVE_VERIFIED' and value['live_verified'] is True
                and value['authority']==('ADVISORY_TEXT_ONLY' if chat else 'ADVISORY_ONLY') and value['fallback'] is False
                and value['cost_kind']=='ESTIMATE_NOT_INVOICE')
            if chat:
                hex_digest(value['response_sha256'])
                require(value['provider_request_id'] is None or type(value['provider_request_id']) is str
                    and re.fullmatch('[A-Za-z0-9_.:/-]{1,200}',value['provider_request_id']))
            else:require(type(value['tool_call_id']) is str and re.fullmatch(r'[A-Za-z0-9_-]{1,128}',value['tool_call_id']))
            usage=value['usage']
            require(type(usage) is dict and set(usage)=={'prompt_tokens','completion_tokens','total_tokens'}
                and all(type(n) is int and n>=0 for n in usage.values())
                and usage['total_tokens']==usage['prompt_tokens']+usage['completion_tokens']
                and usage['prompt_tokens']<=data['input_bound'] and usage['completion_tokens']<=data['output_bound'])
            require(cost(value['cost_estimate_usd'])==(Decimal(usage['prompt_tokens'])*INPUT_PRICE+Decimal(usage['completion_tokens'])*OUTPUT_PRICE)/1000000)
            value={k:value[k] for k in sorted(fields)}
        return projected,value

    def readback(self, request_digest, *, historical=False):
        """Immutable result inspection, never a dispatch or renewed authority.

        Historical mode verifies the original source/warrant/ledger binding;
        it deliberately does not demand that an old source is the current one.
        New calls still use MetaLiveBinding.check and the strict snapshot.
        """
        from lab.archaioa.warrant import EffectWarrant
        hex_digest(request_digest);require(type(historical) is bool and self.governor is not None)
        reader=self.ledger.core.local_operator(Capability.READ)
        def read(tx):
            row=tx.get(RecordKind.OPERATION,'meta-api-attempt-'+request_digest)
            require(row is not None and row.payload.get('schema')==KIND)
            approval=tx.get(RecordKind.OPERATION,row.payload['approval_record_id']);require(approval is not None)
            warrant=EffectWarrant.from_dict(plain(approval.payload)['active'])
            _,data,active=self.ledger._load(tx,warrant)
            return row,tx.get(RecordKind.RECEIPT,'meta-api-'+request_digest),(active,data)
        row,receipt,approval=self.ledger._run(reader,Capability.READ,read)
        _,value=self._validate(row,receipt,approval,reader,self.governor.inspect(reader),self.source_reader(),None,historical=historical)
        require(value is not None)
        return {**value,'historical':historical,'current_authority':False}

    def snapshot(self, *, active_attempt_id=None):
        output={'call_state':'NOT_ATTEMPTED','last_live_receipt':None,'last_attempt':None,
            'billing_status':'UNVERIFIED','credits_confirmed':False,'cost_estimate':None,
            'settled_cost':None,'budget_ledger_state':None}
        try:
            reader=self.ledger.core.local_operator(Capability.READ)
            def read(tx):
                from lab.archaioa.warrant import EffectWarrant
                result=[]
                for row in sorted(_rows(tx),key=lambda r:r.payload['sequence'],reverse=True):
                    try:
                        approval=tx.get(RecordKind.OPERATION,row.payload['approval_record_id']);require(approval is not None)
                        warrant=EffectWarrant.from_dict(plain(approval.payload)['active'])
                        _,data,active=self.ledger._load(tx,warrant)
                        receipt=tx.get(RecordKind.RECEIPT,'meta-api-'+row.payload['request_digest'])
                        result.append((row,receipt,(active,data)))
                    except Exception:result.append((row,None,None))
                return result
            rows=self.ledger._run(reader,Capability.READ,read)
            if not rows:return output
            output['call_state']='UNKNOWN';require(self.governor is not None)
            governor=self.governor.inspect(reader);source=self.source_reader()
            for index,(row,receipt,approval) in enumerate(rows):
                try:
                    latest,value=self._validate(row,receipt,approval,reader,governor,source,active_attempt_id)
                    if index==0:output.update(latest)
                    if value is not None:
                        output['last_live_receipt']=value;break
                except Exception:
                    if index==0:output['diagnostic_error']='META_RECEIPT_READBACK_UNKNOWN'
            return output
        except Exception:
            output.update(call_state='UNKNOWN',last_live_receipt=None,last_attempt=None,
                          cost_estimate=None,diagnostic_error='META_RECEIPT_READBACK_UNKNOWN')
            return output
