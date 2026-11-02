"""One-tap transport adapter over the existing Core runner, records and sessions.

Public packets are not authority. Only the private OS-admitted owner port can
approve the exact request digest. No provider, listener, database or Core here.
"""
import secrets
from runtime.core_admission import Capability
from runtime.memory_patch.persistence.ports import RecordKind
from . import wire
from .service import plain, require

COMMON={'schema','device_spki','nonce','issued_at','audience','origin','source_sha','capsule_digest','signature'}
EXTRA={
    'pairing_begin':{'invite','request_id','device_name'},
    'pairing_status':{'request_id'}, 'pairing_complete':{'request_id'},
    'session_challenge':{'device_id'},
    'session_reconnect':{'device_id','challenge_id','challenge_nonce'}}
OWNER_FIELDS={'pairing_invite':{'op'},'pairing_list':{'op'},
    'pairing_approve':{'op','request_id','request_digest','sas'},
    'pairing_revoke':{'op','device_id'}}


class Pairing:
    def __init__(self,gateway):
        self.g=gateway

    def _save(self,tx,key,data,row=None):
        data={k:v for k,v in data.items() if k!='schema'}
        return self.g._record(tx,key,data,row,at=int(self.g.clock()))

    def _bound(self,data):
        require(data.get('audience')==self.g.identity.audience and data.get('origin')==self.g.origin)
        require(data.get('owner_scope_digest')==self.g.owner_scope_digest)

    def _device(self,tx,device_id,spki=None):
        row=tx.get(RecordKind.OPERATION,'mobile-device-'+device_id)
        require(row is not None)
        self._bound(row.payload)
        if spki is not None:require(row.payload['device_spki']==spki)
        require(not row.payload['revoked'],403)
        return row

    def _nonce(self,tx,row,value):
        data=plain(row.payload)
        if data['state']=='MOBILE_DEVICE':
            recent=[item for item in data.get('recent_nonces',[]) if item['expires_at']>=int(self.g.clock())]
            require(not any(item['nonce']==value['nonce'] for item in recent),409)
            require(len(recent)<128,429)
            recent.append({'nonce':value['nonce'],'expires_at':value['issued_at']+30})
            data['recent_nonces']=recent
            return self._save(tx,row.record_id,data,row)
        key='mobile-pairing-nonce-'+wire.digest(wire.canonical([row.record_id,value['nonce']]))
        require(tx.get(RecordKind.OPERATION,key) is None,409)
        require(data.get('nonce_count',0)<128,429)
        self._save(tx,key,{'state':'MOBILE_PAIRING_NONCE','request_sha256':wire.digest(wire.canonical(value))})
        data['nonce_count']=data.get('nonce_count',0)+1
        return self._save(tx,row.record_id,data,row)

    def owner(self,principal,value):
        g=self.g
        with g._lock:
            g._ready();g.core.require(principal,Capability.OWNER_APPROVAL,scope=g.scope)
            op=value['op'];require(set(value)==OWNER_FIELDS[op],400)
            now=int(g.clock())
            if op=='pairing_invite':
                invite=dict(schema='aioa.mobile.pairing-invite.v1',invite_id=secrets.token_hex(16),
                    origin=g.origin,host_spki=g.identity.spki,audience=g.identity.audience,
                    tls_spki_pin=g.native_host.public_settings()['tls_spki_pin'],
                    source_sha=g.source[0],capsule_digest=g.source[1],owner_scope_digest=g.owner_scope_digest,
                    issued_at=now,expires_at=now+300)
                packet={'invite':invite,'signature':g.identity.sign(invite)}
                def save(tx):
                    require(len(tx.scan(RecordKind.OPERATION,limit=128,states=('MOBILE_PAIRING_INVITE',)))<128,429)
                    self._save(tx,'mobile-invite-'+invite['invite_id'],dict(state='MOBILE_PAIRING_INVITE',
                        packet=packet,used=False,core_instance_id=g.native_host.instance_id))
                g._run(Capability.OWNER_APPROVAL,save,principal)
                return packet
            if op=='pairing_list':
                def listing(tx):
                    pending=tx.scan(RecordKind.OPERATION,limit=128,states=('MOBILE_PAIRING_REQUEST',))
                    devices=tx.scan(RecordKind.OPERATION,limit=128,states=('MOBILE_DEVICE',))
                    return {'pending':[self._view(tx,r) for r in pending if r.payload['core_instance_id']==g.native_host.instance_id],
                        'devices':[{k:r.payload[k] for k in ('device_id','device_name','revoked','approved_at','audience','origin')} for r in devices]}
                return g._run(Capability.READ,listing)
            if op=='pairing_approve':
                require(type(value['request_id']) is str and wire.HEX32.fullmatch(value['request_id']),400)
                require(type(value['request_digest']) is str and wire.HEX64.fullmatch(value['request_digest']),400)
                require(type(value['sas']) is str and len(value['sas'])==6 and value['sas'].isascii() and value['sas'].isdecimal(),400)
                def approve(tx):
                    row=tx.get(RecordKind.OPERATION,'mobile-pairing-'+value['request_id']);require(row is not None)
                    data=plain(row.payload);g._binding(data);self._bound(data)
                    require(now<data['expires_at'])
                    require(data['phase']=='PENDING',409)
                    require(value['request_digest']==data['request_digest'] and value['sas']==data['sas'])
                    key='mobile-device-'+data['device_id'];old=tx.get(RecordKind.OPERATION,key)
                    if old is None:require(len(tx.scan(RecordKind.OPERATION,limit=128,states=('MOBILE_DEVICE',)))<128,429)
                    else:self._bound(old.payload)
                    binding={k:data[k] for k in ('device_id','device_spki','device_name','audience','origin','owner_scope_digest')}
                    binding.update(state='MOBILE_DEVICE',revoked=False,approved_at=now,
                        approval_request_digest=data['request_digest'],approval_instance_id=g.native_host.instance_id,
                        approval_source_sha=g.source[0],approval_capsule_digest=g.source[1],
                        nonce_count=0,challenge_count=0,scope='STATUS_READ_ONLY')
                    # A new approval cannot make a consumed signed request fresh.
                    # Retain the accepted nonce through the full timestamp window.
                    if old is not None:
                        binding['recent_nonces']=[dict(item) for item in old.payload.get('recent_nonces',())
                            if item['expires_at']>=now]
                    self._save(tx,key,binding,old)
                    data['phase']='APPROVED';self._save(tx,row.record_id,data,row)
                    return self._view(tx,tx.get(RecordKind.OPERATION,row.record_id))
                return g._run(Capability.OWNER_APPROVAL,approve,principal)
            require(type(value['device_id']) is str and wire.HEX64.fullmatch(value['device_id']),400)
            def revoke(tx):
                row=self._device(tx,value['device_id']);data=plain(row.payload);data['revoked']=True
                self._save(tx,row.record_id,data,row)
                count=g._revoke_device_sessions(tx,value['device_id'],now)
                # Legacy grants are also preauthorized paths to a session. Consume
                # every outstanding grant atomically with durable revocation.
                for grant in tx.scan(RecordKind.OPERATION,limit=128,states=('MOBILE_ENROLLMENT',)):
                    if grant.payload['device_id']==value['device_id'] and not grant.payload['used']:
                        invalidated=plain(grant.payload);invalidated.update(used=True,revoked=True)
                        self._save(tx,grant.record_id,invalidated,grant)
                return {'device_id':value['device_id'],'revoked':True,'revoked_sessions':count}
            return g._run(Capability.OWNER_APPROVAL,revoke,principal)

    def _view(self,tx,row):
        data=row.payload
        state=data['phase']
        binding=tx.get(RecordKind.OPERATION,'mobile-device-'+data['device_id'])
        if (binding is not None and state in {'APPROVED','COMPLETED'} and
                (binding.payload['revoked'] or binding.payload['approval_request_digest']!=data['request_digest'])):
            state='REVOKED'
        elif int(self.g.clock())>=data['expires_at'] and state!='COMPLETED':state='EXPIRED'
        return {**{k:data[k] for k in ('request_id','request_digest','device_id','device_name','sas','expires_at')},
            'state':state,'automatic_retry':False}

    def handle(self,action,path,value):
        g=self.g;now=int(g.clock())
        require(set(value)==COMMON|EXTRA[action],400)
        require(value['schema']=='aioa.mobile.pairing-request.v1',400)
        for name in ('nonce','request_id','challenge_id','challenge_nonce'):
            if name in value:require(type(value[name]) is str and wire.HEX32.fullmatch(value[name]),400)
        if 'device_id' in value:require(type(value['device_id']) is str and wire.HEX64.fullmatch(value['device_id']),400)
        g._clock(value['issued_at'])
        require(value['audience']==g.identity.audience and value['origin']==g.origin)
        require((value['source_sha'],value['capsule_digest'])==g.source,503)
        proof={k:v for k,v in value.items() if k!='signature'};proof.update(method='POST',path=path)
        wire.verify(value['device_spki'],value['signature'],proof)
        device_id=wire.digest(wire.unbase64(value['device_spki']))
        request_digest=wire.digest(wire.canonical(proof))
        if action=='pairing_begin':
            name=value['device_name']
            require(type(name) is str and 1<=len(name)<=64 and all(' '<=c<='~' for c in name),400)
            packet=value['invite'];require(type(packet) is dict and set(packet)=={'invite','signature'},400)
            invite=packet['invite'];require(type(invite) is dict,400)
            wire.verify(g.identity.spki,packet['signature'],invite)
            require(set(invite)=={'schema','invite_id','origin','host_spki','audience','tls_spki_pin','source_sha','capsule_digest','owner_scope_digest','issued_at','expires_at'},400)
            require(invite['schema']=='aioa.mobile.pairing-invite.v1' and type(invite['invite_id']) is str and wire.HEX32.fullmatch(invite['invite_id']),400)
            require(invite['origin']==g.origin and invite['host_spki']==g.identity.spki and invite['audience']==g.identity.audience)
            require(invite['issued_at']<=now<invite['expires_at']<=invite['issued_at']+300)
            require((invite['source_sha'],invite['capsule_digest'])==g.source,503)
            def begin(tx):
                row=tx.get(RecordKind.OPERATION,'mobile-invite-'+invite['invite_id']);require(row is not None)
                require(row.payload['core_instance_id']==g.native_host.instance_id)
                require(plain(row.payload['packet'])==packet)
                require(not row.payload['used'],409)
                key='mobile-pairing-'+value['request_id'];require(tx.get(RecordKind.OPERATION,key) is None,409)
                data=dict(state='MOBILE_PAIRING_REQUEST',phase='PENDING',device_id=device_id,
                    request_id=value['request_id'],request_digest=request_digest,device_spki=value['device_spki'],
                    device_name=name,sas=str(int(request_digest[:8],16)%1000000).zfill(6),expires_at=invite['expires_at'],
                    core_instance_id=g.native_host.instance_id,audience=g.identity.audience,origin=g.origin,
                    source_sha=g.source[0],capsule_digest=g.source[1],owner_scope_digest=g.owner_scope_digest,nonce_count=0)
                record=self._save(tx,key,data)
                old=plain(row.payload);old['used']=True;self._save(tx,row.record_id,old,row)
                self._nonce(tx,record,value)
                return self._view(tx,record)
            data=g._run(Capability.COMMIT,begin)
        elif action in {'pairing_status','pairing_complete'}:
            def access(tx):
                row=tx.get(RecordKind.OPERATION,'mobile-pairing-'+value['request_id']);require(row is not None)
                require(row.payload['device_spki']==value['device_spki'])
                g._binding(row.payload);self._bound(row.payload)
                row=self._nonce(tx,row,value)
                if action=='pairing_status':return self._view(tx,row)
                require(row.payload['phase']!='COMPLETED',409)
                require(row.payload['phase']=='APPROVED',403)
                require(now<row.payload['expires_at'])
                binding=self._device(tx,device_id,value['device_spki'])
                require(binding.payload['approval_request_digest']==row.payload['request_digest'],403)
                record=plain(row.payload);record['phase']='COMPLETED';self._save(tx,row.record_id,record,row)
                return g._issue_session(tx,value['device_spki'],now,binding_id=device_id)
            data=g._run(Capability.COMMIT,access)
        else:
            require(value['device_id']==device_id)
            def reconnect(tx):
                row=self._device(tx,device_id,value['device_spki'])
                # Approval provenance is stable across nonce counters; replacement
                # approval invalidates every challenge from the prior binding.
                approval=row.payload['approval_request_digest']
                row=self._nonce(tx,row,value)
                if action=='session_challenge':
                    challenge_id,nonce=secrets.token_hex(16),secrets.token_hex(16)
                    result=dict(device_id=device_id,challenge_id=challenge_id,challenge_nonce=nonce,expires_at=now+60)
                    challenge_key='mobile-challenge-'+device_id
                    prior_challenge=tx.get(RecordKind.OPERATION,challenge_key)
                    self._save(tx,challenge_key,dict(result,state='MOBILE_RECONNECT_CHALLENGE',
                        used=False,approval_request_digest=approval,core_instance_id=g.native_host.instance_id,
                        source_sha=g.source[0],capsule_digest=g.source[1],audience=g.identity.audience,
                        owner_scope_digest=g.owner_scope_digest,origin=g.origin),prior_challenge)
                    return result
                challenge=tx.get(RecordKind.OPERATION,'mobile-challenge-'+device_id);require(challenge is not None)
                saved=plain(challenge.payload);g._binding(saved);self._bound(saved)
                require(not saved['used'],409)
                require(saved['device_id']==device_id and saved['challenge_id']==value['challenge_id'] and saved['challenge_nonce']==value['challenge_nonce']
                    and saved['approval_request_digest']==approval and now<saved['expires_at'])
                saved['used']=True;self._save(tx,challenge.record_id,saved,challenge)
                return g._issue_session(tx,value['device_spki'],now,binding_id=device_id)
            data=g._run(Capability.COMMIT,reconnect)
        response_proof=dict(schema='aioa.mobile.pairing-response.v1',method='POST',path=path,
            request_sha256=wire.digest(wire.canonical(value)),nonce=value['nonce'],audience=g.identity.audience,
            origin=g.origin,source_sha=g.source[0],capsule_digest=g.source[1],owner_scope_digest=g.owner_scope_digest,
            issued_at=now,expires_at=now+30,data_sha256=wire.digest(wire.canonical(data)))
        g._ready()
        return dict(ok=True,data=data,proof=response_proof,signature=g.identity.sign(response_proof))
