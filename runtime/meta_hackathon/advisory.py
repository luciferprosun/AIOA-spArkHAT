"""Pure historical capabilities on Native's existing admitted Core port.

Previews never execute commands, connect accounts, send mail or grant approval.
Only fingerprints/results enter the existing Core audit; no second store.
"""
from datetime import datetime, timedelta, timezone
import time

from runtime.core_admission import Capability
from runtime.memory_patch.persistence.ports import RecordKind
from runtime.mobile_gateway import wire
from runtime.mobile_gateway.service import plain

OPS=frozenset(('command_advice','mail_preview'))


def dispatch(host,owner,value):
    # The existing private Native port issues an exact OWNER_APPROVAL principal,
    # not a transferable READ principal. Preview adds no capability to it.
    host.core.require(owner,Capability.OWNER_APPROVAL,scope=host.missions.scope)
    host._require_qualified_operator()
    if (set(value)!={'op','request_id','payload'} or value['op'] not in OPS
            or type(value['request_id']) is not str or not wire.HEX32.fullmatch(value['request_id'])
            or type(value['payload']) is not dict):
        raise wire.MobileError(400)
    payload=value['payload'];op=value['op'];identity=value['request_id']
    if len(wire.canonical(payload))>12000:raise wire.MobileError(400)
    binding=wire.digest(wire.canonical({'op':op,'payload':payload,
        'source_sha':host.source[0],'capsule_digest':host.source[1],
        'core_instance_id':host.instance_id,'owner_scope_digest':host.mobile.owner_scope_digest}))
    key='native-advisory-'+identity
    def reuse(row):
        if row.payload.get('request_digest')!=binding:raise wire.MobileError(409)
        return plain(row.payload['result'])
    prior=host.mobile._get(key)
    if prior is not None:return reuse(prior)
    now=int(time.time())
    if op=='command_advice':
        from runtime.tools.command_grammar import validate_command_shape
        if (set(payload)!={'command'} or type(payload['command']) is not str
                or len(payload['command'].encode())>2000):raise wire.MobileError(400)
        data={'classification':validate_command_shape(payload['command']),
            'status':'ADVISORY_ONLY','input_sha256':wire.digest(payload['command'].encode())}
    else:
        from runtime.communication.contracts import MailContractError,MailProposalV1
        from runtime.communication.canonical_mime import prepare_mime,verify_prepared_mime
        if (set(payload)!={'sender','to','subject','body_text'} or type(payload['to']) is not list
                or type(payload['body_text']) is not str or len(payload['body_text'].encode())>8192):
            raise wire.MobileError(400)
        stamp=lambda when:when.strftime('%Y-%m-%dT%H:%M:%SZ')
        created=datetime.fromtimestamp(now,timezone.utc)
        try:
            proposal=MailProposalV1(task_id='preview-'+identity,proposal_id=identity,
                owner_scope_ref=host.mobile.owner_scope_digest,nonce=binding,
                created_at=stamp(created),expires_at=stamp(created+timedelta(minutes=5)),
                sender=payload['sender'],to=tuple(payload['to']),subject=payload['subject'],body_text=payload['body_text'])
            prepared=prepare_mime(proposal)
            verify_prepared_mime(proposal,prepared)
            data={'status':'DRAFT_PREVIEW_ONLY','proposal_sha256':proposal.fingerprint,
                'mime_sha256':prepared.mime_sha256,'mime_bytes':len(prepared.raw_mime),
                'expires_at':proposal.expires_at,'send_status':'BLOCKED_GMAIL_CORE_TRANSPORT_NOT_BOUND'}
        except MailContractError as error:
            # A known pure input refusal is not an uncertain external effect.
            # Audit failure/ACK loss below still propagates as UNKNOWN normally.
            data={'status':'INPUT_REJECTED','error':error.reason,'send_status':'BLOCKED_GMAIL_CORE_TRANSPORT_NOT_BOUND'}
    receipt={'schema':'aioa.native-advisory-receipt.v1','request_id':identity,'operation':op,
        'request_digest':binding,'data_sha256':wire.digest(wire.canonical(data)),
        'source_sha':host.source[0],'capsule_digest':host.source[1],
        'core_instance_id':host.instance_id,'observed_at':now,'effect':'ADVISORY_PREVIEW',
        'execution_authorized':False,'provider_calls':0,'external_calls':0,'automatic_retry':False}
    result={'data':data,'receipt':receipt,'signature':host.identity.sign(receipt)}
    def save(tx):
        host._require_qualified_operator()
        old=tx.get(RecordKind.OPERATION,key)
        if old is not None:return reuse(old)
        host.mobile._record(tx,key,{'state':'ADVISORY_PREVIEW_RECORDED','request_digest':binding,'result':result},at=now)
        return result
    return host.mobile._run(Capability.COMMIT,save)
