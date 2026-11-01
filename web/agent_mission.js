/* One existing Mission Control; model choice and native effect evidence differ. */
(function(root) {
  'use strict';
  const active = new Set(['AGENT_PENDING','AGENT_APPROVED','AGENT_RUNNING']);
  function validate(value) {
    if (!value || value.schema !== 'aioa.agent.mission.v2' || !/^agent-[a-f0-9]{32}$/.test(value.task_id)
      || value.mode !== 'OFFLINE_FIXTURE' || value.provider_id !== 'meta_model_api'
      || value.model_id !== 'muse-spark-1.3' || !/^[a-f0-9]{64}$/.test(value.preview_digest)) {
      throw new Error('A typed, source-bound local fixture view is required.');
    }
    return value;
  }
  function presentation(value) {
    return {effect:value.receipt?.local_readback_verified === true ? 'Local effect readback verified'
      : value.state === 'AGENT_UNKNOWN' ? 'UNKNOWN — independent readback required' : 'Effect not verified',
      model:value.model_invoked === true ? `${value.provider_id} / ${value.model_id} · ${value.mode}`
        : 'Model not invoked by this registered local recipe. LIVE API remains blocked.',
      approval:value.state === 'AGENT_PENDING' ? 'NEEDS_HOST_APPROVAL — exact local operation only' : value.state};
  }
  function createAgentClient({fetchJSON,render,error,delay=ms=>new Promise(resolve=>setTimeout(resolve,ms)),
    makeId=()=>root.crypto.randomUUID().replaceAll('-',''),saveHint=()=>{},clearHint=()=>{}}) {
    let current=null,generation=0,pending=null;const attempted=new Set();
    function publish(value) { current=validate(value);render(current);return current; }
    async function readback(version=generation) {
      if (!current) return null;
      for (let count=0;count<64 && version===generation;count++) {
        try {
          const value=await fetchJSON('/api/agent/tasks/'+encodeURIComponent(current.task_id));
          if(version!==generation)return current;
          publish(value);
          if(!['AGENT_RUNNING','AGENT_APPROVED'].includes(value.state))return value;
        } catch(_) { error('Readback unavailable. Outcome UNKNOWN; the operation will not be resent.'); }
        await delay(500);
      }
      return current;
    }
    async function proposal(path,payload) {
      if (pending || current && active.has(current.state)) throw new Error('Resolve or STOP the current proposal first.');
      const id=makeId();if(!/^[a-f0-9]{32}$/.test(id))throw new Error('Invalid request identity.');
      pending=id;saveHint(id);++generation;
      try {
        const value=await fetchJSON(path,{method:'POST',headers:{'X-AIOA-Intent':'agent-propose-v2'},
          body:JSON.stringify({...payload,request_id:id})});
        publish(value);pending=null;clearHint();return value;
      } catch(e) { error('Proposal acknowledgement unavailable. Use GET readback; do not repeat POST.');throw e; }
    }
    const client={
      adopt(value) { ++generation;return publish(value); },
      canApprove() { return current && current.state==='AGENT_PENDING' && !attempted.has(current.task_id)
        && ['SANDBOX_EXEC','GIT_COMMIT'].includes(current.operation?.operation_class); },
      async propose(provider='meta_model_api') {
        if(provider!=='meta_model_api')throw new Error('That provider is not enabled in this profile.');
        return proposal('/api/agent/propose',{schema:'aioa.agent-proposal.v2',recipe_id:'sensorbridge-v1',provider_id:provider});
      },
      async gitPreview() {
        if(!current || current.state!=='AGENT_COMPLETED' || !current.receipt?.local_readback_verified
          || current.operation?.operation_class!=='SANDBOX_EXEC')throw new Error('Verified source workspace required.');
        const source=current.task_id;
        return proposal('/api/agent/git-preview',{source_task_id:source});
      },
      async installPreview(plan) { return proposal('/api/agent/install-preview',{plan}); },
      async approve(digest) {
        if(!client.canApprove() || digest!==current.preview_digest)throw new Error('Confirm the current exact operation digest.');
        const task=current.task_id;attempted.add(task);const version=generation;
        try {
          const result=await fetchJSON('/api/agent/run',{method:'POST',headers:{'X-AIOA-Intent':'agent-approve-offline-exact-v2'},
            body:JSON.stringify({task_id:task,preview_digest:digest})});
          if(version===generation)publish(result);
        } catch(_) { error('Approval acknowledgement unavailable. Reading state; no second POST.'); }
        return readback(version);
      },
      async stop() {
        if(!current || !active.has(current.state))throw new Error('No active task. UNKNOWN requires readback.');
        ++generation;
        return publish(await fetchJSON('/api/agent/stop',{method:'POST',headers:{'X-AIOA-Intent':'agent-stop-v2'},
          body:JSON.stringify({task_id:current.task_id})}));
      },
      refresh:()=>readback(),
      async reconcile() {
        if(!current || current.state!=='AGENT_UNKNOWN')throw new Error('Independent readback is for UNKNOWN operations.');
        ++generation;
        return publish(await fetchJSON('/api/agent/reconcile',{method:'POST',headers:{'X-AIOA-Intent':'agent-readback-v2'},
          body:JSON.stringify({task_id:current.task_id})}));
      },
      async proposalReadback(id=pending) {
        if(!/^[a-f0-9]{32}$/.test(id || ''))throw new Error('Pending request ID required.');
        const value=await fetchJSON('/api/agent/proposals/'+id);
        if(value.task_id) { pending=null;clearHint();return publish(value); }
        error('UNKNOWN proposal. Host reconciliation is required; no automatic retry.');return value;
      },
    };
    return client;
  }
  const api={createAgentClient,presentation};
  if(typeof module!=='undefined' && module.exports)module.exports=api;else root.AIOAAgentMissions=api;
})(typeof globalThis!=='undefined'?globalThis:this);
