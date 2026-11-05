/* Advisory Meta chat. Only the private native channel can enable a spending session. */
(function(root){
  'use strict';
  const copy=x=>JSON.parse(JSON.stringify(x));
  function createChat(call,changed=()=>{},id=()=>Array.from(root.crypto.getRandomValues(new Uint8Array(16)),x=>x.toString(16).padStart(2,'0')).join('')) {
    let state={catalog:null,threads:[],thread:null,messages:[],pending:null,busy:false,error:null,draft:false};
    const emit=()=>changed(copy(state));
    let generation=0,refreshing=false;
    async function work(fn,background=false) {
      if(background && (state.busy || refreshing))return;
      if(state.busy)throw Error('CHAT_BUSY');
      const ticket=++generation;
      const check=()=>{if(ticket!==generation)throw Error('CHAT_REFRESH_SUPERSEDED');};
      if(background)refreshing=true;else {state.busy=true;state.error=null;emit();}
      try{const value=await fn(check);check();state.error=null;return value;}catch(e){
        if(background && ticket!==generation)return;
        if(e.message==='LOCAL_OPERATOR_REQUIRED')state.catalog=null;
        state.error=/^[A-Z][A-Z0-9_]{1,100}$/.test(e.message)?e.message:'CHAT_READBACK_UNKNOWN';throw e;
      }
      finally{if(background)refreshing=false;else state.busy=false;if(ticket===generation)emit();}
    }
    function accept(value,expectedRequest=null,expectedThread=state.thread) {
      if((expectedRequest && value.request_id!==expectedRequest) || (expectedThread && value.thread_id!==expectedThread))
        throw Error('CHAT_RESPONSE_MISMATCH');
      if(value.schema!=='aioa.mobile.chat-result.v1' || !/^[a-f0-9]{32}$/.test(value.request_id) ||
          value.model_id!=='muse-spark-1.3' || value.provider_id!=='meta_model_api' || value.save_knowledge!==false)throw Error('CHAT_SCHEMA_INVALID');
      if(['SUCCEEDED','TRUNCATED'].includes(value.state) && (!value.live_verified || !value.receipt ||
          value.receipt.schema!==(value.state==='TRUNCATED'?'aioa.meta.chat-receipt.v2':'aioa.meta.chat-receipt.v1') ||
          value.receipt.request_digest!==value.request_digest || value.state==='TRUNCATED' &&
          (value.receipt.finish_reason!=='length' || value.receipt.response_complete!==false)))throw Error('CHAT_RECEIPT_UNKNOWN');
      state.thread=value.thread_id;state.messages=state.messages.filter(x=>x.request_id!==value.request_id).concat([value]).slice(-20);
      state.pending=['PENDING_OWNER','RUNNING','UNKNOWN'].includes(value.state)?value.request_id:null;
      return copy(value);
    }
    const select=async(thread,check=()=>{})=>{
      if(!/^[a-f0-9]{32}$/.test(thread))throw Error('CHAT_ID_INVALID');
      const value=await call({op:'chat_thread',thread_id:thread});
      check();
      if(value.schema!=='aioa.mobile.chat-thread.v1' || value.thread_id!==thread || !Array.isArray(value.messages) || value.messages.length>20)throw Error('CHAT_SCHEMA_INVALID');
      if(state.pending && !value.messages.some(x=>x.request_id===state.pending) &&
          !state.messages.some(x=>x.request_id===state.pending && x.state==='UNKNOWN'))throw Error('CHAT_READBACK_ONLY');
      if(value.messages.some(x=>x.thread_id!==thread))throw Error('CHAT_RESPONSE_MISMATCH');
      state.messages=[];state.pending=null;state.thread=thread;state.draft=false;for(const message of value.messages)accept(message,null,thread);
      return copy(value);
    };
    return Object.freeze({snapshot:()=>copy(state),
      refresh:({background=false}={})=>work(async check=>{
        const catalog=await call({op:'chat_catalog'});check();state.catalog=catalog;
        const value=await call({op:'chat_threads'});if(!Array.isArray(value.threads) || value.threads.length>24)throw Error('CHAT_SCHEMA_INVALID');
        check();
        state.threads=value.threads;
        const fresh=value.threads.filter(x=>['SUCCEEDED','TRUNCATED'].includes(x.state) && x.current_source===true && x.text_available===true).at(-1);
        const pending=value.threads.filter(x=>x.current_source===true && ['PENDING_OWNER','RUNNING'].includes(x.state)).at(-1);
        // Old peers without summary fields retain v1 behaviour. A current peer
        // never automatically selects a historical UNKNOWN conversation.
        const legacy=value.threads.every(x=>x.state===undefined)?value.threads.at(-1):null;
        const target=state.thread || fresh?.thread_id || pending?.thread_id || legacy?.thread_id;
        if(!state.draft && target)await select(target,check);
      },background),
      newConversation:confirmed=>{
        if(state.busy || confirmed!==true || (state.pending &&
            !state.messages.some(x=>x.request_id===state.pending && x.state==='UNKNOWN')))throw Error('CHAT_READBACK_ONLY');
        generation++;state.thread=id();state.messages=[];state.pending=null;state.draft=true;state.error=null;emit();
      },
      select:thread=>work(check=>select(thread,check)),
      send:(prompt,readRequestId=null)=>work(async()=>{
        if(!state.catalog?.chat || state.catalog.model_id!=='muse-spark-1.3')throw Error('CHAT_NOT_AVAILABLE');
        if(state.pending)throw Error('CHAT_READBACK_ONLY');
        if(typeof prompt!=='string' || !prompt.trim() || new TextEncoder().encode(prompt).length>2000)throw Error('CHAT_PROMPT_LIMIT');
        if(readRequestId!==null && !/^[a-f0-9]{32}$/.test(readRequestId))throw Error('CHAT_READ_REFERENCE_INVALID');
        const request=id();state.thread=state.thread || id();state.pending=request;state.draft=false;emit();
        const direct=state.catalog.mode==='LIVE_OWNER_SESSION';
        try{return accept(await call({op:direct?'chat_send':'chat_propose',...(readRequestId?{read_request_id:readRequestId}:{}),payload:{
          schema:direct?'aioa.mobile.chat-send.v2':'aioa.mobile.chat-send.v1',thread_id:state.thread,
          request_id:request,model_id:'muse-spark-1.3',prompt,...(direct?{}:{max_budget_usd:state.catalog.max_budget_usd || '0.05'})}}),request,state.thread);}
        catch(error){if(error.notDispatched===true){state.pending=null;state.draft=true;}throw error;}
      }),
      read:()=>work(async()=>{
        const request=state.pending || state.messages[state.messages.length-1]?.request_id;
        if(!request)throw Error('CHAT_NO_REQUEST');return accept(await call({op:'chat_request',request_id:request}),request,state.thread);
      }),
      stop:()=>work(async()=>{
        if(!state.pending)throw Error('CHAT_NO_REQUEST');const request=state.pending;
        return accept(await call({op:'chat_stop',request_id:request}),request,state.thread);
      }),
      endSession:()=>work(async()=>{
        await call({op:'chat_session_stop'});
        state.catalog=await call({op:'chat_catalog'});
      })
    });
  }
  function mount(call,readContext=()=>null) {
    const el=id=>document.getElementById('native-chat-'+id);if(!el('send'))return;
    const text=(tag,value,parent)=>{const item=document.createElement(tag);item.textContent=value;parent.append(item);return item;};
    let renderedMessages='',renderedThreads='';
    const client=createChat(call,state=>{
      const responding=!!state.pending && !state.messages.some(x=>x.request_id===state.pending && x.state!=='RUNNING');
      el('state').textContent=state.error || (state.catalog?.blocking_reason==='CHAT_SESSION_REQUIRED'?
        'Chat session ended. Open Mission Control from its launcher to begin a new session.':
        state.catalog?.blocking_reason==='CREDIT_BALANCE_NOT_BOUND'?
        'Local allocation: USD '+state.catalog.allocation_usd+'. A fresh owner-attested Meta credit balance is required before paid calls.':
        responding?'Muse is responding…':
        state.catalog?.mode==='LIVE_OWNER_SESSION'?'Muse Spark 1.3 · conversation active · no local spending cap':
        state.catalog?.chat?'Meta · muse-spark-1.3 · owner approval required for every message':'Chat is unavailable in the current profile');
      el('send').disabled=!state.catalog?.chat || state.busy || !!state.pending;
      el('refresh').disabled=state.busy;el('stop').disabled=state.busy || !state.pending;
      el('read').disabled=state.busy || !(state.pending || state.messages.length);
      if(el('new'))el('new').disabled=state.busy || (!!state.pending && !state.messages.some(x=>x.request_id===state.pending && x.state==='UNKNOWN'));
      if(el('end-session'))el('end-session').disabled=state.busy || state.catalog?.mode!=='LIVE_OWNER_SESSION';
      const threadKey=JSON.stringify([state.threads,state.thread,state.busy]);
      if(threadKey!==renderedThreads){renderedThreads=threadKey;el('threads').replaceChildren();
      for(const thread of state.threads) {
        const button=text('button',(thread.thread_id===state.thread?'Active · ':'')+'Conversation '+thread.thread_id.slice(0,12)+
          (thread.state?' · '+thread.state:'')+(thread.current_source===false?' · historical':''),el('threads'));button.className='button button-ghost';
        button.disabled=state.busy;button.onclick=()=>client.select(thread.thread_id).catch(()=>{});
      }}
      const messageKey=JSON.stringify([state.thread,state.messages]);
      if(messageKey===renderedMessages)return;
      renderedMessages=messageKey;
      const box=el('messages'),atEnd=(box.scrollHeight || 0)-(box.scrollTop || 0)-(box.clientHeight || 0)<80;
      const oldTop=box.scrollTop || 0;
      el('messages').replaceChildren();
      for(const message of state.messages) {
        const card=text('article','',el('messages'));card.className='panel';
        if(message.prompt)text('p','You: '+message.prompt,card);
        if(message.reply)text('p','Muse Spark 1.3: '+message.reply,card);
        if(message.state==='TRUNCATED')text('p','This reply reached its length limit. The partial text and usage were verified. You can ask a follow-up; nothing was retried automatically.',card);
        if(message.state==='RUNNING')text('p','Muse is responding…',card);
        const evidence=text('details','',card);text('summary','Evidence and receipt',evidence);
        text('p',message.state+' · task '+message.task_id+' · source '+message.source_sha,evidence).className='device-digest';
        if(message.receipt)text('p','Recorded LIVE receipt · SHA-256 '+message.receipt.response_sha256+' · estimated usage '+message.receipt.cost_estimate_usd+' USD (not an invoice)',evidence).className='device-digest';
        if(message.state==='PENDING_OWNER') {
          if(message.authorization?.basis==='OWNER_SESSION_AND_SEND') {
            text('p','Message recorded; execution was not confirmed. Check its result without resending, or stop this message.',card);
          } else {
            text('p','Cost approval stays in the local Linux channel. The model is not called before approval.',card);
            text('code','python3 -B -m runtime.webapp --mobile-operator chat-approve --state-dir /home/l/.local/state/aioa-mobile-native-main-20261102 --chat-request-id '+message.request_id,card);
          }
        }
        if(message.error)text('p',message.error,card);
        if(!message.prompt)text('p','Text expired; metadata and the Core receipt are retained.',card);
      }
      box.scrollTop=atEnd?box.scrollHeight:oldTop;
    });
    el('refresh').onclick=()=>client.refresh().catch(()=>{});
    el('send').onclick=()=>{
      const value=el('prompt').value;let reference=null;
      if(el('attach-read')?.checked){reference=readContext();if(!reference){
        el('state').textContent='Read repository and main in GitHub Tools first. The signed READ must be current and younger than five minutes.';return;
      }}
      client.send(value,reference).then(()=>{el('prompt').value='';if(el('attach-read'))el('attach-read').checked=false;}).catch(()=>{});
    };
    el('stop').onclick=()=>client.stop().catch(()=>{});
    if(el('end-session'))el('end-session').onclick=()=>client.endSession().catch(()=>{});
    el('read').onclick=()=>client.read().catch(()=>{});
    if(el('new'))el('new').onclick=()=>client.newConversation(true);
    el('prompt').onkeydown=event=>{
      if(event.key==='Enter' && !event.shiftKey && !event.isComposing && !el('send').disabled){
        event.preventDefault();el('send').onclick();
      }
    };
    client.refresh().catch(()=>{});
    setInterval(()=>{if(document.visibilityState==='visible')client.refresh({background:true}).catch(()=>{});},8000);
  }
  const api={createChat,mount};if(typeof module!=='undefined' && module.exports)module.exports=api;else root.AIOAMobileChat=Object.freeze(api);
})(typeof globalThis!=='undefined'?globalThis:this);
