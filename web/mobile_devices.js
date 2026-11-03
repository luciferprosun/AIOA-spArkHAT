/* Existing AIOA operator panel transport. Core remains the authority. */
(function (root) {
  'use strict';
  const copy = value => JSON.parse(JSON.stringify(value));
  // Registry counts are not an Android liveness or signed-status assertion.
  function presentation(state) {
    const ready=state?.phase==='READY' && state.observed===true;
    return {operatorReady:ready,
      trustedDevices:ready?state.devices.filter(x=>x.revoked===false).length:null,
      pendingApprovals:ready?state.pending.filter(x=>x.state==='PENDING').length:null,
      activeSessions:ready?state.devices.reduce((sum,x)=>sum+(x.active_sessions || 0),0):null};
  }
  const canRevokeDevice = row => row.revoked===false || row.active_sessions>0 || row.pending_enrollments>0;
  function createDeviceConsole(credential, fetcher = root.fetch.bind(root), clock = () => Math.floor(Date.now()/1000)) {
    if (!/^[A-Za-z0-9_-]{43}$/.test(credential)) throw Error('LOCAL_OPERATOR_REQUIRED');
    let token = credential, busy = false, generation = 0;
    let state = {phase:'READY', observed:false, pending:[], devices:[], invite:null, message:'',coreStatus:null,coreStatusAt:null};
    async function call(value, mutation, apply) {
      if (!token) throw Error('LOCAL_OPERATOR_REQUIRED');
      if (busy) throw Error('BUSY');
      if (mutation && state.phase !== 'READY') throw Error('READBACK_REQUIRED');
      busy = true;
      const epoch = generation;
      const controller = new AbortController();
      const timer = setTimeout(() => controller.abort(), 8000);
      try {
        const response = await fetcher('/api/native-operator', {
          method:'POST', credentials:'same-origin', redirect:'error', cache:'no-store', signal:controller.signal,
          headers:{'Content-Type':'application/json', 'X-AIOA-Session-Token':token},
          body:JSON.stringify(value)
        });
        if (!response.ok) throw Error(response.status === 403 ? 'LOCAL_OPERATOR_REQUIRED' : 'UNKNOWN_READBACK_REQUIRED');
        const envelope = await response.json();
        if (epoch !== generation || !token) throw Error('LOCAL_OPERATOR_REQUIRED');
        if (!envelope || envelope.ok !== true || !envelope.data || typeof envelope.data !== 'object') throw Error('UNKNOWN_READBACK_REQUIRED');
        apply(copy(envelope.data));
        state.phase = 'READY'; state.message = '';
        return copy(envelope.data);
      } catch (error) {
        if (epoch !== generation || !token) throw Error('LOCAL_OPERATOR_REQUIRED');
        state.phase = 'UNKNOWN';
        state.observed = false;
        state.message = error.message === 'LOCAL_OPERATOR_REQUIRED' ? error.message : 'UNKNOWN_READBACK_REQUIRED';
        throw Error(state.message);
      } finally { clearTimeout(timer); busy = false; }
    }
    return Object.freeze({
      chatCall:value=>{
        if(!value || !['chat_catalog','chat_threads','chat_thread','chat_request','chat_review','chat_propose','chat_stop'].includes(value.op))return Promise.reject(Error('LOCAL_OPERATOR_REQUIRED'));
        return call(value,['chat_propose','chat_stop'].includes(value.op),()=>{});
      },
      snapshot:() => copy({...state, busy}),
      refresh:() => call({op:'pairing_list'}, false, data => {
        if (!Array.isArray(data.pending) || !Array.isArray(data.devices) || data.pending.length>128 || data.devices.length>128) throw Error('INVALID_READBACK');
        state.pending=data.pending; state.devices=data.devices; state.observed=true;
      }),
      status:async () => {
        // An unrelated read must never resolve an uncertain pairing mutation.
        if(state.phase!=='READY' || !state.observed) throw Error('READBACK_REQUIRED');
        return call({op:'status'},false,data=>{
          if(!['NATIVE_STATUS_READ_ONLY_V1','NATIVE_ADVISORY_CHAT_V1'].includes(data.profile) ||
              !Number.isSafeInteger(data.model_calls) || data.model_calls<0 ||
              data.profile==='NATIVE_STATUS_READ_ONLY_V1' && data.model_calls!==0 ||
              !Array.isArray(data.sessions) || data.sessions.length>8 ||
              !Array.isArray(data.observations) || data.observations.length>8 ||
              typeof data.history_truncated!=='boolean') throw Error('INVALID_READBACK');
          for(const row of data.observations) {
            const p=row?.proof;
            if(!p || !Number.isSafeInteger(p.issued_at) || !Number.isSafeInteger(p.expires_at) ||
                p.issued_at<0 || p.expires_at<p.issued_at || p.expires_at>253402300799 ||
                typeof row.signature!=='string') throw Error('INVALID_READBACK');
          }
          state.coreStatus=data;state.coreStatusAt=clock();
        });
      },
      invite:() => call({op:'pairing_invite'}, true, data => { state.invite=data; }),
      approve:async (requestId, reviewedDigest) => {
        if (busy) throw Error('BUSY');
        const selected=state.pending.find(x=>x.request_id===requestId);
        if (!selected || selected.request_digest!==reviewedDigest || selected.state!=='PENDING' || selected.expires_at<=clock()) throw Error('REVIEW_REQUIRED');
        return call({op:'pairing_approve', request_id:requestId, request_digest:reviewedDigest, sas:selected.sas}, true, data => {
          if (data.request_id!==requestId || data.request_digest!==reviewedDigest || data.state!=='APPROVED') throw Error('INVALID_APPROVAL_READBACK');
          state.pending=state.pending.map(x=>x.request_id===requestId ? data : x);
        });
      },
      revoke:async deviceId => {
        const selected=state.devices.find(x=>x.device_id===deviceId && canRevokeDevice(x));
        if (!selected) throw Error('REVIEW_REQUIRED');
        return call({op:'pairing_revoke', device_id:deviceId}, true, data => {
          if (data.device_id!==deviceId || data.revoked!==true) throw Error('INVALID_REVOCATION_READBACK');
          state.devices=state.devices.map(x=>x.device_id===deviceId ? {...x,revoked:true,active_sessions:0,pending_enrollments:0} : x);
        });
      },
      close:() => { generation++; token=''; state={phase:'LOCKED',observed:false,pending:[],devices:[],invite:null,coreStatus:null,coreStatusAt:null,message:'LOCAL_OPERATOR_REQUIRED'}; }
    });
  }
  const api={createDeviceConsole,canRevokeDevice,presentation};
  if (typeof module !== 'undefined' && module.exports) module.exports=api;
  else root.AIOAMobileDevices=Object.freeze(api);
})(typeof globalThis !== 'undefined' ? globalThis : this);
