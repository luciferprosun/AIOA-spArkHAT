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
  const codingStates=new Set(['QUEUED','RUNNING','VALIDATING','PLANNED','PATCH_READY','TESTING','REPAIRING','REVIEW_REQUIRED','APPROVED','APPLYING','VERIFIED','DENIED','CANCELLED','FAILED','UNKNOWN']);
  function createCodingClient({fetchJSON,render,error,onClose=()=>{}}) {
    let current=null,closed=false,generation=0;
    const attempted=new Set();
    function open(){if(closed)throw Error('Coding session is closed.');}
    function active(ticket){return !closed && ticket===generation;}
    function close(){if(closed)return;closed=true;generation++;current=null;attempted.clear();onClose();}
    function denied(error){return error?.status===401 || error?.status===403;}
    function adopt(value) {
      open();
      if(!value || !/^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$/.test(value.task_id)
        || !codingStates.has(value.state) || value.authority!=='NONE')throw Error('Invalid Core coding receipt.');
      if(current && current.task_id===value.task_id && current.capsule_digest===value.capsule_digest
        && current.effect_preview && !value.effect_preview)value={...value,effect_preview:current.effect_preview};
      generation++;current=value;render(value);return value;
    }
    async function readTask(id,path) {
      open();const ticket=++generation;
      let value;
      try {value=await fetchJSON(path);}
      catch(error){if(!active(ticket))return null;if(denied(error)){close();return null;}throw error;}
      if(!active(ticket))return null;
      if(value.task_id!==id)throw Error('Cross-task reply denied.');
      return adopt(value);
    }
    async function refresh(){
      open();if(!current)throw Error('Select an admitted task.');
      return readTask(current.task_id,'/api/agent/coding/tasks/'+encodeURIComponent(current.task_id));
    }
    async function send(action,payload){
      open();
      const id=payload.task_id||payload.task?.task_id;
      const key=id+':'+action+':'+(payload.capsule_digest||'');
      if(attempted.has(key))throw Error('Read back the existing request; no second POST.');
      attempted.add(key);const ticket=++generation;
      try {
        const value=await fetchJSON('/api/agent/coding/'+action,{method:'POST',
          headers:{'X-AIOA-Intent':'coding-'+action+'-v1'},body:JSON.stringify(payload)});
        if(!active(ticket))return null;
        if(value.task_id!==id)throw Error('Cross-task reply denied.');
        return adopt(value);
      } catch(failure) {
        if(!active(ticket))return null;
        if(denied(failure)){close();return null;}
        error('Acknowledgement UNKNOWN. Reading state; no automatic resend.');
        return readTask(id,'/api/agent/coding/tasks/'+encodeURIComponent(id));
      }
    }
    function exact(state,digest){
      open();
      if(current?.state!==state || !/^[a-f0-9]{64}$/.test(digest||'')
        || digest!==current.effect_preview?.operation_digest
        || current.capsule_digest!==current.effect_preview?.capsule_digest)throw Error('Review and confirm the exact current operation.');
      return {task_id:current.task_id,capsule_digest:current.capsule_digest,operation_digest:digest};
    }
    return {adopt,refresh,
      close,
      async select(id){
        open();if(!/^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$/.test(id))throw Error('Invalid task ID.');
        current=null;return readTask(id,'/api/agent/coding/tasks/'+encodeURIComponent(id));
      },
      async create(task){
        open();if(!task?.task_id || !/^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$/.test(task.task_id))throw Error('Task identity required.');
        current=null;return send('create_task',{task});
      },
      async start(){open();if(current?.state!=='QUEUED')throw Error('Queued task required.');return send('start',{task_id:current.task_id});},
      async stop(){open();if(!['QUEUED','RUNNING','VALIDATING','PLANNED','PATCH_READY','TESTING','REPAIRING','REVIEW_REQUIRED','APPROVED','APPLYING'].includes(current?.state))throw Error('No active task.');
        return send('stop',{task_id:current.task_id});},
      async review(){
        open();if(!current)throw Error('Select a task.');
        return readTask(current.task_id,'/api/agent/coding/review/'+encodeURIComponent(current.task_id));
      },
      approve:async digest=>send('approve',exact('REVIEW_REQUIRED',digest)),
      apply:async digest=>send('apply',exact('APPROVED',digest)),
      async deny(){open();if(current?.state!=='REVIEW_REQUIRED')throw Error('Review required.');return send('deny',{task_id:current.task_id});},
      async reconcile(){open();if(current?.state!=='UNKNOWN')throw Error('UNKNOWN required.');return send('reconcile',{task_id:current.task_id});},
    };
  }
  function mountCodingPanel(fetchJSON) {
    const node=id=>root.document.querySelector('#coding-'+id);if(!node('panel'))return;
    let selected=null,closed=false;
    const actions=['create','select','start','stop','review','approve','apply','deny','reconcile','refresh'];
    const client=createCodingClient({fetchJSON,onClose:close,error:message=>{if(!closed)node('message').textContent=message;},render:value=>{
      if(closed)return;
      selected=value;node('evidence').textContent=JSON.stringify(value,null,2);node('confirm').checked=false;
      node('approve').disabled=true;node('apply').disabled=true;
      node('start').disabled=value.state!=='QUEUED';
      node('stop').disabled=!['QUEUED','RUNNING','VALIDATING','PLANNED','PATCH_READY','TESTING','REPAIRING','REVIEW_REQUIRED','APPROVED','APPLYING'].includes(value.state);
      node('deny').disabled=value.state!=='REVIEW_REQUIRED';node('reconcile').disabled=value.state!=='UNKNOWN';
      node('message').textContent=value.state==='VERIFIED'?'Local Git readback verified.':value.state;
    }});
    async function action(call){if(closed)return;try{await call();}catch(e){if(!closed)node('message').textContent=e.message;}}
    node('select').onclick=()=>action(()=>client.select(node('task-id').value));
    node('create').onclick=()=>action(()=>client.create(JSON.parse(node('task').value)));
    for(const id of ['start','stop','review','deny','reconcile','refresh'])node(id).onclick=()=>action(()=>client[id]());
    node('confirm').onchange=()=>{
      if(closed)return;
      node('approve').disabled=!(node('confirm').checked && selected?.state==='REVIEW_REQUIRED' && selected?.effect_preview);
      node('apply').disabled=!(node('confirm').checked && selected?.state==='APPROVED' && selected?.effect_preview);
    };
    for(const id of ['approve','apply'])node(id).onclick=()=>{
      if(closed || !node('confirm').checked)return;node(id).disabled=true;
      action(()=>client[id](selected.effect_preview.operation_digest));
    };
    function close(){
      if(closed)return;
      closed=true;selected=null;client.close();
      node('evidence').textContent='';node('message').textContent='';
      node('task-id').value='';node('task').value='';node('confirm').checked=false;
      for(const id of actions)node(id).disabled=true;
      if(typeof root.removeEventListener==='function')root.removeEventListener('pagehide',close);
    }
    if(typeof root.addEventListener==='function')root.addEventListener('pagehide',close);
    return {close};
  }

  const api={createAgentClient,presentation,createCodingClient,mountCodingPanel};
  if(typeof module!=='undefined' && module.exports)module.exports=api;else root.AIOAAgentMissions=api;
})(typeof globalThis!=='undefined'?globalThis:this);
