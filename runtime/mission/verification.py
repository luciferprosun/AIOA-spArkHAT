"""Native commit/select/reveal bookkeeping; every verdict remains advisory.

One injected Core and native transaction port own the records. No provider,
credential, effect executor, evidence admission service or authority is created.
Current input is resolved by an existing host evidence service. The mandatory
local mechanical checker receives admitted canonical evidence. Selected review
gets only the bounded worker claim and hashed context/scope references, never
source text, private HAT payloads, a prompt or a Core principal.
"""
from dataclasses import dataclass, replace, is_dataclass
from datetime import datetime, timezone
import json
from random import SystemRandom

from runtime.core_admission import Capability, CoreAdmission, OwnerScope
from runtime.memory_patch.audit import append_domain_event, decode_audit, domain_chain
from runtime.memory_patch.contracts.serialization import canonical_json_bytes, canonical_sha256, ensure_utc
from runtime.memory_patch.errors import ErrorCode, MemoryPatchError
from runtime.memory_patch.learning.contracts import CoreVerifierBinding, VerificationInput, VerificationVerdict, VerifierReceipt
from runtime.memory_patch.persistence.idempotency import OperationBinding, execute_once
from runtime.memory_patch.persistence.ports import RecordKind, TransactionContext, TransactionRunner
from runtime.mission.contracts import logical_id
from runtime.providers.nvidia import ProviderResponse, OUTPUT_SCHEMA
from runtime.service_guard.contracts import OUTPUT_SCHEMA as SERVICE_SCHEMA, parse_proposal

CANONICAL_POLICY='native-json-utf8-exact-v1'
PREFIX='aioa-csr-'


def _require(condition,code=ErrorCode.INVALID_REQUEST):
    if not condition:raise MemoryPatchError(code)


def _plain(value):return json.loads(canonical_json_bytes(value))


@dataclass(frozen=True,slots=True,repr=False)
class VerificationPolicy:
    scope: OwnerScope
    hat_id: str
    output_schema: str
    verifier_refs: tuple[str,...]
    selection_count: int=1
    max_artifact_bytes: int=4096
    validity_seconds: int=300
    policy_version: str='native-csr-v1'
    canonical_policy: str=CANONICAL_POLICY

    def __post_init__(self):
        _require(type(self.scope) is OwnerScope)
        for value in (self.hat_id,self.policy_version):logical_id(value)
        _require(self.output_schema in (OUTPUT_SCHEMA,SERVICE_SCHEMA)
            and self.canonical_policy==CANONICAL_POLICY
            and type(self.verifier_refs) is tuple and 1<=len(self.verifier_refs)<=8
            and self.verifier_refs==tuple(sorted(set(self.verifier_refs))))
        for ref in self.verifier_refs:logical_id(ref)
        _require(type(self.selection_count) is int and 1<=self.selection_count<=len(self.verifier_refs)
            and type(self.max_artifact_bytes) is int and 32<=self.max_artifact_bytes<=8192
            and type(self.validity_seconds) is int and 1<=self.validity_seconds<=300)


class CoreCommitSelectReveal:
    """Host composition only. Selection requires Core MANAGE, not worker COMMIT.

Imports/constructor are inert with respect to storage, RNG, network and effects.
Callbacks/RNG run outside retry transactions. START persists before callbacks;
missing receipt thereafter is UNKNOWN and cannot automatically invoke them again.
"""
    def __init__(self,core,runner,policy,mechanical,verifiers,*,current_input,picker=None,
                 clock=lambda:datetime.now(timezone.utc)):
        _require(type(core) is CoreAdmission and type(runner) is TransactionRunner
            and type(policy) is VerificationPolicy and type(mechanical) is CoreVerifierBinding
            and type(verifiers) is tuple and all(type(v) is CoreVerifierBinding for v in verifiers)
            and tuple(sorted(v.verifier_ref for v in verifiers))==policy.verifier_refs
            and len({v.verifier_ref for v in verifiers})==len(verifiers)
            and callable(current_input) and callable(clock) and (picker is None or callable(picker)))
        self.core,self.runner,self.policy=core,runner,policy
        self.mechanical,self.verifiers=mechanical,{v.verifier_ref:v for v in verifiers}
        self.current_input,self.picker,self.clock=current_input,picker,clock
        reader=core.local_operator(Capability.READ)
        core.require(reader,Capability.READ,scope=policy.scope)
        _require(policy.hat_id in reader.hat_ids)
        self.registry_digest=self._active_registry_digest()

    def _active_registry_digest(self):
        return canonical_sha256({'policy':self.policy,'mechanical':self._descriptor(self.mechanical),
            'verifiers':tuple(self._descriptor(self.verifiers[r]) for r in self.policy.verifier_refs)})

    @staticmethod
    def _descriptor(binding):
        # Native frozen rule definitions can be pinned mechanically. Arbitrary
        # host callback behavior remains an explicit policy-version assumption.
        oracle=binding.verifier
        frozen=is_dataclass(oracle) and getattr(type(oracle),'__dataclass_params__').frozen
        definition=canonical_sha256(oracle) if frozen else None
        return (binding.verifier_ref,binding.verifier_method,binding.source_family,
            type(oracle).__module__,type(oracle).__qualname__,definition)

    def _require(self,principal,purpose):
        self.core.require(principal,purpose,scope=self.policy.scope)
        _require(self.policy.hat_id in principal.hat_ids)

    def _key(self,task_id,stage):
        logical_id(task_id)
        return canonical_sha256((PREFIX,self.policy.scope,task_id,stage))

    def _get(self,task_id,stage):
        reader=self.core.local_operator(Capability.READ);key=self._key(task_id,stage)
        def read(tx):
            domain_chain(tx)
            record=tx.get(RecordKind.OPERATION,key)
            if record is None:return None
            p=record.payload
            _require(set(p)=={'operation_kind','payload_digest','outcome'}
                and p['operation_kind']==PREFIX+stage+'-v1'
                and p['payload_digest']==canonical_sha256(p['outcome']),ErrorCode.INTEGRITY_FAILED)
            audit=tx.get(RecordKind.AUDIT,'csr-'+key)
            _require(audit is not None,ErrorCode.PROVENANCE_PENDING)
            event=decode_audit(audit)
            _require(event.resource_id==key and event.event_type==PREFIX+stage+'-v1'
                and event.content_hashes.get('operation')==p['payload_digest']
                and event.content_hashes.get('content')==p['payload_digest'],ErrorCode.INTEGRITY_FAILED)
            outbox=tx.get(RecordKind.OUTBOX,'csr-outbox-'+key)
            operation=OperationBinding(key,PREFIX+stage+'-v1',p['payload_digest'])
            _require(outbox is not None and set(outbox.payload)=={'state','event_id','event_digest',
                'operation_digest','proof_id','core_entry_hash'}
                and outbox.payload['state'] in ('PENDING','PUBLISHED')
                and outbox.payload['event_id']=='csr-'+key
                and outbox.payload['proof_id']=='csr-outbox-'+key
                and outbox.payload['operation_digest']==canonical_sha256({'scope':reader.scope.binding(),'operation':operation})
                and outbox.payload['event_digest']==event.event_hash,
                ErrorCode.PROVENANCE_PENDING)
            return _plain(p['outcome'])
        return self.runner.run(TransactionContext(reader,Capability.READ),read)

    def _put(self,principal,task_id,stage,outcome,purpose=Capability.COMMIT,*,claim=False):
        key=self._key(task_id,stage);binding=OperationBinding.bind(key,PREFIX+stage+'-v1',outcome)
        at=ensure_utc(self.clock())
        def write(tx):
            def append():
                events=domain_chain(tx)
                # Keep the native head readable (<1024) and leave one receipt
                # slot before callbacks. Other native writers can still consume
                # space later; that outcome remains UNKNOWN, never redispatched.
                _require(len(events)<(1022 if stage=='start' else 1023),ErrorCode.QUOTA_EXCEEDED)
                if stage=='commit':
                    operations=tx.scan(RecordKind.OPERATION,limit=1024)
                    _require(len(operations)<1024 and sum(r.payload.get('operation_kind')==PREFIX+'commit-v1'
                        for r in operations)<64,ErrorCode.QUOTA_EXCEEDED)
                append_domain_event(tx,binding,event_id='csr-'+key,proof_id='csr-outbox-'+key,
                    resource_id=key,before=None,after=stage,content_digest=binding.payload_digest,at=at)
                return outcome
            return execute_once(tx,binding,append)
        result=self.runner.run(TransactionContext(principal,purpose),write)
        value=_plain(result.outcome)
        return (value,not result.replayed) if claim else value

    def _artifact(self,response):
        _require(type(response) is ProviderResponse and response.validation_result=='VALID'
            and response.authority=='ADVISORY_ONLY' and response.finish_reason=='stop'
            and response.http_status==200 and type(response.raw_size) is int and 0<=response.raw_size<=16384)
        value=_plain(response.parsed_payload)
        if self.policy.output_schema==SERVICE_SCHEMA:
            try:value=parse_proposal(value)
            except ValueError:raise MemoryPatchError(ErrorCode.INVALID_REQUEST) from None
        else:
            _require(type(value) is dict and set(value)=={'summary','needs_attention'}
                and type(value['summary']) is str and 1<=len(value['summary'])<=800
                and type(value['needs_attention']) is bool)
        raw=canonical_json_bytes(value)
        _require(len(raw)<=self.policy.max_artifact_bytes,ErrorCode.QUOTA_EXCEEDED)
        # No Unicode normalization: exact legitimate NFD content is preserved.
        return value,canonical_sha256(value),len(raw)

    def _current(self,response):
        reader=self.core.local_operator(Capability.READ)
        request=self.current_input(reader,response)
        _require(type(request) is VerificationInput and request.scope==self.policy.scope
            and request.domain_hat==self.policy.hat_id and 1<=len(request.sources)<=8,
            ErrorCode.EVIDENCE_DENIED)
        _require(all(type(row) is tuple and len(row)==4 and all(type(v) is str for v in row)
            for row in request.sources),ErrorCode.EVIDENCE_DENIED)
        _require(sum(len(row[3].encode()) for row in request.sources)<=8192,ErrorCode.QUOTA_EXCEEDED)
        _require(len(request.claim.encode())<=4096,ErrorCode.QUOTA_EXCEEDED)
        identities=[]
        for source,version,ref,text in request.sources:
            for identity in (source,version,ref):logical_id(identity)
            identities.append((source,version,ref,canonical_sha256(text)))
        _require(len({row[0] for row in identities})==len(identities),ErrorCode.EVIDENCE_DENIED)
        root=canonical_sha256((request.scope,request.domain_hat,request.task_signature,tuple(sorted(identities))))
        return request,root

    def _valid_commit(self,commit):
        _require(set(commit)=={'request_hash','artifact_hash','artifact_bytes','producer_ref','source_root',
            'registry_digest','canonical_policy','authority','created_at'}
            and commit['authority']=='NONE' and commit['canonical_policy']==CANONICAL_POLICY,
            ErrorCode.INTEGRITY_FAILED)
        _require(commit['registry_digest']==self.registry_digest==self._active_registry_digest(),
            ErrorCode.IDEMPOTENCY_CONFLICT)
        age=(ensure_utc(self.clock())-datetime.fromisoformat(commit['created_at'])).total_seconds()
        _require(0<=age<self.policy.validity_seconds,ErrorCode.EVIDENCE_DENIED)

    def commit(self,principal,task_id,request_hash,response):
        self._require(principal,Capability.COMMIT)
        _require(self.registry_digest==self._active_registry_digest(),ErrorCode.IDEMPOTENCY_CONFLICT)
        _require(type(request_hash) is str and len(request_hash)==64
            and all(v in '0123456789abcdef' for v in request_hash))
        _require(response.model_id in principal.model_binding_ids)
        _,artifact_hash,size=self._artifact(response);_,source_root=self._current(response)
        binding={'request_hash':request_hash,'artifact_hash':artifact_hash,'artifact_bytes':size,
            'producer_ref':canonical_sha256((response.request_id,response.provider_request_id,response.model_id)),
            'source_root':source_root,'registry_digest':self.registry_digest,
            'canonical_policy':self.policy.canonical_policy,'authority':'NONE'}
        old=self._get(task_id,'commit')
        if old is not None:
            _require({k:v for k,v in old.items() if k!='created_at'}==binding,ErrorCode.IDEMPOTENCY_CONFLICT)
            self._valid_commit(old);return old
        return self._put(principal,task_id,'commit',{**binding,'created_at':ensure_utc(self.clock()).isoformat()})

    def select(self,principal,task_id):
        self._require(principal,Capability.MANAGE)
        commit=self._get(task_id,'commit');_require(commit is not None,ErrorCode.RECOVERY_REQUIRED)
        self._valid_commit(commit)
        old=self._get(task_id,'select')
        if old is not None:
            self._valid_selection(old,commit)
            return old
        pool=self.policy.verifier_refs
        chosen=tuple(self.picker(pool,self.policy.selection_count)) if self.picker else tuple(SystemRandom().sample(pool,self.policy.selection_count))
        _require(len(chosen)==self.policy.selection_count and len(set(chosen))==len(chosen)
            and all(ref in self.verifiers for ref in chosen),ErrorCode.INVALID_REQUEST)
        return self._put(principal,task_id,'select',{'commit_digest':canonical_sha256(commit),
            'verifier_refs':sorted(chosen),'authority':'NONE'},Capability.MANAGE)

    @staticmethod
    def _check(binding,request):
        verdict=binding.verifier.verify(request)
        _require(type(verdict) is VerificationVerdict and verdict.input_digest==request.digest,
            ErrorCode.INTEGRITY_FAILED)
        return VerifierReceipt(binding.verifier_ref,binding.verifier_method,binding.source_family,
            request.digest,verdict.supported)

    def _valid_selection(self,selection,commit):
        _require(set(selection)=={'commit_digest','verifier_refs','authority'}
            and selection['authority']=='NONE' and selection['commit_digest']==canonical_sha256(commit)
            and type(selection['verifier_refs']) is list
            and selection['verifier_refs']==sorted(set(selection['verifier_refs']))
            and len(selection['verifier_refs'])==self.policy.selection_count
            and all(ref in self.verifiers for ref in selection['verifier_refs']),ErrorCode.INTEGRITY_FAILED)

    @staticmethod
    def _bounded(request):
        scope_ref=canonical_sha256(request.scope)
        return VerificationInput(OwnerScope(scope_ref,scope_ref,scope_ref,scope_ref),
            canonical_sha256(request.domain_hat),canonical_sha256(request.task_signature),request.claim,
            tuple((canonical_sha256(row[0]),canonical_sha256(row[1]),canonical_sha256(row[2]),'CONTEXT_OMITTED')
                  for row in request.sources),request.at)

    def _valid_receipt(self,receipt,start,commit,selection,request):
        _require(start is not None and set(start)=={'commit_digest','selection_digest','authority',
            'mechanical_input_digest','selected_input_digest','input_at'},ErrorCode.INTEGRITY_FAILED)
        original=replace(request,at=datetime.fromisoformat(start['input_at']))
        _require(start['authority']=='NONE' and start['commit_digest']==canonical_sha256(commit)
            and start['selection_digest']==canonical_sha256(selection)
            and start['mechanical_input_digest']==original.digest
            and start['selected_input_digest']==self._bounded(original).digest,ErrorCode.INTEGRITY_FAILED)
        _require(set(receipt)=={'status','authority','execution_authority','verification','commit_digest',
            'selection_digest','mechanical_receipt','verifier_receipts','source_root','auto_retry'}
            and receipt['authority']=='NONE' and receipt['execution_authority'] is False
            and receipt['auto_retry'] is False and receipt['verification']=='MECHANICAL_PLUS_ADVISORY'
            and receipt['commit_digest']==start['commit_digest']
            and receipt['selection_digest']==start['selection_digest']
            and receipt['source_root']==commit['source_root'],ErrorCode.INTEGRITY_FAILED)
        mechanical=VerifierReceipt(**receipt['mechanical_receipt'])
        _require((mechanical.verifier_ref,mechanical.verifier_method,mechanical.source_family)==
            self._descriptor(self.mechanical)[:3] and mechanical.input_digest==start['mechanical_input_digest'],
            ErrorCode.INTEGRITY_FAILED)
        refs=selection['verifier_refs'] if mechanical.supported else []
        receipts=[VerifierReceipt(**value) for value in receipt['verifier_receipts']]
        _require([r.verifier_ref for r in receipts]==refs,ErrorCode.INTEGRITY_FAILED)
        for r in receipts:
            _require((r.verifier_ref,r.verifier_method,r.source_family)==self._descriptor(self.verifiers[r.verifier_ref])[:3]
                and r.input_digest==start['selected_input_digest'],ErrorCode.INTEGRITY_FAILED)
        supported=mechanical.supported and all(r.supported for r in receipts)
        _require(receipt['status']==('SUPPORTED' if supported else 'REVIEW_REQUIRED'),ErrorCode.INTEGRITY_FAILED)
        return receipt

    def reveal(self,principal,task_id,response):
        self._require(principal,Capability.COMMIT)
        commit=self._get(task_id,'commit');selection=self._get(task_id,'select')
        _require(commit is not None and selection is not None,ErrorCode.RECOVERY_REQUIRED)
        self._valid_commit(commit)
        self._valid_selection(selection,commit)
        _,digest,size=self._artifact(response)
        _require(digest==commit['artifact_hash'] and size==commit['artifact_bytes']
            and canonical_sha256((response.request_id,response.provider_request_id,response.model_id))==commit['producer_ref']
            and selection['commit_digest']==canonical_sha256(commit),ErrorCode.INTEGRITY_FAILED)
        request,root=self._current(response)
        _require(root==commit['source_root'],ErrorCode.EVIDENCE_DENIED)
        old=self._get(task_id,'receipt')
        start=self._get(task_id,'start')
        if old is not None:return self._valid_receipt(old,start,commit,selection,request)
        if start is not None:return {'status':'UNKNOWN','authority':'NONE','execution_authority':False,
            'reconciliation_required':True,'auto_retry':False}
        bounded=self._bounded(request)
        marker={'commit_digest':canonical_sha256(commit),'selection_digest':canonical_sha256(selection),'authority':'NONE',
            'mechanical_input_digest':request.digest,'selected_input_digest':bounded.digest,'input_at':request.at.isoformat()}
        _,owns_callbacks=self._put(principal,task_id,'start',marker,claim=True)
        if not owns_callbacks:
            # Another acknowledged START owner may still be running. Read only;
            # durable replay is never callback ownership, including CAS retries.
            receipt=self._get(task_id,'receipt')
            return self._valid_receipt(receipt,self._get(task_id,'start'),commit,selection,request) if receipt is not None else {'status':'UNKNOWN','authority':'NONE',
                'execution_authority':False,'reconciliation_required':True,'auto_retry':False}
        try:
            mechanical=self._check(self.mechanical,request)
            receipts=[]
            if mechanical.supported:
                # Reuse the native input/verdict DTO while withholding private
                # scope names, evidence content and prompt from selected review.
                for ref in selection['verifier_refs']:
                    receipts.append(self._check(self.verifiers[ref],bounded))
            _,current_root=self._current(response)
            _require(current_root==root,ErrorCode.EVIDENCE_DENIED)
            self._valid_commit(commit)
            supported=mechanical.supported and all(r.supported for r in receipts)
            result={'status':'SUPPORTED' if supported else 'REVIEW_REQUIRED','authority':'NONE',
                'execution_authority':False,'verification':'MECHANICAL_PLUS_ADVISORY',
                'commit_digest':marker['commit_digest'],'selection_digest':marker['selection_digest'],
                'mechanical_receipt':_plain(mechanical),'verifier_receipts':_plain(receipts),
                'source_root':root,'auto_retry':False}
        except Exception:
            # START remains; no fabricated receipt or automatic callback retry.
            return {'status':'UNKNOWN','authority':'NONE','execution_authority':False,
                'reconciliation_required':True,'auto_retry':False}
        return self._put(principal,task_id,'receipt',result)

    def inspect(self,principal,task_id):
        self._require(principal,Capability.READ)
        commit=self._get(task_id,'commit')
        return {'status':'COMMITTED' if commit is not None else 'NOT_FOUND','authority':'NONE',
            'commit_digest':canonical_sha256(commit) if commit else None,
            'selection_present':self._get(task_id,'select') is not None,
            'receipt_present':self._get(task_id,'receipt') is not None}
