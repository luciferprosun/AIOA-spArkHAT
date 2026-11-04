/* Advisory Meta chat in the existing native console. No financial approval API. */
(function(root){
  'use strict';
  const copy=x=>JSON.parse(JSON.stringify(x));
  function createChat(call,changed=()=>{},id=()=>Array.from(root.crypto.getRandomValues(new Uint8Array(16)),x=>x.toString(16).padStart(2,'0')).join('')) {
    let state={catalog:null,threads:[],thread:null,messages:[],pending:null,busy:false,error:null};
    const emit=()=>changed(copy(state));
    async function work(fn) {
      if(state.busy)throw Error('CHAT_BUSY');state.busy=true;state.error=null;emit();
      try{return await fn();}catch(e){state.error=/^[A-Z][A-Z0-9_]{1,100}$/.test(e.message)?e.message:'CHAT_READBACK_UNKNOWN';throw e;}
      finally{state.busy=false;emit();}
    }
    function accept(value) {
      if(value.schema!=='aioa.mobile.chat-result.v1' || !/^[a-f0-9]{32}$/.test(value.request_id) ||
          value.model_id!=='muse-spark-1.3' || value.provider_id!=='meta_model_api' || value.save_knowledge!==false)throw Error('CHAT_SCHEMA_INVALID');
      if(value.state==='SUCCEEDED' && (!value.live_verified || !value.receipt ||
          value.receipt.schema!=='aioa.meta.chat-receipt.v1' || value.receipt.request_digest!==value.request_digest))throw Error('CHAT_RECEIPT_UNKNOWN');
      state.thread=value.thread_id;state.messages=state.messages.filter(x=>x.request_id!==value.request_id).concat([value]).slice(-20);
      state.pending=['PENDING_OWNER','RUNNING','UNKNOWN'].includes(value.state)?value.request_id:null;
      return copy(value);
    }
    const select=async thread=>{
      if(!/^[a-f0-9]{32}$/.test(thread))throw Error('CHAT_ID_INVALID');
      const value=await call({op:'chat_thread',thread_id:thread});
      if(value.schema!=='aioa.mobile.chat-thread.v1' || value.thread_id!==thread || !Array.isArray(value.messages) || value.messages.length>20)throw Error('CHAT_SCHEMA_INVALID');
      state.messages=[];state.pending=null;state.thread=thread;for(const message of value.messages)accept(message);
      return copy(value);
    };
    return Object.freeze({snapshot:()=>copy(state),
      refresh:()=>work(async()=>{
        state.catalog=await call({op:'chat_catalog'});
        const value=await call({op:'chat_threads'});if(!Array.isArray(value.threads) || value.threads.length>24)throw Error('CHAT_SCHEMA_INVALID');
        state.threads=value.threads;
        if(state.thread || value.threads.length)await select(state.thread || value.threads[value.threads.length-1].thread_id);
      }),
      select:thread=>work(()=>select(thread)),
      send:prompt=>work(async()=>{
        if(!state.catalog?.chat || state.catalog.model_id!=='muse-spark-1.3')throw Error('CHAT_NOT_AVAILABLE');
        if(state.pending)throw Error('CHAT_READBACK_ONLY');
        if(typeof prompt!=='string' || !prompt.trim() || new TextEncoder().encode(prompt).length>2000)throw Error('CHAT_PROMPT_LIMIT');
        const request=id();state.thread=state.thread || id();state.pending=request;emit();
        return accept(await call({op:'chat_propose',payload:{schema:'aioa.mobile.chat-send.v1',thread_id:state.thread,
          request_id:request,model_id:'muse-spark-1.3',prompt,max_budget_usd:'0.05'}}));
      }),
      read:()=>work(async()=>{
        const request=state.pending || state.messages[state.messages.length-1]?.request_id;
        if(!request)throw Error('CHAT_NO_REQUEST');return accept(await call({op:'chat_request',request_id:request}));
      }),
      stop:()=>work(async()=>{
        if(!state.pending)throw Error('CHAT_NO_REQUEST');return accept(await call({op:'chat_stop',request_id:state.pending}));
      })
    });
  }
  function mount(call) {
    const el=id=>document.getElementById('native-chat-'+id);if(!el('send'))return;
    const text=(tag,value,parent)=>{const item=document.createElement(tag);item.textContent=value;parent.append(item);return item;};
    const client=createChat(call,state=>{
      el('state').textContent=state.error || (state.catalog?.chat?'Meta · muse-spark-1.3 · owner approval required for every message':'Chat is unavailable in the current profile');
      el('send').disabled=!state.catalog?.chat || state.busy || !!state.pending;
      el('refresh').disabled=state.busy;el('stop').disabled=state.busy || !state.pending;
      el('read').disabled=state.busy || !(state.pending || state.messages.length);
      el('threads').replaceChildren();
      for(const thread of state.threads) {
        const button=text('button','Conversation '+thread.thread_id.slice(0,12),el('threads'));button.className='button button-ghost';
        button.disabled=state.busy;button.onclick=()=>client.select(thread.thread_id).catch(()=>{});
      }
      el('messages').replaceChildren();
      for(const message of state.messages) {
        const card=text('article','',el('messages'));card.className='panel';
        if(message.prompt)text('p','You: '+message.prompt,card);
        if(message.reply)text('p','Muse Spark 1.3: '+message.reply,card);
        text('p',message.state+' · task '+message.task_id+' · source '+message.source_sha,card).className='device-digest';
        if(message.receipt)text('p','LIVE · SHA-256 '+message.receipt.response_sha256+' · estimated usage '+message.receipt.cost_estimate_usd+' USD (not an invoice)',card).className='device-digest';
        if(message.state==='PENDING_OWNER') {
          text('p','Cost approval stays in the local Linux channel. The model is not called before approval.',card);
          text('code','python3 -B -m runtime.webapp --mobile-operator chat-approve --state-dir /home/l/.local/state/aioa-mobile-native-main-20261102 --chat-request-id '+message.request_id,card);
        }
        if(message.error)text('p',message.error,card);
        if(!message.prompt)text('p','Text expired; metadata and the Core receipt are retained.',card);
      }
    });
    el('refresh').onclick=()=>client.refresh().catch(()=>{});
    el('send').onclick=()=>{const value=el('prompt').value;client.send(value).then(()=>{el('prompt').value='';}).catch(()=>{});};
    el('stop').onclick=()=>client.stop().catch(()=>{});
    el('read').onclick=()=>client.read().catch(()=>{});
    client.refresh().catch(()=>{});
    setInterval(()=>{if(document.visibilityState==='visible' && !client.snapshot().busy)client.refresh().catch(()=>{});},8000);
  }
  const api={createChat,mount};if(typeof module!=='undefined' && module.exports)module.exports=api;else root.AIOAMobileChat=Object.freeze(api);
})(typeof globalThis!=='undefined'?globalThis:this);
