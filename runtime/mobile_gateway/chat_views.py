"""Chat routes after the existing signed transport authentication/nonce gate."""
from runtime.core_admission import Capability
from runtime.meta_hackathon.mission_service import MissionError
from . import wire

# Only errors raised before a send intent is written may clear a client hint.
# Conflicts, lost ACKs and all transaction failures deliberately remain UNKNOWN.
PRE_ADMISSION_DENIALS=frozenset(('CHAT_THREAD_BUSY','CHAT_PROMPT_LIMIT','CHAT_MODEL_INVALID',
    'CHAT_PAYLOAD_INVALID','CHAT_BUDGET_INVALID','CHAT_BUDGET_INSUFFICIENT','CHAT_AUTHORITY_REVOKED',
    'CHAT_HISTORY_LIMIT','CHAT_NOT_CONFIGURED','CHAT_DEVICE_INVALID','CHAT_ID_INVALID'))

def dispatch(gateway,action,identity,session,value):
    host=gateway.native_host
    if host is None or not host.chat_enabled:raise wire.MobileError(501)
    reader=gateway.core.local_operator(Capability.READ);device=session.data['device_id']
    try:
        if action=='chat_send':
            return gateway.missions.chat_propose(value,reader,device_id=device,session_id=session.data['session_id'],nonce=session.nonce,actor='ANDROID')
        if action=='chat_request':return gateway.missions.chat_request(identity,reader,device_id=device)
        if action=='chat_thread':return gateway.missions.chat_thread(identity,reader,device_id=device)
        if action=='chat_threads':return gateway.missions.chat_threads(reader,device_id=device)
        if action=='chat_stop':
            if set(value)!={'request_id'}:raise wire.MobileError(400)
            return gateway.missions.chat_stop(value['request_id'],reader,device_id=device)
    except MissionError as error:
        # Contract denials remain concrete but signed, without echoing text.
        result={'schema':'aioa.mobile.chat-error.v1','error':error.code,'automatic_retry':False}
        request_id=value.get('request_id') if type(value) is dict else None
        if action=='chat_send' and error.code in PRE_ADMISSION_DENIALS and type(request_id) is str and wire.HEX32.fullmatch(request_id):
            result.update(admitted=False,request_id=request_id)
        return result
    raise wire.MobileError(400)
