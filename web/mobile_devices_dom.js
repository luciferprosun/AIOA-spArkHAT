/* View adapter for the existing AIOA page. No authority from HTTP bootstrap. */
(function () {
  'use strict';
  if (location.pathname !== '/devices') return;
  document.body.classList.add('devices-mode');
  const node = id => document.getElementById('devices-'+id);
  document.getElementById('devices-view').hidden=false;
  const fragment=location.hash;
  history.replaceState(null,'','/devices');
  let client=null;
  const match=/^#operator=([A-Za-z0-9_-]{43})$/.exec(fragment);
  if (match) client=AIOAMobileDevices.createDeviceConsole(match[1]);
  const errors={LOCAL_OPERATOR_REQUIRED:'Lokalna sesja operatora jest wymagana. Otwórz panel ponownie z Linuxa.',
    UNKNOWN_READBACK_REQUIRED:'Wynik nieznany. Odczytaj stan Core przed kolejną operacją. Nie ponowiono automatycznie.',
    READBACK_REQUIRED:'Najpierw odczytaj aktualny stan Core.',REVIEW_REQUIRED:'Stan urządzenia zmienił się. Odczytaj go ponownie.',
    BUSY:'Trwa jedna operacja. Poczekaj na jej wynik.'};
  function text(tag,value,parent) {const el=document.createElement(tag);el.textContent=value;parent.append(el);return el;}
  function render() {
    const state=client?.snapshot();
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
      text('h3',row.device_name,card);text('p',row.revoked?'Dostęp odwołany':'Zaufane urządzenie · status online niezweryfikowany',card);
      text('p',row.device_id,card).className='device-digest';
      if (!row.revoked) {
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
  node('add').addEventListener('click',()=>act(()=>client.invite()));
  node('refresh').addEventListener('click',()=>act(()=>client.refresh()));
  node('lock').addEventListener('click',()=>{client?.close();render();});
  window.addEventListener('pagehide',()=>{client?.close();render();});
  // Read-only polling while visible; never repeat a mutation or UNKNOWN operation.
  setInterval(()=>{
    const state=client?.snapshot();
    if (document.visibilityState==='visible' && state?.phase==='READY' && !state.busy) act(()=>client.refresh());
  },5000);
  render();if(client)act(()=>client.refresh());
})();
