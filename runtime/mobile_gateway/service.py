"""Signed observation/preview/STOP port over the existing MissionService.

Only an explicit OFFLINE fixture is enabled in N1. Production enrollment is
blocked until the host's native TLS edge/identity is independently qualified.
Transport records share Core's scoped transaction runner; they grant no warrant.
"""
import secrets
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone

from runtime.core_admission import Capability
from runtime.memory_patch.contracts.serialization import canonical_sha256
from runtime.memory_patch.audit import append_domain_event
from runtime.memory_patch.persistence.idempotency import OperationBinding
from runtime.memory_patch.errors import ErrorCode, MemoryPatchError
from runtime.memory_patch.persistence.ports import RecordKind, StoredRecord, TransactionContext
from runtime.meta_hackathon.mission_service import MissionError, MissionService, MissionRequest
from . import wire

SCHEMA = 'aioa.mobile.transport.v1'
SCOPE_FIELDS = ('device_id', 'session_id', 'source_sha', 'capsule_digest', 'owner_scope_digest', 'audience')


def require(ok, status=401):
    if not ok:
        raise wire.MobileError(status)


def plain(value):
    # Core freezes mappings/arrays; its serializer is the existing canonical port.
    from runtime.memory_patch.contracts.serialization import canonical_json_bytes
    import json
    return json.loads(canonical_json_bytes(value))


@dataclass(frozen=True)
class Session:
    token_hash: str
    data: dict
    nonce: str
    method: str
    path: str


class MobileGateway:
    def __init__(self, missions, *, identity=None, fixture=False, clock=time.time,native_host=None):
        require(type(missions) is MissionService, 503)
        self.missions, self.core, self.runner = missions, missions.core, missions.runner
        self.scope = missions.scope
        self.identity, self.clock = identity, clock
        self.native_host=native_host
        self._lock = threading.RLock()
        self.enabled = (fixture is True and type(identity) is wire.Identity
                        and missions.manager._meta_provider.mode == 'MOCK'
                        and missions.scope.tenant_id == 'offline-fixture')
        self.source = tuple(missions.source_probe())
        require(len(self.source) == 2 and wire.SHA40.fullmatch(self.source[0])
                and wire.HEX64.fullmatch(self.source[1]), 503)
        self.owner_scope_digest = canonical_sha256(self.scope)
        self.origin = 'https://fixture.invalid'
        if native_host is not None:
            from runtime.meta_hackathon.runtime_adapter import NativeMobileComposition
            require(type(native_host) is NativeMobileComposition and native_host.core is self.core
                and native_host.missions is missions and fixture is False and identity is native_host.identity,503)
            self.core.require(native_host.operator_principal(),Capability.OWNER_APPROVAL,scope=self.scope)
            self.origin=native_host.origin
            self.enabled=True

    def _ready(self,*,allow_pending_tls=False):
        if self.native_host is not None:
            self.core.require(self.native_host.operator_principal(),Capability.OWNER_APPROVAL,scope=self.scope)
            if self.native_host.tls_verified:self.native_host.public_settings()
            require(allow_pending_tls or self.native_host.tls_verified,503)
        else:require(self.enabled and self.missions.manager._meta_provider.mode=='MOCK',503)
        require(self.core.configured and self.runner.configured and not self.missions._closed,503)
        require(tuple(self.missions.source_probe()) == self.source, 503)

    def _run(self, purpose, callback, principal=None):
        try:
            return self.runner.run(TransactionContext(principal or self.core.local_operator(purpose), purpose), callback)
        except MemoryPatchError as exc:
            # The runner rolls back domain callback exceptions. Unwrap only this
            # closed pre-commit denial, never a commit/ACK/cleanup uncertainty.
            if (type(exc) is MemoryPatchError and exc.code is ErrorCode.TRANSACTION_FAILED
                    and type(exc.__cause__) is wire.MobileError):
                raise exc.__cause__ from None
            raise

    def _record(self, tx, key, data, prior=None, *, at):
        row = StoredRecord(RecordKind.OPERATION, key, self.scope, prior.revision+1 if prior else 1,
                           dict(schema=SCHEMA, **data))
        if prior is None:
            tx.insert(row)
        else:
            tx.replace(row, expected_revision=prior.revision)
        # The existing native domain format owns AUDIT, ordering and OUTBOX.
        # Every transport record revision receives its actual record digest;
        # no ad hoc audit payload or second publication chain is introduced.
        identity = wire.digest(wire.canonical([key, row.revision]))
        operation = OperationBinding.bind('mobile-op-'+identity,'MOBILE_TRANSPORT_RECORD',
            {'record_digest':row.payload_digest,'source_sha':self.source[0],
             'capsule_digest':self.source[1],'owner_scope_digest':self.owner_scope_digest,
             'audience':self.identity.audience})
        append_domain_event(tx,operation,event_id='mobile-audit-'+identity,
            proof_id='mobile-outbox-'+identity,resource_id=key,
            before=prior.payload.get('state') if prior else None,after=data['state'],
            content_digest=row.payload_digest,at=datetime.fromtimestamp(at,timezone.utc))
        return row

    def _get(self, key):
        return self._run(Capability.READ, lambda tx: tx.get(RecordKind.OPERATION, key))

    def issue_enrollment(self, principal, device_spki, *, ttl=300,native_request_id=None):
        """Native host-only, exact prebound transport key; never an HTTP action."""
        with self._lock:
            self._ready()
            self.core.require(principal, Capability.OWNER_APPROVAL, scope=self.scope)
            require(type(ttl) is int and 1 <= ttl <= 300, 400)
            wire.public_key(device_spki)
            if self.native_host is not None:
                require(type(native_request_id) is str and wire.HEX32.fullmatch(native_request_id),400)
            code, now = secrets.token_hex(24), int(self.clock())
            key = 'mobile-enroll-'+wire.digest(code.encode())
            data = {'state':'MOBILE_ENROLLMENT', 'device_spki':device_spki,
                'device_id':wire.digest(wire.unbase64(device_spki)), 'expires_at':now+ttl,
                'used':False, 'source_sha':self.source[0], 'capsule_digest':self.source[1],
                'owner_scope_digest':self.owner_scope_digest, 'audience':self.identity.audience}
            if self.native_host is not None:data['core_instance_id']=self.native_host.instance_id
            def save(tx):
                if self.native_host is not None:
                    request_key='mobile-owner-request-'+native_request_id
                    require(tx.get(RecordKind.OPERATION,request_key) is None,409)
                    self._record(tx,request_key,{'state':'MOBILE_OWNER_REQUEST','device_id':data['device_id'],
                        'core_instance_id':self.native_host.instance_id,'source_sha':self.source[0],
                        'capsule_digest':self.source[1]},at=now)
                require(len(tx.scan(RecordKind.OPERATION, limit=128, states=('MOBILE_ENROLLMENT',))) < 128, 429)
                self._record(tx,key,data,at=now)
            self._run(Capability.OWNER_APPROVAL, save, principal)
            return code

    @staticmethod
    def enrollment_proof(value):
        return {'schema':'aioa.mobile.enrollment-proof.v1',
            'code_sha256':wire.digest(value['code'].encode('ascii')),
            **{k:value[k] for k in ('device_spki','nonce','issued_at','audience','source_sha','capsule_digest')}}

    def _clock(self, issued):
        require(type(issued) is int and int(self.clock())-30 <= issued <= int(self.clock())+30)

    def _binding(self, data):
        if self.native_host is not None:require(data.get('core_instance_id')==self.native_host.instance_id)
        require(data.get('audience') == self.identity.audience)
        require(data['source_sha'] == self.source[0] and data['capsule_digest'] == self.source[1]
                and data['owner_scope_digest'] == self.owner_scope_digest, 503)

    def _redeem(self, value):
        require(set(value) == {'code','device_spki','nonce','issued_at','audience','source_sha','capsule_digest','signature'},400)
        require(type(value['code']) is str and len(value['code']) == 48
                and all(c in '0123456789abcdef' for c in value['code']))
        require(type(value['nonce']) is str and wire.HEX32.fullmatch(value['nonce']))
        self._clock(value['issued_at'])
        require(value['audience'] == self.identity.audience)
        require((value['source_sha'],value['capsule_digest']) == self.source,503)
        wire.verify(value['device_spki'],value['signature'],self.enrollment_proof(value))
        key, now = 'mobile-enroll-'+wire.digest(value['code'].encode()), int(self.clock())
        token, session_id = secrets.token_urlsafe(32), secrets.token_hex(16)
        token_hash = wire.digest(token.encode('ascii'))
        device_id = wire.digest(wire.unbase64(value['device_spki']))
        def redeem(tx):
            row=tx.get(RecordKind.OPERATION,key)
            require(row is not None and row.payload.get('schema') == SCHEMA)
            data=plain(row.payload)
            require(not data['used'] and now < data['expires_at'] and data['device_spki'] == value['device_spki'])
            self._binding(data)
            data.pop('schema');data['used']=True
            self._record(tx,key,data,row,at=now)
            return self._issue_session(tx,value['device_spki'],now,token=token,session_id=session_id)
        self._run(Capability.COMMIT,redeem)
        session=plain(self._get('mobile-session-'+token_hash).payload)
        request=Session(token_hash,session,value['nonce'],'POST',wire.BASE+'/enrollment/redeem')
        return self._observe(request,{'token':token,'session_id':session_id,'device_id':device_id,
                                    'expires_at':session['expires_at'],'owner_authority':'NOT_BOUND'})

    def _revoke_device_sessions(self,tx,device_id,now):
        count=0
        for old in tx.scan(RecordKind.OPERATION,limit=128,states=('MOBILE_SESSION',)):
            if old.payload['device_id']==device_id and not old.payload['revoked']:
                prior=plain(old.payload);prior.pop('schema');prior['revoked']=True
                self._record(tx,old.record_id,prior,old,at=now);count+=1
        return count

    def _issue_session(self,tx,device_spki,now,*,binding_id=None,token=None,session_id=None):
        """Shared v1 enrollment/reconnect issuer in the caller's Core transaction."""
        session_key='mobile-session-device-'+binding_id if binding_id else None
        old=tx.get(RecordKind.OPERATION,session_key) if session_key else None
        if old is None:require(len(tx.scan(RecordKind.OPERATION,limit=128,states=('MOBILE_SESSION',)))<128,429)
        device_id=wire.digest(wire.unbase64(device_spki))
        self._revoke_device_sessions(tx,device_id,now)
        token=token or secrets.token_urlsafe(32);session_id=session_id or secrets.token_hex(16)
        session={'state':'MOBILE_SESSION','device_spki':device_spki,
            'device_id':device_id,'session_id':session_id,'source_sha':self.source[0],
            'capsule_digest':self.source[1],'owner_scope_digest':self.owner_scope_digest,
            'expires_at':now+600,'revoked':False,'nonce_count':0,'audience':self.identity.audience}
        if self.native_host is not None:session['core_instance_id']=self.native_host.instance_id
        token_hash=wire.digest(token.encode('ascii'))
        if binding_id is not None:
            session.update(binding_id=binding_id,token_hash=token_hash)
            old=tx.get(RecordKind.OPERATION,session_key)
        self._record(tx,session_key or 'mobile-session-'+token_hash,session,old,at=now)
        return {'token':token,'session_id':session_id,'device_id':device_id,
            'expires_at':session['expires_at'],'owner_authority':'NOT_BOUND'}

    def _session_row(self,token_hash):
        def lookup(tx):
            direct=tx.get(RecordKind.OPERATION,'mobile-session-'+token_hash)
            found=[row for row in tx.scan(RecordKind.OPERATION,limit=128,states=('MOBILE_SESSION',))
                if row.payload.get('token_hash')==token_hash]
            require(len(found)+(1 if direct else 0)<=1)
            return direct or (found[0] if found else None)
        return self._run(Capability.READ,lookup)

    def _authenticate(self, method, path, headers, body):
        auth=headers.get('Authorization','')
        require(auth.startswith('Bearer ') and len(auth) == 50)
        token=auth[7:]
        require(all(c in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_' for c in token))
        nonce=headers.get('X-AIOA-Nonce','')
        require(wire.HEX32.fullmatch(nonce))
        issued=headers.get('X-AIOA-Issued-At','')
        require(issued.isascii() and issued.isdecimal() and len(issued)<=12)
        issued=int(issued);self._clock(issued)
        require(headers.get('X-AIOA-Audience') == self.identity.audience)
        require((headers.get('X-AIOA-Source-SHA'),headers.get('X-AIOA-Capsule')) == self.source,503)
        token_hash=wire.digest(token.encode())
        row=self._session_row(token_hash)
        require(row is not None and row.payload.get('schema') == SCHEMA)
        key=row.record_id
        session=plain(row.payload)
        self._binding(session)
        require(not session['revoked'] and int(self.clock()) < session['expires_at'])
        if 'binding_id' in session:
            row_binding=self._get('mobile-device-'+session['binding_id'])
            require(row_binding is not None and not row_binding.payload['revoked'],403)
        proof=wire.request_proof(method,path,body,token=token,nonce=nonce,issued_at=issued,
            audience=self.identity.audience,source_sha=self.source[0],capsule_digest=self.source[1])
        wire.verify(session['device_spki'],headers.get('X-AIOA-Signature',''),proof)
        now=int(self.clock())
        nonce_key='mobile-nonce-'+wire.digest((session['session_id']+nonce).encode())
        def consume(tx):
            current=tx.get(RecordKind.OPERATION,key)
            require(current is not None and current.revision == row.revision)
            data=plain(current.payload);self._binding(data)
            require(not data['revoked'] and now < data['expires_at'])
            require(tx.get(RecordKind.OPERATION,nonce_key) is None,409)
            require(data['nonce_count']<512,429)
            self._record(tx,nonce_key,{'state':'MOBILE_NONCE','proof_sha256':wire.digest(wire.canonical(proof))},at=now)
            data.pop('schema');data['nonce_count']+=1
            self._record(tx,key,data,current,at=now)
        self._run(Capability.COMMIT,consume)
        return Session(token_hash,session,nonce,method,path)

    def _observe(self, session, data):
        self._ready()
        now=int(self.clock())
        proof={'schema':'aioa.mobile.observation.v1','audience':self.identity.audience,
            **{k:session.data[k] for k in SCOPE_FIELDS},'nonce':session.nonce,'method':session.method,
            'path':session.path,'issued_at':now,'expires_at':now+30,'data_sha256':wire.digest(wire.canonical(data))}
        response={'ok':True,'data':data,'proof':proof,'signature':self.identity.sign(proof)}
        require(len(wire.canonical(response)) <= wire.RESPONSE_LIMIT,413)
        if self.native_host is not None:
            key='mobile-observation-'+wire.digest(wire.canonical([session.data['session_id'],session.nonce,session.path]))
            record={'state':'MOBILE_OBSERVATION','device_id':session.data['device_id'],
                'session_id':session.data['session_id'],'proof':proof,'signature':response['signature'],
                'core_instance_id':self.native_host.instance_id}
            self._run(Capability.COMMIT,lambda tx:self._record(tx,key,record,at=now))
        return response

    def _host_proof(self, headers):
        challenge=headers.get('X-AIOA-Challenge','')
        require(wire.HEX64.fullmatch(challenge),400)
        capabilities={'schema':'aioa.mobile.capabilities.v1','profile':'OFFLINE_FIXTURE',
            'status':True,'preview':True,'evidence':True,'stop':True,'run':False,'approve':False,
            'chat':False,'meta_spend':False,'native_execute':False,'github_write':False,'install':False,
            'owner_pairing_m12':False,'remote_deployment':'REMOTE_DEPLOYMENT_BLOCKED'}
        if self.native_host is not None:
            capabilities.update(profile='NATIVE_STATUS_READ_ONLY_V1',preview=False,evidence=False,stop=False,
                remote_deployment='TLS_HOST_VERIFIED' if self.native_host.tls_verified else 'TLS_QUALIFICATION_PENDING')
        now=int(self.clock())
        proof={'schema':'aioa.mobile.host-proof.v1','challenge':challenge,'origin':self.origin,
            'audience':self.identity.audience,'host_spki':self.identity.spki,'issued_at':now,'expires_at':now+30,
            'source_sha':self.source[0],'capsule_digest':self.source[1],
            'owner_scope_digest':self.owner_scope_digest,
            'capabilities_sha256':wire.digest(wire.canonical(capabilities))}
        return {'ok':True,'capabilities':capabilities,'proof':proof,'signature':self.identity.sign(proof)}

    def _linked(self, session, task_id):
        row=self._get('mobile-task-'+task_id)
        require(row is not None and row.payload.get('schema') == SCHEMA,403)
        data=plain(row.payload)
        require(all(data[k] == session.data[k] for k in SCOPE_FIELDS),403)
        record=self.missions.evidence(task_id,self.core.local_operator(Capability.READ))
        require(all(data[k] == record[k] for k in ('task_digest','source_sha','capsule_digest','owner_scope_digest')),503)
        return record

    def _project(self, record):
        receipt=record.get('browser_receipt')
        if receipt is not None:
            require(all(receipt.get(k) == record[k] for k in ('task_digest','source_sha','capsule_digest','owner_scope_digest')),503)
            require(wire.HEX64.fullmatch(receipt.get('content_sha256','')),503)
        return {**{k:record[k] for k in ('task_id','task_digest','source_sha','capsule_digest','owner_scope_digest',
                    'provider_id','model_id','mode','state','stopped','created_at')},
            'schema':'aioa.mobile.mission-view.v1','verified':False,'live_verified':False,
            'billing':'UNVERIFIED','owner_authority':'NOT_BOUND','can_run':False,
            'receipt':None if receipt is None else {'kind':'OFFLINE_FIXTURE',
                'content_sha256':receipt['content_sha256'],'verified':False},
            'readback_required':record['state']=='UNKNOWN'}

    def _preview(self, session, value):
        require(set(value)=={'proposal_id','instruction','mode','target_url'},400)
        proposal_id=value['proposal_id']
        require(type(proposal_id) is str and wire.HEX32.fullmatch(proposal_id),400)
        require(value['mode']=='OFFLINE_FIXTURE',403)
        try:
            MissionRequest.parse({k:value[k] for k in ('instruction','mode','target_url')})
        except MissionError:
            raise wire.MobileError(400) from None
        key='mobile-proposal-'+wire.digest((session.data['session_id']+proposal_id).encode())
        started_at=int(self.clock())
        marker={k:session.data[k] for k in SCOPE_FIELDS}
        marker.update(state='MOBILE_PROPOSAL',task_id=None,proposal_id=proposal_id,
                      request_digest=wire.digest(wire.canonical(value)))
        def begin(tx):
            require(tx.get(RecordKind.OPERATION,key) is None,409)
            require(len(tx.scan(RecordKind.OPERATION,limit=128,states=('MOBILE_TASK',)))<128,429)
            self._record(tx,key,marker,at=started_at)
        self._run(Capability.COMMIT,begin)
        # Separate transaction from Core's proposal: a crash may leave an orphan
        # proposal. Marker readback remains UNKNOWN, and no effect/retry is allowed.
        record=self.missions.preview({k:value[k] for k in ('instruction','mode','target_url')},
                                     self.core.local_operator(Capability.READ))
        self._ready()
        require(all(record[k] == session.data[k] for k in ('source_sha','capsule_digest','owner_scope_digest')),503)
        linked_at=int(self.clock())
        def link(tx):
            row=tx.get(RecordKind.OPERATION,key)
            require(row is not None and row.payload['task_id'] is None,409)
            self._record(tx,key,dict(marker,task_id=record['task_id']),row,at=linked_at)
            self._record(tx,'mobile-task-'+record['task_id'],{**marker,'state':'MOBILE_TASK',
                'task_id':record['task_id'],'task_digest':record['task_digest'],
                'created_order':record['created_order']},at=linked_at)
        self._run(Capability.COMMIT,link)
        return self._project(record)

    def _dispatch(self, action, identity, session, value):
        if action.startswith('agent_'):
            from .views_v2 import dispatch
            return dispatch(self,action,identity,session,value)
        if action=='preview':return self._preview(session,value)
        if action=='revoke':
            require(value=={},400)
            row=self._session_row(session.token_hash);require(row is not None)
            key=row.record_id
            revoked_at=int(self.clock())
            def revoke(tx):
                row=tx.get(RecordKind.OPERATION,key);data=plain(row.payload);data.pop('schema');data['revoked']=True
                self._record(tx,key,data,row,at=revoked_at)
            self._run(Capability.COMMIT,revoke)
            return {'revoked':True,'owner_authority':'NOT_BOUND'}
        if action in ('status','status_page'):
            rows=self._run(Capability.READ,lambda tx:tx.scan(RecordKind.OPERATION,limit=128,states=('MOBILE_TASK',)))
            mine=[r for r in rows if all(r.payload[k]==session.data[k] for k in SCOPE_FIELDS)]
            mine.sort(key=lambda r:(r.payload.get('created_order',0),r.payload['task_id']),reverse=True)
            start=0
            if action=='status_page':
                ids=[r.payload['task_id'] for r in mine]
                require(identity in ids,403)
                start=ids.index(identity)+1
            page=mine[start:start+16]
            records=self.missions.evidence_many(tuple(r.payload['task_id'] for r in page),
                        self.core.local_operator(Capability.READ)) if page else ()
            for row,record in zip(page,records):
                require(all(row.payload[k]==record[k] for k in ('task_id','task_digest','source_sha',
                            'capsule_digest','owner_scope_digest')),503)
            views=[self._project(record) for record in records]
            more=start+len(page)<len(mine)
            return {'schema':'aioa.mobile.status.v1','mode':'NATIVE_STATUS_READ_ONLY_V1' if self.native_host else 'OFFLINE_FIXTURE','missions':views,
                'total_missions':len(mine),'history_truncated':more,
                'next_cursor':page[-1].payload['task_id'] if more else None,
                'owner_authority':'NOT_BOUND','billing':'UNVERIFIED','live_verified':False,
                'remote_deployment':'TLS_HOST_VERIFIED' if self.native_host else 'REMOTE_DEPLOYMENT_BLOCKED'}
        if action=='proposal':
            key='mobile-proposal-'+wire.digest((session.data['session_id']+identity).encode())
            row=self._get(key)
            require(row is not None and all(row.payload[k]==session.data[k] for k in SCOPE_FIELDS),403)
            if row.payload['task_id'] is None:
                return {'state':'UNKNOWN','readback_required':True,'automatic_retry':False,'verified':False}
            identity=row.payload['task_id']
        if action=='stop':
            require(set(value)=={'task_id'} and type(value['task_id']) is str and wire.TASK.fullmatch(value['task_id']),400)
            identity=value['task_id']
        record=self._linked(session,identity)
        if action=='stop':
            record=self.missions.stop(identity,self.core.local_operator(Capability.READ))
        return self._project(record)

    def handle(self, method, path, headers, body):
        """Bounded response only; never leaks exceptions, tokens, code or task text."""
        with self._lock:
            try:
                require(type(body) is bytes and len(body)<=wire.BODY_LIMIT,413)
                action,identity=wire.route(method,path)
                self._ready(allow_pending_tls=action=='capabilities')
                if self.native_host is not None:require(action in {'capabilities','redeem','status','status_page','revoke','pairing_begin','pairing_status','pairing_complete','session_challenge','session_reconnect'},501)
                if method=='GET':require(not body,400)
                value=wire.strict_json(body) if method=='POST' else {}
                if action=='capabilities':return 200,self._host_proof(headers)
                if action=='redeem':return 200,self._redeem(value)
                if action.startswith('pairing_') or action in {'session_challenge','session_reconnect'}:
                    require(self.native_host is not None,503)
                    from .pairing import Pairing
                    return 200,Pairing(self).handle(action,path,value)
                session=self._authenticate(method,path,headers,body)
                return 200,self._observe(session,self._dispatch(action,identity,session,value))
            except wire.MobileError as exc:
                return exc.status,{'ok':False,'error':exc.code,'automatic_retry':False}
            except Exception:
                # CommitOutcomeUnknown, unexpected receipt/IO/core failure: no retry.
                return 503,{'ok':False,'error':wire.ERRORS[503],'automatic_retry':False}
