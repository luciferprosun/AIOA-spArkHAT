/* View adapter for the existing AIOA page. No authority from HTTP bootstrap. */
(function () {
  'use strict';
  if (location.pathname !== '/devices') return;
  document.body.classList.add('devices-mode');
  const node = id => document.getElementById('devices-'+id);
  document.getElementById('devices-view').hidden=false;
  history.replaceState(null,'','/devices');
  let client=null;
  const errors={LOCAL_OPERATOR_REQUIRED:'A local operator session is required. Reopen the panel from Linux.',
    UNKNOWN_READBACK_REQUIRED:'Unknown result. Read Core status before another operation. No automatic retry was made.',
    READBACK_REQUIRED:'Read current Core status first.',REVIEW_REQUIRED:'Device state changed. Read it again.',
    BUSY:'An operation is in progress. Wait for its result.'};
  const menu=Array.from(document.querySelectorAll?.('[data-cosmic-target]') || []);
  const pages=Array.from(document.querySelectorAll?.('[data-cosmic-page]') || []);
  function showPage(name, focus=false) {
    if (!pages.some(page=>page.dataset.cosmicPage.split(' ').includes(name))) return;
    for (const page of pages) page.hidden=!page.dataset.cosmicPage.split(' ').includes(name);
    for (const button of menu) button.setAttribute('aria-current',button.dataset.cosmicTarget===name?'page':'false');
    if (focus) pages.find(page=>!page.hidden)?.querySelector('h2')?.focus();
  }
  for (const button of menu) button.addEventListener('click',()=>showPage(button.dataset.cosmicTarget,true));
  function renderOverview(state) {
    const view=AIOAMobileDevices.presentation(state);
    const values={'cosmic-operator-state':view.operatorReady?'Core registry readback confirmed':'No current operator readback',
      'cosmic-trusted-count':view.trustedDevices,'cosmic-session-count':view.activeSessions,'cosmic-approval-count':view.pendingApprovals};
    for (const [id,value] of Object.entries(values)) {
      const element=document.getElementById(id);
      if(element) element.textContent=value===null?'—':String(value);
    }
  }
  function text(tag,value,parent) {const el=document.createElement(tag);el.textContent=value;parent.append(el);return el;}
  function renderTools(state) {
    const ready=state?.phase==='READY' && state.observed && !state.busy;
    for(const button of document.querySelectorAll?.('[data-tool-read]') || [])button.disabled=!ready;
    const readback=document.getElementById('cosmic-tool-readback');
    if(readback)readback.disabled=!state?.toolRequest || state.busy || state.phase==='LOCKED';
    const parse=document.getElementById('cosmic-proposal-parse');if(parse)parse.disabled=!ready;
    const result=state?.toolResult, receipt=result?.receipt;
    const value=document.getElementById('cosmic-tool-result'),summary=document.getElementById('cosmic-receipt-summary');
    if(value)value.textContent=result?JSON.stringify(result,null,2):'No repository evidence yet.';
    if(summary)summary.textContent=receipt?receipt.operation+' · '+receipt.transport+'\n'+receipt.task_id+'\n'+
      new Date(receipt.observed_at*1000).toISOString()+'\nSHA-256 '+receipt.data_sha256:
      (state?.toolState || 'NOT_RUN')+(state?.toolRequest?' · '+state.toolRequest:'');
    const status=document.getElementById('cosmic-tool-state');
    if(status)status.textContent=state?.message || (receipt?'Recorded READ · '+receipt.transport+' · no WRITE performed.':
      state?.toolError==='TOOL_READ_TIMEOUT'?'GitHub/Git READ exceeded its time budget. The request remains UNKNOWN. No automatic retry.':
      state?.toolState==='NOT_FOUND'?'No READ record found for this request. No automatic retry.':
      state?.toolRequest?'READ result not confirmed. Check last receipt; no automatic retry.':'No tool result read.');
    const proposal=document.getElementById('cosmic-proposal-result');
    if(proposal && state?.toolProposal)proposal.textContent=JSON.stringify(state.toolProposal,null,2);
  }
  function renderCore(state) {
    const button=document.getElementById('cosmic-core-read');
    if(button)button.disabled=!state || state.phase!=='READY' || !state.observed || state.busy;
    const label=document.getElementById('cosmic-core-read-state');
    const settings=document.getElementById('cosmic-core-settings');
    const history=document.getElementById('cosmic-core-observations');
    if(!label || !settings || !history)return;
    settings.replaceChildren();history.replaceChildren();
    const data=state?.coreStatus;
    const registry=document.getElementById('cosmic-module-registry');
    const evidence=document.getElementById('cosmic-evidence-state');
    if(registry) {
      registry.replaceChildren();
      if(data?.components)for(const [name,item] of Object.entries(data.components)) {
        const row=text('article','',registry);row.className='cosmic-module';
        text('h3',name.replaceAll('_',' '),row);
        text('p',String(item.status),row);
        if(item.observed_at)text('p','Observed '+new Date(item.observed_at*1000).toISOString(),row);
      }
      else text('p','No current binding readback. Nothing is implicitly LIVE.',registry);
    }
    if(evidence)evidence.textContent=data?'Source '+data.source_sha+' · operator observation '+
      new Date(state.coreStatusAt*1000).toISOString()+(state.phase==='READY'?'':' · historical, authorization not confirmed'):
      'Waiting for an authenticated Core observation.';
    const cpl=document.getElementById('cosmic-cpl-state'),write=document.getElementById('cosmic-github-write-state');
    if(cpl)cpl.textContent=data?.components?.cpl?.status || 'No current binding readback.';
    if(write)write.textContent='REMOTE_WRITE_BLOCKED · '+(data?.components?.github_write?.status || 'No current authority readback.');
    if(!data) {
      label.textContent='No diagnostic readback from this Core yet.';
      text('p','No readback yet. Read the profile from Overview.',history);
      text('p','Private keys and tokens remain on the host.',settings);return;
    }
    label.textContent='Historical local operator readback: '+new Date(state.coreStatusAt*1000).toLocaleString()+
      (state.phase==='READY'?'':' · current authorization or result not confirmed.');
    for(const [name,key] of [['Profile','profile'],['Host','origin'],['Source SHA','source_sha'],
        ['Capsule digest','capsule_digest'],['TLS SPKI pin','tls_spki_pin'],['Host public SPKI','host_spki'],
        ['Operator authentication','operator_authentication']]) {
      const value=data[key];
      text('h4',name,settings);text('p',value && typeof value==='object'?JSON.stringify(value):String(value || 'Not read'),settings).className='device-digest';
    }
    text('p','Recorded model attempts: '+data.model_calls+'. Worker: BLOCKED_NATIVE_WORKER_NOT_BOUND.',settings);
    if(!data.observations.length)text('p','No Core responses in the observed range.',history);
    for(const row of data.observations) {
      const proof=row.proof || {};
      const card=text('article','',history);card.className='device-card';
      text('h4',String(proof.method || '—')+' '+String(proof.path || '—'),card);
      text('p','Host time: '+new Date(proof.issued_at*1000).toISOString()+' · '+
        (proof.expires_at<=Math.floor(Date.now()/1000)?'signed observation expired':'observation has not expired'),card);
      text('p','Source: '+String(proof.source_sha || '—'),card).className='device-digest';
      text('p','Data SHA-256: '+String(proof.data_sha256 || '—'),card).className='device-digest';
    }
    if(data.history_truncated)text('p','Range limited to eight entries; this is not the full ledger.',history);
  }
  function render() {
    const state=client?.snapshot();
    renderOverview(state);
    renderCore(state);
    renderTools(state);
    for (const id of ['add','refresh','lock']) node(id).disabled=!state || state.phase==='LOCKED' || state.busy;
    if (!state) return;
    node('add').disabled=state.phase!=='READY'||state.busy;
    node('message').textContent=errors[state.message] || (state.phase==='READY' ? 'Local operator · this Core status readback' : state.phase);
    node('pending').replaceChildren();node('trusted').replaceChildren();
    if (!state.pending.length) text('p','No pending requests. Scan an invitation on the phone.',node('pending'));
    for (const row of state.pending) {
      const card=text('article','',node('pending'));card.className='device-card';
      text('h3',row.device_name,card);text('p',row.state,card);
      text('p','Code on both screens: '+row.sas,card).className='device-sas';
      text('p','Device fingerprint: '+row.device_id,card).className='device-digest';
      if (row.state==='PENDING' && row.expires_at>Math.floor(Date.now()/1000)) {
        const button=text('button','Code '+row.sas+' matches — approve this phone',card);
        button.className='button button-primary';button.disabled=state.busy || state.phase!=='READY';
        button.dataset.deviceFocus=JSON.stringify(['approve',row.request_id,row.request_digest]);
        button.addEventListener('click',()=>act(()=>client.approve(row.request_id,row.request_digest)));
      }
    }
    if (!state.devices.length) text('p','No remembered devices.',node('trusted'));
    for (const row of state.devices) {
      const card=text('article','',node('trusted'));card.className='device-card';
      text('h3',row.device_name,card);text('p',row.revoked?'Reconnect revoked':'Trusted device · online status not verified',card);
      text('p',row.device_id,card).className='device-digest';
      text('p','Active sessions: '+(row.active_sessions || 0)+' · Pending codes: '+(row.pending_enrollments || 0),card);
      if (AIOAMobileDevices.canRevokeDevice(row)) {
        const button=text('button','Revoke access',card);button.className='button button-ghost';button.disabled=state.phase!=='READY'||state.busy;
        button.dataset.deviceFocus=JSON.stringify(['revoke',row.device_id]);
        button.addEventListener('click',()=>{
          if (window.confirm('Revoke access for device '+row.device_name+'?\n'+row.device_id)) act(()=>client.revoke(row.device_id));
        });
      }
    }
    const packet=state.invite,expires=packet?.invite?.expires_at || 0;
    node('invite').hidden=!packet || expires<=Math.floor(Date.now()/1000) || state.phase==='LOCKED';
    if (!node('invite').hidden) {
      const value=JSON.stringify(packet);
      node('packet').value=value;
      node('expiry').textContent='Valid until '+new Date(expires*1000).toLocaleTimeString()+'. The comparison code appears after scanning.';
      if (node('qr').dataset.invite!==packet.invite.invite_id) {
        try {
          const qr=qrcodegen.QrCode.encodeText(value,qrcodegen.QrCode.Ecc.MEDIUM),scale=4,border=4;
          const canvas=node('qr');canvas.width=canvas.height=(qr.size+border*2)*scale;
          const ctx=canvas.getContext('2d');ctx.fillStyle='#fff';ctx.fillRect(0,0,canvas.width,canvas.height);ctx.fillStyle='#000';
          for(let y=0;y<qr.size;y++)for(let x=0;x<qr.size;x++)if(qr.getModule(x,y))ctx.fillRect((x+border)*scale,(y+border)*scale,scale,scale);
          canvas.dataset.invite=packet.invite.invite_id;
        } catch (_) {node('message').textContent='QR unavailable. Use the public pairing packet.';}
      }
    } else {node('packet').value='';const canvas=node('qr');canvas.getContext('2d').clearRect(0,0,canvas.width,canvas.height);delete canvas.dataset.invite;}
  }
  async function act(fn) {
    const focus=document.activeElement?.dataset.deviceFocus;
    let focusMoved=false;
    const moved=()=>{focusMoved=true;};
    if(focus)document.addEventListener('focusin',moved);
    let failure='';
    try {const pending=fn();render();await pending;} catch(error) {failure=errors[error.message] || 'Operation refused. Read Core status.';}
    render();if(failure)node('message').textContent=failure;
    if(focus) {
      document.removeEventListener('focusin',moved);
      // Disabled controls are rebuilt while awaiting readback. Restore only the
      // exact reviewed record, unless the operator deliberately moved focus.
      if(!focusMoved && document.activeElement===document.body) {
        for(const button of document.querySelectorAll('#devices-pending button, #devices-trusted button')) {
          if(!button.disabled && button.dataset.deviceFocus===focus) {button.focus();break;}
        }
      }
    }
  }
  node('add').addEventListener('click',()=>{showPage('devices');act(()=>client.invite());});
  node('refresh').addEventListener('click',()=>act(()=>client.refresh()));
  node('lock').addEventListener('click',()=>{client?.close();render();});
  document.getElementById('cosmic-core-read')?.addEventListener('click',()=>act(()=>client.status()));
  for(const button of document.querySelectorAll?.('[data-tool-read]') || [])button.addEventListener('click',()=>act(()=>client.readTool(button.dataset.toolRead)));
  document.getElementById('cosmic-tool-readback')?.addEventListener('click',()=>act(()=>client.readToolResult()));
  document.getElementById('cosmic-proposal-parse')?.addEventListener('click',()=>act(()=>client.proposeTool(document.getElementById('cosmic-proposal-chat').value.trim())));
  window.addEventListener('pagehide',()=>{client?.close();render();});
  // Read-only polling while visible; never repeat a mutation or UNKNOWN operation.
  setInterval(()=>{
    const state=client?.snapshot();
    if (document.visibilityState==='visible' && state?.phase==='READY' && !state.busy) act(()=>client.refresh());
  },5000);
  render();
  // The HttpOnly cookie was delivered through the private OS launcher. The
  // anti-CSRF value exists only in this closure, never HTML/URL/storage.
  fetch('/api/native-operator/session',{credentials:'same-origin',redirect:'error',cache:'no-store'})
    .then(async response=>{if(!response.ok)throw Error('LOCAL_OPERATOR_REQUIRED');return response.json();})
    .then(async data=>{
      if(data.ok!==true || !/^[A-Za-z0-9_-]{43}$/.test(data.csrf_token))throw Error('LOCAL_OPERATOR_REQUIRED');
      client=AIOAMobileDevices.createDeviceConsole(data.csrf_token);
      await act(()=>client.refresh());
      if(data.profile==='NATIVE_ADVISORY_CHAT_V1' && client?.snapshot().phase==='READY' &&
          typeof AIOAMobileChat!=='undefined') {
        AIOAMobileChat.mount(value=>client.chatCall(value));showPage('chat');
      }
      else {
        const label=document.getElementById('native-chat-state');
        if(label)label.textContent='Chat is unavailable in this host profile.';
      }
    }).catch(()=>{client=null;render();});
})();
