/* View adapter for the existing AIOA page. No authority from HTTP bootstrap. */
(function () {
  'use strict';
  if (location.pathname !== '/devices') return;
  document.body.classList.add('devices-mode');
  const node = id => document.getElementById('devices-'+id);
  document.getElementById('devices-view').hidden=false;
  history.replaceState(null,'','/devices');
  let client=null;
  const errors={LOCAL_OPERATOR_REQUIRED:'Lokalna sesja operatora jest wymagana. Otwórz panel ponownie z Linuxa.',
    UNKNOWN_READBACK_REQUIRED:'Wynik nieznany. Odczytaj stan Core przed kolejną operacją. Nie ponowiono automatycznie.',
    READBACK_REQUIRED:'Najpierw odczytaj aktualny stan Core.',REVIEW_REQUIRED:'Stan urządzenia zmienił się. Odczytaj go ponownie.',
    BUSY:'Trwa jedna operacja. Poczekaj na jej wynik.'};
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
    const values={'cosmic-operator-state':view.operatorReady?'Odczyt rejestru Core potwierdzony':'Brak bieżącego odczytu operatora',
      'cosmic-trusted-count':view.trustedDevices,'cosmic-session-count':view.activeSessions,'cosmic-approval-count':view.pendingApprovals};
    for (const [id,value] of Object.entries(values)) {
      const element=document.getElementById(id);
      if(element) element.textContent=value===null?'—':String(value);
    }
  }
  function text(tag,value,parent) {const el=document.createElement(tag);el.textContent=value;parent.append(el);return el;}
  function renderCore(state) {
    const button=document.getElementById('cosmic-core-read');
    if(button)button.disabled=!state || state.phase!=='READY' || !state.observed || state.busy;
    const label=document.getElementById('cosmic-core-read-state');
    const settings=document.getElementById('cosmic-core-settings');
    const history=document.getElementById('cosmic-core-observations');
    if(!label || !settings || !history)return;
    settings.replaceChildren();history.replaceChildren();
    const data=state?.coreStatus;
    if(!data) {
      label.textContent='Nie odczytano diagnostyki tego Core.';
      text('p','Brak odczytu. Użyj odczytu profilu na stronie Główna.',history);
      text('p','Klucze prywatne i tokeny pozostają na hoście.',settings);return;
    }
    label.textContent='Historyczny odczyt lokalnego kanału operatora: '+new Date(state.coreStatusAt*1000).toLocaleString()+
      (state.phase==='READY'?'':' · bieżąca autoryzacja lub wynik niepotwierdzony.');
    for(const [name,key] of [['Profil','profile'],['Host','origin'],['Source SHA','source_sha'],
        ['Capsule digest','capsule_digest'],['TLS SPKI pin','tls_spki_pin'],['Publiczny SPKI hosta','host_spki'],
        ['Uwierzytelnienie operatora','operator_authentication']]) {
      const value=data[key];
      text('h4',name,settings);text('p',value && typeof value==='object'?JSON.stringify(value):String(value || 'Nie odczytano'),settings).className='device-digest';
    }
    text('p','Zapisane próby modelu: '+data.model_calls+'. Worker: BLOCKED_NATIVE_WORKER_NOT_BOUND.',settings);
    if(!data.observations.length)text('p','Core nie zapisał odpowiedzi w odczytanym zakresie.',history);
    for(const row of data.observations) {
      const proof=row.proof || {};
      const card=text('article','',history);card.className='device-card';
      text('h4',String(proof.method || '—')+' '+String(proof.path || '—'),card);
      text('p','Czas hosta: '+new Date(proof.issued_at*1000).toISOString()+' · '+
        (proof.expires_at<=Math.floor(Date.now()/1000)?'podpisana obserwacja wygasła':'ważność obserwacji jeszcze nie upłynęła'),card);
      text('p','Source: '+String(proof.source_sha || '—'),card).className='device-digest';
      text('p','SHA-256 danych: '+String(proof.data_sha256 || '—'),card).className='device-digest';
    }
    if(data.history_truncated)text('p','Zakres skrócony do ośmiu wpisów; to nie jest pełny ledger.',history);
  }
  function render() {
    const state=client?.snapshot();
    renderOverview(state);
    renderCore(state);
    for (const id of ['add','refresh','lock']) node(id).disabled=!state || state.phase==='LOCKED' || state.busy;
    if (!state) return;
    node('add').disabled=state.phase!=='READY'||state.busy;
    node('message').textContent=errors[state.message] || (state.phase==='READY' ? 'Lokalny operator · odczyt stanu tego Core' : state.phase);
    node('pending').replaceChildren();node('trusted').replaceChildren();
    if (!state.pending.length) text('p','Brak zgłoszeń. Zeskanuj zaproszenie na telefonie.',node('pending'));
    for (const row of state.pending) {
      const card=text('article','',node('pending'));card.className='device-card';
      text('h3',row.device_name,card);text('p',row.state,card);
      text('p','Kod na obu ekranach: '+row.sas,card).className='device-sas';
      text('p','Odcisk urządzenia: '+row.device_id,card).className='device-digest';
      if (row.state==='PENDING' && row.expires_at>Math.floor(Date.now()/1000)) {
        const button=text('button','Kod '+row.sas+' zgadza się — zatwierdź ten telefon',card);
        button.className='button button-primary';button.disabled=state.busy || state.phase!=='READY';
        button.dataset.deviceFocus=JSON.stringify(['approve',row.request_id,row.request_digest]);
        button.addEventListener('click',()=>act(()=>client.approve(row.request_id,row.request_digest)));
      }
    }
    if (!state.devices.length) text('p','Brak zapamiętanych urządzeń.',node('trusted'));
    for (const row of state.devices) {
      const card=text('article','',node('trusted'));card.className='device-card';
      text('h3',row.device_name,card);text('p',row.revoked?'Ponowne łączenie odwołane':'Zaufane urządzenie · status online niezweryfikowany',card);
      text('p',row.device_id,card).className='device-digest';
      text('p','Aktywne sesje: '+(row.active_sessions || 0)+' · Oczekujące kody: '+(row.pending_enrollments || 0),card);
      if (AIOAMobileDevices.canRevokeDevice(row)) {
        const button=text('button','Odwołaj dostęp',card);button.className='button button-ghost';button.disabled=state.phase!=='READY'||state.busy;
        button.dataset.deviceFocus=JSON.stringify(['revoke',row.device_id]);
        button.addEventListener('click',()=>{
          if (window.confirm('Odwołać dostęp urządzeniu '+row.device_name+'?\n'+row.device_id)) act(()=>client.revoke(row.device_id));
        });
      }
    }
    const packet=state.invite,expires=packet?.invite?.expires_at || 0;
    node('invite').hidden=!packet || expires<=Math.floor(Date.now()/1000) || state.phase==='LOCKED';
    if (!node('invite').hidden) {
      const value=JSON.stringify(packet);
      node('packet').value=value;
      node('expiry').textContent='Ważne do '+new Date(expires*1000).toLocaleTimeString()+'. Kod potwierdzenia pojawi się po skanowaniu.';
      if (node('qr').dataset.invite!==packet.invite.invite_id) {
        try {
          const qr=qrcodegen.QrCode.encodeText(value,qrcodegen.QrCode.Ecc.MEDIUM),scale=4,border=4;
          const canvas=node('qr');canvas.width=canvas.height=(qr.size+border*2)*scale;
          const ctx=canvas.getContext('2d');ctx.fillStyle='#fff';ctx.fillRect(0,0,canvas.width,canvas.height);ctx.fillStyle='#000';
          for(let y=0;y<qr.size;y++)for(let x=0;x<qr.size;x++)if(qr.getModule(x,y))ctx.fillRect((x+border)*scale,(y+border)*scale,scale,scale);
          canvas.dataset.invite=packet.invite.invite_id;
        } catch (_) {node('message').textContent='QR niedostępny. Użyj publicznego pakietu parowania.';}
      }
    } else {node('packet').value='';const canvas=node('qr');canvas.getContext('2d').clearRect(0,0,canvas.width,canvas.height);delete canvas.dataset.invite;}
  }
  async function act(fn) {
    const focus=document.activeElement?.dataset.deviceFocus;
    let focusMoved=false;
    const moved=()=>{focusMoved=true;};
    if(focus)document.addEventListener('focusin',moved);
    let failure='';
    try {const pending=fn();render();await pending;} catch(error) {failure=errors[error.message] || 'Operacja odrzucona. Odczytaj stan Core.';}
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
          typeof AIOAMobileChat!=='undefined') AIOAMobileChat.mount(value=>client.chatCall(value));
      else {
        const label=document.getElementById('native-chat-state');
        if(label)label.textContent='Czat niedostępny w tym profilu hosta.';
      }
    }).catch(()=>{client=null;render();});
})();
