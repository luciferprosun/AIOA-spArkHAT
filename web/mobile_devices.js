/* Existing AIOA operator panel transport. Core remains the authority. */
(function (root) {
  'use strict';
  const copy = value => JSON.parse(JSON.stringify(value));
  const canRevokeDevice = row => row.revoked===false || row.active_sessions>0 || row.pending_enrollments>0;
  function createDeviceConsole(credential, fetcher = root.fetch.bind(root), clock = () => Math.floor(Date.now()/1000)) {
    if (!/^[A-Za-z0-9_-]{43}$/.test(credential)) throw Error('LOCAL_OPERATOR_REQUIRED');
    let token = credential, busy = false, generation = 0;
    let state = {phase:'READY', pending:[], devices:[], invite:null, message:''};
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
          method:'POST', credentials:'omit', redirect:'error', cache:'no-store', signal:controller.signal,
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
        state.message = error.message === 'LOCAL_OPERATOR_REQUIRED' ? error.message : 'UNKNOWN_READBACK_REQUIRED';
        throw Error(state.message);
      } finally { clearTimeout(timer); busy = false; }
    }
    return Object.freeze({
      snapshot:() => copy({...state, busy}),
      refresh:() => call({op:'pairing_list'}, false, data => {
        if (!Array.isArray(data.pending) || !Array.isArray(data.devices) || data.pending.length>128 || data.devices.length>128) throw Error('INVALID_READBACK');
        state.pending=data.pending; state.devices=data.devices;
      }),
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
      close:() => { generation++; token=''; state={phase:'LOCKED',pending:[],devices:[],invite:null,message:'LOCAL_OPERATOR_REQUIRED'}; }
    });
  }
  const api={createDeviceConsole,canRevokeDevice};
  if (typeof module !== 'undefined' && module.exports) module.exports=api;
  else root.AIOAMobileDevices=Object.freeze(api);
})(typeof globalThis !== 'undefined' ? globalThis : this);
