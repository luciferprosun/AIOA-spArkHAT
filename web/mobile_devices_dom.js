/* View adapter for the existing AIOA page. No authority from HTTP bootstrap. */
(function () {
  'use strict';
  if (location.pathname !== '/devices') return;
  document.body.classList.add('devices-mode');
  const node = id => document.getElementById('devices-'+id);
  document.getElementById('devices-view').hidden=false;
  history.replaceState(null,'','/devices');
  let client=null,chatView=null,consoleClosed=false;
  function lockConsole() {consoleClosed=true;chatView?.close();client?.close();render();}
  const errors={LOCAL_OPERATOR_REQUIRED:'A local operator session is required. Reopen the panel from Linux.',
    UNKNOWN_READBACK_REQUIRED:'Unknown result. Read Core status before another operation. No automatic retry was made.',
    READBACK_REQUIRED:'Read current Core status first.',REVIEW_REQUIRED:'Review the current exact operation before approving.',
    PREVIEW_INPUT_LIMIT:'Enter a command up to 2,000 UTF-8 bytes or a message up to 8,192 UTF-8 bytes. Total draft input must stay below 12,000 bytes.',
    BUSY:'An operation is in progress. Wait for its result.'};
  const menu=Array.from(document.querySelectorAll?.('[data-cosmic-target]') || []);
  const pages=Array.from(document.querySelectorAll?.('[data-cosmic-page]') || []);
  function updateLayout() {
    const view=document.getElementById('devices-view');
    const large=typeof getComputedStyle==='function' && parseFloat(getComputedStyle(document.documentElement).fontSize)>20;
    view.dataset.cosmicLayout=large?'flow':'fit';
  }
  function showPage(name, focus=false) {
    if (!pages.some(page=>page.dataset.cosmicPage.split(' ').includes(name))) return;
    for (const page of pages) page.hidden=!page.dataset.cosmicPage.split(' ').includes(name);
    for (const button of menu) button.setAttribute('aria-current',button.dataset.cosmicTarget===name?'page':'false');
    document.getElementById('devices-view').dataset.cosmicActive=name;updateLayout();
    if (focus) pages.find(page=>!page.hidden)?.querySelector('h2')?.focus();
  }
  for (const button of menu) button.addEventListener('click',()=>showPage(button.dataset.cosmicTarget,true));
  window.addEventListener('resize',updateLayout);
  if(typeof ResizeObserver==='function')new ResizeObserver(updateLayout).observe(document.documentElement);
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
  let reviewedDigest=null;
  function renderGithub(state) {
    const get=id=>document.getElementById('cosmic-github-'+id);
    const value=state?.githubWrite,approval=get('approve'),reviewed=get('reviewed');
    const ready=state?.phase==='READY' && state.observed && !state.busy;
    const cptInput=document.getElementById('cosmic-cpt-input');
    if(cptInput) {
      cptInput.disabled=!ready;
      if(!state || state.phase==='LOCKED')cptInput.value='';
    }
    const readable=state && state.phase!=='LOCKED' && state.message!=='LOCAL_OPERATOR_REQUIRED' && !state.busy;
    if(reviewed && reviewedDigest!==value?.review_digest){reviewed.checked=false;reviewedDigest=value?.review_digest;}
    const mayApprove=ready && value?.approval_available===true && !state.githubApprovalAttempted;
    if(reviewed)reviewed.disabled=!mayApprove;
    if(approval)approval.disabled=!(mayApprove && reviewed?.checked);
    if(get('status'))get('status').disabled=!(readable && state.githubOperation);
    if(get('reconcile'))get('reconcile').disabled=!(readable && value?.readback_available===true);
    if(get('stop'))get('stop').disabled=!(readable && state.githubOperation && value?.status!=='GITHUB_VERIFIED');
    if(get('history-read'))get('history-read').disabled=!readable;
    const auth=value?.authorization || state?.githubHistory?.authorization;
    if(get('auth-state'))get('auth-state').textContent=auth?
      auth.status+' · '+(auth.reason || 'Repository scope is checked again before WRITE.'):'GitHub App authorization has not been read.';
    if(get('write-state'))get('write-state').textContent=value?
      (value.status==='GITHUB_VERIFIED'?(value.result?.receipt?.live_verified===true?'LIVE VERIFIED':'OFFLINE TEST ONLY'):
        value.status==='GITHUB_UNKNOWN'?'UNKNOWN':
        value.blockers?.length || value.status==='GITHUB_PROPOSAL_FAILED'?'BLOCKED':
        value.approval_available?'NEEDS OWNER APPROVAL':value.owner_approval?'APPROVED WRITE':'PROPOSAL')+' · '+value.status+' · '+value.operation_id+
      (value.blockers?.length?'\n'+value.blockers.join(' · '):'')+(value.error?'\n'+value.error:''):
      'PROPOSE · no owner-approved operation selected.';
    const result=value?.result;
    if(get('receipt'))get('receipt').textContent=result?JSON.stringify(result,null,2):'No GitHub WRITE receipt.';
    if(get('links')) {
      get('links').replaceChildren();
      for(const [label,url] of [['Verified commit',result?.receipt?.github_url],['Verified draft PR',result?.receipt?.pr_url]]) {
        if(value?.status==='GITHUB_VERIFIED' && result?.receipt?.live_verified===true && typeof url==='string' &&
            /^https:\/\/github\.com\/luciferprosun\/AIOA-spArkHAT-Meta-Hackathon-2026\/(commit\/[a-f0-9]{40}|pull\/[1-9][0-9]{0,8})$/.test(url)) {
          const link=text('a',label,get('links'));link.href=url;link.target='_blank';link.rel='noopener noreferrer';
        }
      }
    }
    if(get('history')) {
      get('history').replaceChildren();
      for(const item of state?.githubHistory?.operations || []) {
        const button=text('button',item.mode+' · '+item.status+' · '+item.operation_id,get('history'));
        button.className='button button-ghost';button.disabled=!readable;
        button.addEventListener('click',()=>act(()=>client.githubStatus(item.operation_id)));
      }
    }
  }
  function renderTools(state) {
    const ready=state?.phase==='READY' && state.observed && !state.busy;
    for(const id of ['cosmic-command-preview','cosmic-mail-preview','cosmic-cpt-preview']) {
      const button=document.getElementById(id);if(button)button.disabled=!ready;
    }
    const advisory=document.getElementById('cosmic-advisory-result');
    if(advisory)advisory.textContent=state?.advisoryPreview?JSON.stringify(state.advisoryPreview,null,2):'No preview recorded.';
    const cpt=state?.advisoryPreview?.receipt?.operation==='critic_transform_preview'?state.advisoryPreview:null;
    const cptResult=document.getElementById('cosmic-cpt-result'),cptReceipt=document.getElementById('cosmic-cpt-receipt');
    if(cptResult)cptResult.textContent=cpt?.preview?.transformed_prompt || cpt?.data?.status || 'No critical prompt preview.';
    if(cptReceipt)cptReceipt.textContent=cpt?JSON.stringify({data:cpt.data,receipt:cpt.receipt,signature:cpt.signature},null,2):'No preview recorded.';
    for(const button of document.querySelectorAll?.('[data-tool-read]') || [])button.disabled=!ready;
    const readback=document.getElementById('cosmic-tool-readback');
    if(readback)readback.disabled=!state?.toolRequest || state.busy || state.phase==='LOCKED';
    const parse=document.getElementById('cosmic-proposal-parse');if(parse)parse.disabled=!ready;
    const result=state?.toolResult, receipt=result?.receipt;
    const value=document.getElementById('cosmic-tool-result'),summary=document.getElementById('cosmic-receipt-summary');
    if(value)value.textContent=result?JSON.stringify(result,null,2):'No repository evidence yet.';
    if(summary)summary.textContent=receipt?receipt.operation+' · '+receipt.transport+'\nread_receipt_id: '+receipt.request_id+'\n'+
      'read_source: '+(result.data?.read_source || receipt.transport)+'\nbase_sha: '+(result.data?.commit_sha || 'not a repository context')+'\n'+
      'freshness: '+(receipt.observed_at<=Date.now()/1000 && Date.now()/1000<receipt.observed_at+300?'CURRENT (5-minute window)':'STALE')+'\n'+
      new Date(receipt.observed_at*1000).toISOString()+'\nSHA-256 '+receipt.data_sha256:
      (state?.toolState || 'NOT_RUN')+(state?.toolRequest?' · '+state.toolRequest:'');
    const status=document.getElementById('cosmic-tool-state');
    if(status)status.textContent=state?.message || (receipt?'Recorded READ · '+receipt.transport+' · no WRITE performed.':
      state?.toolError==='TOOL_READ_TIMEOUT'?'GitHub/Git READ exceeded its time budget. The request remains UNKNOWN. No automatic retry.':
      state?.toolState==='NOT_FOUND'?'No READ record found for this request. No automatic retry.':
      state?.toolRequest?'READ result not confirmed. Check last receipt; no automatic retry.':'No tool result read.');
    const proposal=document.getElementById('cosmic-proposal-result');
    if(proposal)proposal.textContent=state?.toolProposal?JSON.stringify(state.toolProposal,null,2):'No proposal selected.';
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
    const preview=document.getElementById('cosmic-cpl-preview'),memory=document.getElementById('cosmic-memory-state');
    if(preview)preview.textContent=data?.components?.cpl?.preview?JSON.stringify(data.components.cpl.preview,null,2):'Read Core status to inspect the contract.';
    if(memory)memory.textContent=data?.components?.memory?JSON.stringify(data.components.memory,null,2):'Read Core status to inspect configured persistence.';
    if(write)write.textContent='REMOTE_WRITE_BLOCKED · '+(data?.components?.github_write?.status || 'No current authority readback.');
    if(!data) {
      label.textContent='No diagnostic readback from this Core yet.';
      text('p','No readback yet. Read the profile from Overview.',history);
      text('p','Private keys and tokens remain on the host.',settings);return;
    }
    label.textContent='Historical local operator readback: '+new Date(state.coreStatusAt*1000).toLocaleString()+
      (state.phase==='READY'?'':' · current authorization or result not confirmed.');
    for(const [name,key] of [['Profile','profile'],['Host','origin'],['Source SHA','source_sha'],
        ['Capsule digest','capsule_digest']]) {
      const value=data[key];
      text('h4',name,settings);text('p',value && typeof value==='object'?JSON.stringify(value):String(value || 'Not read'),settings).className='device-digest';
    }
    text('h4','Operator authentication',settings);
    text('p',String(data.operator_authentication?.method || 'Not read'),settings);
    text('p','TLS and saved host identity are checked by this Native host. Keys and pairing material are not displayed here.',settings);
    text('p','Recorded model attempts: '+data.model_calls+'. Worker: BLOCKED_NATIVE_WORKER_NOT_CERTIFIED.',settings);
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
    if(state?.phase==='LOCKED' || state?.message==='LOCAL_OPERATOR_REQUIRED') {
      chatView?.close();
      for(const id of ['cosmic-proposal-chat','cosmic-command-input','cosmic-cpt-input',
          'cosmic-mail-sender','cosmic-mail-to','cosmic-mail-subject','cosmic-mail-body']) {
        const input=document.getElementById(id);if(input)input.value='';
      }
    }
    node('pending').setAttribute?.('aria-busy',state?.polling?'true':'false');
    node('trusted').setAttribute?.('aria-busy',state?.polling?'true':'false');
    renderOverview(state);
    renderCore(state);
    renderTools(state);
    renderGithub(state);
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
  node('lock').addEventListener('click',lockConsole);
  document.getElementById('cosmic-core-read')?.addEventListener('click',()=>act(()=>client.status()));
  document.getElementById('cosmic-command-preview')?.addEventListener('click',()=>act(()=>client.preview('command_advice',{
    command:document.getElementById('cosmic-command-input').value})));
  document.getElementById('cosmic-cpt-preview')?.addEventListener('click',()=>act(()=>client.preview('critic_transform_preview',{
    prompt:document.getElementById('cosmic-cpt-input').value})));
  document.getElementById('cosmic-mail-preview')?.addEventListener('click',()=>act(()=>client.preview('mail_preview',{
    sender:document.getElementById('cosmic-mail-sender').value,
    to:document.getElementById('cosmic-mail-to').value.split(',').map(x=>x.trim()),
    subject:document.getElementById('cosmic-mail-subject').value,
    body_text:document.getElementById('cosmic-mail-body').value})));
  for(const button of document.querySelectorAll?.('[data-tool-read]') || [])button.addEventListener('click',()=>act(()=>client.readTool(button.dataset.toolRead)));
  document.getElementById('cosmic-tool-readback')?.addEventListener('click',()=>act(()=>client.readToolResult()));
  document.getElementById('cosmic-proposal-parse')?.addEventListener('click',()=>act(()=>client.proposeTool(document.getElementById('cosmic-proposal-chat').value.trim())));
  document.getElementById('cosmic-github-reviewed')?.addEventListener('change',render);
  document.getElementById('cosmic-github-approve')?.addEventListener('click',()=>{
    if(document.getElementById('cosmic-github-reviewed')?.checked)act(()=>client.githubApprove());
  });
  for(const [id,method] of [['status','githubStatus'],['reconcile','githubReconcile'],['stop','githubStop'],['history-read','githubHistory']])
    document.getElementById('cosmic-github-'+id)?.addEventListener('click',()=>act(()=>client[method]()));
  window.addEventListener('pagehide',lockConsole);
  // The transport decides whether a stale read can recover. An uncertain
  // mutation still requires explicit readback and is never replayed here.
  setInterval(()=>{
    const state=client?.snapshot();
    if (document.visibilityState==='visible' && state && state.phase!=='LOCKED' && !state.busy)act(async()=>{
      await client.refresh({background:true});
      // Local Core records only. External recovery GETs require a deliberate click.
      if(state.githubOperation && (!state.githubWrite ||
          ['GITHUB_APPROVAL_PENDING','GITHUB_APPROVED','GITHUB_RUNNING','GITHUB_RECONCILING'].includes(state.githubWrite.status) ||
          state.githubApprovalAttempted && state.githubWrite.status==='GITHUB_PROPOSED'))await client.githubStatus();
    });
  },5000);
  render();
  // The HttpOnly cookie was delivered through the private OS launcher. The
  // anti-CSRF value exists only in this closure, never HTML/URL/storage.
  fetch('/api/native-operator/session',{credentials:'same-origin',redirect:'error',cache:'no-store'})
    .then(async response=>{if(!response.ok)throw Error('LOCAL_OPERATOR_REQUIRED');return response.json();})
    .then(async data=>{
      if(consoleClosed)throw Error('LOCAL_OPERATOR_REQUIRED');
      if(data.ok!==true || !/^[A-Za-z0-9_-]{43}$/.test(data.csrf_token))throw Error('LOCAL_OPERATOR_REQUIRED');
      client=AIOAMobileDevices.createDeviceConsole(data.csrf_token);
      await act(()=>client.refresh());
      if(data.profile==='NATIVE_ADVISORY_CHAT_V1' && client?.snapshot().phase==='READY' &&
          typeof AIOAMobileChat!=='undefined') {
        chatView=AIOAMobileChat.mount(async value=>{
          try{return await client.chatCall(value);}
          finally {if(client?.snapshot().message==='LOCAL_OPERATOR_REQUIRED')render();}
        },()=>{
          const snapshot=client.snapshot(),receipt=snapshot.toolResult?.receipt;
          return snapshot.toolState==='VERIFIED' && ['github.repository','github.code_context','github.demo_context'].includes(receipt?.operation) &&
            receipt.transport==='LIVE_GITHUB_GET' && Number.isSafeInteger(receipt.observed_at) &&
            receipt.observed_at<=Date.now()/1000 && Date.now()/1000<receipt.observed_at+300?receipt.request_id:null;
        });showPage('chat');
      }
      else {
        const label=document.getElementById('native-chat-state');
        if(label)label.textContent='Chat is unavailable in this host profile.';
      }
    }).catch(()=>{client=null;render();});
})();
