"""QA-only ephemeral signed device; no phone or production owner claim."""
import secrets
from cryptography.hazmat.primitives.asymmetric import ec
from runtime.mobile_gateway import wire


class SignedDeviceFixture:
    def __init__(self,gateway,owner,*,identity=None):
        self.gateway=gateway;self.device=identity or wire.Identity(ec.generate_private_key(ec.SECP256R1()))
        code=gateway.issue_enrollment(owner,self.device.spki)
        source=gateway.source
        value={'code':code,'device_spki':self.device.spki,'nonce':secrets.token_hex(16),
            'issued_at':int(gateway.clock()),'audience':gateway.identity.audience,
            'source_sha':source[0],'capsule_digest':source[1]}
        value['signature']=self.device.sign(gateway.enrollment_proof(value))
        status,response=gateway.handle('POST',wire.BASE+'/enrollment/redeem',{},wire.canonical(value))
        if status!=200:raise ValueError('fixture enrollment failed')
        self.token=response['data']['token']
        self.verify(response,value['nonce'],'POST',wire.BASE+'/enrollment/redeem')

    def frame(self,method,path,value=None):
        raw=b'' if value is None else wire.canonical(value);gateway=self.gateway
        proof=wire.request_proof(method,path,raw,token=self.token,nonce=secrets.token_hex(16),
            issued_at=int(gateway.clock()),audience=gateway.identity.audience,
            source_sha=gateway.source[0],capsule_digest=gateway.source[1])
        headers={'Authorization':'Bearer '+self.token,'X-AIOA-Nonce':proof['nonce'],
            'X-AIOA-Issued-At':str(proof['issued_at']),'X-AIOA-Audience':proof['audience'],
            'X-AIOA-Source-SHA':proof['source_sha'],'X-AIOA-Capsule':proof['capsule_digest'],
            'X-AIOA-Signature':self.device.sign(proof)}
        return method,path,headers,raw

    def verify(self,response,nonce,method,path):
        proof=response['proof']
        wire.verify(self.gateway.identity.spki,response['signature'],proof)
        if (proof['nonce'],proof['method'],proof['path'],proof['data_sha256'])!=(nonce,method,path,
            wire.digest(wire.canonical(response['data']))):raise ValueError('invalid signed fixture observation')

    def request(self,method,path,value=None):
        frame=self.frame(method,path,value);status,response=self.gateway.handle(*frame)
        if status==200:self.verify(response,frame[2]['X-AIOA-Nonce'],method,path)
        return status,response
