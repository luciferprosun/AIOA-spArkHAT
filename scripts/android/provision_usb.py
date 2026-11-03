"""Explicit USB delivery into the existing app/Core; never export a key or session.

The operator authorizes this exact connected installation. Core still enforces
the actual local principal/PolicyKit lease. Each uncertain mutation stops; this
helper never retries BEGIN, APPROVE or COMPLETE.
"""
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import time

from runtime.mobile_gateway import wire
from runtime.webapp import mobile_operator_client
from scripts.android import cosmic4_channel as channel


def require(condition):
    if not condition:raise ValueError('USB_PROVISIONING_DENIED_OR_UNKNOWN')


def sas(digest):
    require(type(digest) is str and wire.HEX64.fullmatch(digest))
    return str(int(digest[:8],16)%1000000).zfill(6)


def verify_identity(value,challenge,source,now):
    require(type(value) is dict and set(value)=={'proof','signature'})
    p=value['proof']
    require(type(p) is dict and set(p)=={'schema','challenge','issued_at','package','certificate_sha256','apk_source_sha','device_spki'})
    require(p['schema']=='aioa.mobile.usb-identity.v1' and p['challenge']==challenge
        and wire.HEX64.fullmatch(challenge) and p['package']==channel.PACKAGE
        and p['certificate_sha256']==channel.CERTIFICATE and p['apk_source_sha']==source
        and wire.SHA40.fullmatch(source) and type(p['issued_at']) is int and now-30<=p['issued_at']<=now)
    wire.verify(p['device_spki'],value['signature'],p)
    return p['device_spki']


def verify_pending(pending,record,device,now):
    require(type(pending) is dict and all(pending.get(k)==record.get(k)
        for k in ('request_id','request_digest','expires_at'))
        and pending.get('device_id')==device and pending.get('sas')==sas(record['request_digest'])
        and pending.get('state')=='PENDING' and pending.get('automatic_retry') is False
        and type(pending['expires_at']) is int and now<pending['expires_at'])


def claim_approval(path,operation):
    # Exclusive and fsynced BEFORE dispatch. Restart/ACK loss is readback only.
    try:fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
    except FileExistsError:raise ValueError('APPROVAL_ALREADY_ATTEMPTED_READBACK_REQUIRED') from None
    with os.fdopen(fd,'wb') as stream:
        stream.write(wire.canonical({'state':'APPROVAL_ATTEMPTED_UNKNOWN_UNTIL_READBACK','operation':operation}))
        stream.flush();os.fsync(stream.fileno())
    parent=os.open(path.parent,os.O_RDONLY|os.O_DIRECTORY)
    try:os.fsync(parent)
    finally:os.close(parent)


def verify_status_readback(app,observations,spki,device,source,capsule,now):
    require(type(app) is dict and set(app)=={'proof','signature','fresh'} and app['fresh'] is True)
    proof=app['proof'];signature=app['signature']
    require(type(proof) is dict)
    wire.verify(spki,signature,proof)
    require(proof.get('schema')=='aioa.mobile.observation.v1' and proof.get('path')==wire.BASE+'/status'
        and proof.get('method')=='GET' and proof.get('device_id')==device
        and proof.get('source_sha')==source and proof.get('capsule_digest')==capsule
        and proof.get('audience')==wire.digest(wire.unbase64(spki))
        and wire.HEX32.fullmatch(proof.get('nonce','')) and wire.HEX32.fullmatch(proof.get('session_id',''))
        and wire.HEX64.fullmatch(proof.get('data_sha256',''))
        and type(proof.get('issued_at')) is int and type(proof.get('expires_at')) is int
        and proof['issued_at']<=now<proof['expires_at']<=proof['issued_at']+30)
    require({'proof':proof,'signature':signature} in observations)
    return {'proof':proof,'signature':signature}


def parse_content_stdout(output):
    match=re.fullmatch(r'Result: Bundle\[\{json_b64=([A-Za-z0-9_-]+)\}\]\r?\n?',output)
    require(match is not None)
    encoded=match[1];raw=base64.urlsafe_b64decode(encoded+'='*((-len(encoded))%4))
    require(base64.urlsafe_b64encode(raw).decode().rstrip('=')==encoded)
    result=wire.strict_json(raw);require(wire.canonical(result)==raw)
    return result


class UsbDelivery:
    def __init__(self,serial,source,state_dir,evidence,apk):
        require(type(serial) is str and re.fullmatch(r'[A-Za-z0-9]{8,32}',serial))
        require(wire.SHA40.fullmatch(source))
        self.serial=serial;self.source=source;self.state_dir=state_dir;self.evidence=evidence;self.apk=apk
    def adb(self,*args):
        result=subprocess.run(['adb','-s',self.serial,*args],stdin=subprocess.DEVNULL,capture_output=True,timeout=35)
        require(result.returncode==0 and len(result.stdout)+len(result.stderr)<=65536)
        return result.stdout.decode('utf-8','strict')
    def call(self,method,arg=None):
        command=['shell','content','call','--uri','content://'+channel.PACKAGE+'.usb','--method',method]
        if arg is not None:
            require(re.fullmatch(r'[A-Za-z0-9_-]{1,22000}',arg))
            command+=['--arg',arg]
        return parse_content_stdout(self.adb(*command))
    def installed_bytes(self):
        path=self.adb('shell','pm','path',channel.PACKAGE).strip()
        require(re.fullmatch(r'package:/data/app/[A-Za-z0-9_~=/+.-]+/base\.apk',path))
        result=subprocess.run(['adb','-s',self.serial,'exec-out','cat',path.removeprefix('package:')],
            capture_output=True,stdin=subprocess.DEVNULL,timeout=35)
        require(result.returncode==0 and not result.stderr and 0<len(result.stdout)<=128*1024*1024)
        return result.stdout
    def verify_installation(self):
        # The local APK is independently verified against CI evidence/apksigner
        # before invocation. Match actual installed bytes, not app self-report.
        require(self.apk.is_file() and not self.apk.is_symlink() and 0<self.apk.stat().st_size<=128*1024*1024)
        expected=self.apk.read_bytes();installed=self.installed_bytes()
        require(len(installed)==len(expected) and hashlib.sha256(installed).digest()==hashlib.sha256(expected).digest())
    def prepare_idle_installation(self,spki):
        def idle():
            state=self.call('state')
            require(state['pairing'] is None and state['binding_invalid'] is False and state['delivery']['delivery']=='EMPTY'
                and state['device_spki']==spki and state['apk_source_sha']==self.source)
        idle()
        # Before any invite/stage/BEGIN, only this verified, empty new package.
        # A MAIN intent into an already resumed singleTask Activity does not
        # send ON_RESUME. A fresh Activity must consume the staged delivery.
        self.adb('shell','am','force-stop',channel.PACKAGE)
        idle() # Provider restart must retain the very same Keystore identity.
    def core(self,operation):
        response=mobile_operator_client(self.state_dir,operation)
        require(type(response) is dict and set(response)=={'ok','data'} and response['ok'] is True)
        return response['data']
    def save(self,name,value):
        target=self.evidence/name
        fd=os.open(target,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
        with os.fdopen(fd,'wb') as stream:
            stream.write(wire.canonical(value));stream.flush();os.fsync(stream.fileno())
    def provision(self,trusted,previous_device,archived=(),archived_agents=()):
        self.evidence.mkdir(mode=0o700) # Never reuse an ambiguous previous attempt directory.
        require(self.adb('get-state').strip()=='device')
        self.verify_installation()
        settings=self.core({'op':'settings'}) # True owner admission, before any mutation.
        require(settings['profile']=='NATIVE_STATUS_READ_ONLY_V1' and settings['model_calls']==0)
        for key in ('origin','host_spki','tls_spki_pin'):require(settings[key]==trusted[key])
        challenge=secrets.token_hex(32)
        identity=self.call('identity',challenge)
        spki=verify_identity(identity,challenge,self.source,int(time.time()));device=wire.digest(wire.unbase64(spki))
        self.save('USB_IDENTITY.json',identity)
        self.prepare_idle_installation(spki)
        self.save('INVITE_ATTEMPT.json',{'state':'ATTEMPTED_NO_AUTOMATIC_RETRY'})
        packet=self.core({'op':'pairing_invite'})
        invite=packet['invite'];wire.verify(trusted['host_spki'],packet['signature'],invite)
        for key in ('origin','host_spki','tls_spki_pin','owner_scope_digest'):require(invite[key]==trusted[key])
        require(invite['source_sha']==settings['source_sha'] and invite['capsule_digest']==settings['capsule_digest'])
        at=int(time.time());require(invite['issued_at']<=at<invite['expires_at']<=invite['issued_at']+300)
        payload={'schema':'aioa.mobile.usb-transfer.v1','flow_id':secrets.token_hex(16),
            'device_spki':spki,'package':channel.PACKAGE,'certificate_sha256':channel.CERTIFICATE,
            'apk_source_sha':self.source,'issued_at':at,'expires_at':min(at+300,invite['expires_at']),
            'trusted_host':trusted,'invite':packet,'previous_device_id':previous_device,
            'archived':list(archived),'archived_agents':list(archived_agents)}
        encoded=base64.urlsafe_b64encode(wire.canonical(payload)).decode().rstrip('=')
        self.save('STAGE_ATTEMPT.json',{'flow_id':payload['flow_id'],'digest':wire.digest(wire.canonical(payload))})
        self.call('stage',encoded)
        self.adb('shell','am','start','-n',channel.PACKAGE+'/eu.sparkhat.aioa.companion.MainActivity')
        until=time.monotonic()+120
        record=None
        while time.monotonic()<until:
            state=self.call('state');require(state['device_spki']==spki and state['apk_source_sha']==self.source)
            record=state['pairing']
            if record is not None:break
            time.sleep(2)
        require(record is not None and record['host']=={k:invite[k] for k in trusted})
        pending=[]
        while time.monotonic()<until:
            pending=[p for p in self.core({'op':'pairing_list'})['pending'] if p['request_id']==record['request_id']]
            if pending:break
            time.sleep(2) # Local record precedes BEGIN: wait for dispatch, never resend.
        require(len(pending)==1)
        verify_pending(pending[0],record,device,int(time.time()))
        operation={'op':'pairing_approve','request_id':record['request_id'],'request_digest':record['request_digest'],
            'sas':pending[0]['sas']}
        self.save('PENDING_VERIFIED.json',pending[0])
        claim_approval(self.evidence/'APPROVAL_ATTEMPT.json',operation)
        approved=self.core(operation) # Genuine existing Core principal; never an imported approved flag.
        require(approved['state']=='APPROVED')
        self.save('OWNER_APPROVAL_READBACK.json',approved)
        while time.monotonic()<until:
            state=self.call('state');app=state.get('status_readback')
            if app is not None:
                core=self.core({'op':'status'})
                receipt=verify_status_readback(app,core['observations'],trusted['host_spki'],device,
                    settings['source_sha'],settings['capsule_digest'],int(time.time()))
                require(state['pairing']['trusted'] is True and state['pairing']['complete_attempted'] is True)
                self.save('SIGNED_STATUS_VERIFIED.json',receipt)
                self.save('PAIRING_RESULT.json',{'status':'PAIRING_AND_SIGNED_STATUS_PASS','device_id':device,
                    'old_device_id':previous_device,'old_data_preservation_evidence':'SEPARATE_BEFORE_AFTER_CHECK_REQUIRED','private_key_migrated':False,
                    'apk_source_sha':self.source,'core_source_sha':settings['source_sha'],'model_calls':0})
                return
            time.sleep(2) # Provider readback only, no BEGIN/APPROVE/COMPLETE retry.
        raise ValueError('PAIRING_UNKNOWN_READBACK_REQUIRED')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--serial',required=True);parser.add_argument('--source-sha',required=True)
    parser.add_argument('--state-dir',required=True,type=Path);parser.add_argument('--evidence-dir',required=True,type=Path)
    parser.add_argument('--public-transfer',required=True,type=Path)
    parser.add_argument('--verified-apk',required=True,type=Path)
    args=parser.parse_args()
    try:
        # Owner-private prepared public data; no command-line token or approval bit.
        info=args.public_transfer.lstat()
        require(not args.public_transfer.is_symlink() and info.st_uid==os.getuid() and info.st_size<=16384 and not info.st_mode&0o077)
        data=wire.strict_json(args.public_transfer.read_bytes())
        require(set(data)=={'trusted_host','previous_device_id','archived','archived_agents'})
        UsbDelivery(args.serial,args.source_sha,args.state_dir,args.evidence_dir,args.verified_apk).provision(
            data['trusted_host'],data['previous_device_id'],data['archived'],data['archived_agents'])
        print('PAIRING_AND_SIGNED_STATUS_PASS')
        return 0
    except (ValueError,OSError,KeyError,TypeError,subprocess.SubprocessError):
        print('BLOCKED_OR_UNKNOWN_READBACK_REQUIRED; no automatic retry')
        return 2


if __name__=='__main__':raise SystemExit(main())
