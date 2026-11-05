const test=require('node:test');const assert=require('node:assert/strict');const fs=require('node:fs');
const path=require('node:path').join(__dirname,'../web/mobile_chat.js');const api=fs.existsSync(path)?require(path):{};
test('superseded background success cannot clear a newer uncertain-send error',async()=>{
  let defer=false,finish;
  const client=api.createChat(async value=>{
    if(value.op==='chat_catalog')return {chat:true,model_id:'muse-spark-1.3'};
    if(value.op==='chat_threads')return defer?new Promise(resolve=>{finish=()=>resolve({threads:[]});}):{threads:[]};
    throw Error('NETWORK_ACK_LOST');
  },()=>{},()=> 'a'.repeat(32));
  await client.refresh();defer=true;const background=client.refresh({background:true});
  await new Promise(resolve=>setImmediate(resolve));await assert.rejects(client.send('one attempt'),/NETWORK_ACK_LOST/);
  finish();await background;
  assert.equal(client.snapshot().error,'NETWORK_ACK_LOST');assert.equal(client.snapshot().pending,'a'.repeat(32));
});
test('successful current background read clears a transient banner without resending',async()=>{
  let failure=false;const calls=[];
  const client=api.createChat(async value=>{
    calls.push(value.op);if(failure)throw Error('UNKNOWN_READBACK_REQUIRED');
    return value.op==='chat_catalog'?{chat:true,model_id:'muse-spark-1.3',mode:'LIVE_OWNER_SESSION'}:{threads:[]};
  });
  await client.refresh();failure=true;
  await assert.rejects(client.refresh({background:true}),/UNKNOWN_READBACK_REQUIRED/);
  failure=false;await client.refresh({background:true});
  assert.equal(client.snapshot().error,null);
  assert.equal(client.snapshot().catalog.mode,'LIVE_OWNER_SESSION');
  assert.ok(calls.every(op=>['chat_catalog','chat_threads'].includes(op)));
});
test('recovered background read retains authoritative UNKNOWN and its send barrier',async()=>{
  let failure=false;
  const message={schema:'aioa.mobile.chat-result.v1',request_id:'a'.repeat(32),thread_id:'b'.repeat(32),
    provider_id:'meta_model_api',model_id:'muse-spark-1.3',save_knowledge:false,state:'UNKNOWN'};
  const client=api.createChat(async value=>{
    if(failure)throw Error('UNKNOWN_READBACK_REQUIRED');
    if(value.op==='chat_catalog')return {chat:true,model_id:'muse-spark-1.3'};
    if(value.op==='chat_threads')return {threads:[{thread_id:message.thread_id}]};
    if(value.op==='chat_thread')return {schema:'aioa.mobile.chat-thread.v1',thread_id:message.thread_id,messages:[message]};
    assert.fail('recovery cannot send');
  });
  await client.refresh();failure=true;await assert.rejects(client.refresh({background:true}));
  failure=false;await client.refresh({background:true});
  assert.equal(client.snapshot().error,null);assert.equal(client.snapshot().pending,message.request_id);
  await assert.rejects(client.send('do not repeat'),/CHAT_READBACK_ONLY/);
});
test('verified partial response permits a new explicit message without retrying the first',async()=>{
  let count=0,serial=0,current;
  const chat=api.createChat(async v=>{
    if(v.op==='chat_catalog')return {chat:true,model_id:'muse-spark-1.3',mode:'LIVE_OWNER_SESSION'};
    if(v.op==='chat_threads')return {threads:[]};
    if(v.op==='chat_send') {count++;current={schema:'aioa.mobile.chat-result.v1',request_id:v.payload.request_id,
      thread_id:v.payload.thread_id,provider_id:'meta_model_api',model_id:'muse-spark-1.3',save_knowledge:false,state:'RUNNING'};return current;}
    assert.equal(v.op,'chat_request');return {...current,state:'TRUNCATED',live_verified:true,reply:'partial',request_digest:'d'.repeat(64),
      receipt:{schema:'aioa.meta.chat-receipt.v2',request_digest:'d'.repeat(64),finish_reason:'length',response_complete:false}};
  },()=>{},()=> (++serial).toString(16).padStart(32,'0'));
  await chat.refresh();await chat.send('First');await chat.read();
  assert.equal(chat.snapshot().pending,null);assert.equal(chat.snapshot().messages[0].reply,'partial');
  await chat.send('Follow up');assert.equal(count,2);
});
test('owner conversation crosses the actual console transport and can end its session',async()=>{
  const {createDeviceConsole}=require('../web/mobile_devices.js');
  const calls=[];let serial=0,active=true,latest;
  const consoleClient=createDeviceConsole('T'.repeat(43),async(url,options)=>{
    assert.equal(url,'/api/native-operator');
    assert.equal(options.headers['X-AIOA-Session-Token'],'T'.repeat(43));
    assert.equal(options.credentials,'same-origin');
    const value=JSON.parse(options.body);calls.push(value);
    let data;
    if(value.op==='chat_catalog')data={chat:active,model_id:'muse-spark-1.3',mode:active?'LIVE_OWNER_SESSION':'LIVE_PENDING_EXACT_OWNER_APPROVAL'};
    else if(value.op==='chat_threads')data={threads:[]};
    else if(value.op==='chat_send'){
      assert.equal(value.payload.schema,'aioa.mobile.chat-send.v2');
      assert.equal('max_budget_usd' in value.payload,false);
      latest={schema:'aioa.mobile.chat-result.v1',request_id:value.payload.request_id,thread_id:value.payload.thread_id,
        provider_id:'meta_model_api',model_id:'muse-spark-1.3',save_knowledge:false,state:'RUNNING'};
      data=latest;
    } else if(value.op==='chat_request')data={...latest,state:'SUCCEEDED',live_verified:true,reply:'Synthetic reply',request_digest:'a'.repeat(64),
      receipt:{schema:'aioa.meta.chat-receipt.v1',request_digest:'a'.repeat(64)}};
    else if(value.op==='chat_session_stop'){active=false;data={state:'INACTIVE'};}
    else assert.fail('Unexpected operation: '+value.op);
    return {ok:true,status:200,json:async()=>({ok:true,data})};
  });
  const chat=api.createChat(consoleClient.chatCall,()=>{},()=> (++serial).toString(16).padStart(32,'0'));
  await chat.refresh();await chat.send('First message');await chat.read();
  assert.equal(chat.snapshot().messages[0].reply,'Synthetic reply');
  const thread=chat.snapshot().thread;
  await chat.send('Second message');await chat.read();
  assert.equal(chat.snapshot().thread,thread);assert.equal(chat.snapshot().pending,null);
  assert.equal(calls.filter(x=>x.op==='chat_send').length,2);
  await chat.endSession();await assert.rejects(chat.send('Session ended'),/CHAT_NOT_AVAILABLE/);
  assert.equal(calls.some(x=>['chat_approve','chat_session_start','budget_approve'].includes(x.op)),false);
});
test('lost session send ACK through console transport retains the request and never retries',async()=>{
  const {createDeviceConsole}=require('../web/mobile_devices.js');
  let sends=0;
  const transport=createDeviceConsole('T'.repeat(43),async(url,options)=>{
    const value=JSON.parse(options.body);
    if(value.op==='chat_send'){sends++;throw Error('lost ACK');}
    const data=value.op==='chat_catalog'?{chat:true,model_id:'muse-spark-1.3',mode:'LIVE_OWNER_SESSION'}:{threads:[]};
    return {ok:true,status:200,json:async()=>({ok:true,data})};
  });
  const chat=api.createChat(transport.chatCall,()=>{},()=> 'a'.repeat(32));
  await chat.refresh();await assert.rejects(chat.send('One attempt'),/UNKNOWN_READBACK_REQUIRED/);
  assert.equal(chat.snapshot().pending,'a'.repeat(32));
  await assert.rejects(chat.send('One attempt'),/CHAT_READBACK_ONLY/);
  assert.equal(sends,1);
});
test('an owner session sends directly without a cost approval or a browser-supplied budget',async()=>{
  const calls=[];let serial=0;
  const client=api.createChat(async value=>{
    calls.push(value);
    if(value.op==='chat_catalog')return {chat:true,model_id:'muse-spark-1.3',mode:'LIVE_OWNER_SESSION'};
    if(value.op==='chat_threads')return {threads:[]};
    assert.equal(value.op,'chat_send');
    return {schema:'aioa.mobile.chat-result.v1',request_id:value.payload.request_id,thread_id:value.payload.thread_id,
      provider_id:'meta_model_api',model_id:'muse-spark-1.3',save_knowledge:false,state:'RUNNING'};
  },()=>{},()=> (++serial).toString(16).padStart(32,'0'));
  await client.refresh();await client.send('Cześć!');
  assert.equal(calls.at(-1).payload.schema,'aioa.mobile.chat-send.v2');
  assert.equal('max_budget_usd' in calls.at(-1).payload,false);
  assert.equal(calls.some(v=>['chat_approve','chat_session_start','budget_approve'].includes(v.op)),false);
  await assert.rejects(client.send('same again'),/CHAT_READBACK_ONLY/);
});
test('new ordinary conversation clears context locally without a confirmation or remote mutation',async()=>{
  const calls=[];let serial=0;
  const client=api.createChat(async value=>{
    calls.push(value);
    if(value.op==='chat_catalog')return {chat:true,model_id:'muse-spark-1.3',mode:'LIVE_OWNER_SESSION'};
    if(value.op==='chat_threads')return {threads:[]};
    assert.fail('new conversation must not spend or approve');
  },()=>{},()=> (++serial).toString(16).padStart(32,'0'));
  await client.refresh();const before=calls.length;
  client.newConversation(true);assert.equal(client.snapshot().draft,true);
  assert.equal(calls.length,before);
});
test('initial selection prefers current successful text over historical UNKNOWN and preserves manual history',async()=>{
  const fresh='1'.repeat(32),old='2'.repeat(32);let selected;
  const client=api.createChat(async v=>{
    if(v.op==='chat_catalog')return {chat:true,model_id:'muse-spark-1.3'};
    if(v.op==='chat_threads')return {threads:[
      {thread_id:fresh,state:'SUCCEEDED',current_source:true,text_available:true},
      {thread_id:old,state:'UNKNOWN',current_source:false,text_available:false}]};
    if(v.op==='chat_thread'){selected=v.thread_id;return {schema:'aioa.mobile.chat-thread.v1',thread_id:v.thread_id,messages:[]};}
    assert.fail('unexpected mutation');
  });
  await client.refresh();assert.equal(selected,fresh);
  await client.select(old);await client.refresh();assert.equal(client.snapshot().thread,old);
});
test('slow background refresh never blocks a new send or replaces its selected conversation',async()=>{
  let finish,serial=0;
  const client=api.createChat(async v=>{
    if(v.op==='chat_catalog')return {chat:true,model_id:'muse-spark-1.3'};
    if(v.op==='chat_threads')return serial?new Promise(resolve=>{finish=resolve;}):{threads:[]};
    if(v.op==='chat_propose')return {schema:'aioa.mobile.chat-result.v1',request_id:v.payload.request_id,
      thread_id:v.payload.thread_id,provider_id:'meta_model_api',model_id:'muse-spark-1.3',save_knowledge:false,state:'PENDING_OWNER'};
    assert.fail('unexpected thread switch');
  },()=>{},()=>String(++serial).padStart(32,'0'));
  await client.refresh();serial=1;
  const refresh=client.refresh({background:true});await new Promise(resolve=>setImmediate(resolve));
  assert.equal(client.snapshot().busy,false);
  await client.send('a separate exact owner approval is still required');const thread=client.snapshot().thread;
  finish({threads:[{thread_id:'f'.repeat(32)}]});await refresh;
  assert.equal(client.snapshot().thread,thread);assert.ok(client.snapshot().pending);
});
test('explicit separate conversation supersedes a late background historical read',async()=>{
  const old={schema:'aioa.mobile.chat-result.v1',request_id:'a'.repeat(32),thread_id:'b'.repeat(32),
    provider_id:'meta_model_api',model_id:'muse-spark-1.3',save_knowledge:false,state:'UNKNOWN'};
  let finish,defer=false;
  const client=api.createChat(async v=>{
    if(v.op==='chat_catalog')return {chat:true,model_id:'muse-spark-1.3'};
    if(v.op==='chat_threads')return {threads:[{thread_id:old.thread_id}]};
    const reply={schema:'aioa.mobile.chat-thread.v1',thread_id:old.thread_id,messages:[old]};
    return defer?new Promise(resolve=>{finish=()=>resolve(reply);}):reply;
  },()=>{},()=> 'f'.repeat(32));
  await client.refresh();defer=true;const refresh=client.refresh({background:true});
  await new Promise(resolve=>setImmediate(resolve));client.newConversation(true);finish();await refresh;
  assert.equal(client.snapshot().thread,'f'.repeat(32));assert.equal(client.snapshot().draft,true);
  assert.equal(client.snapshot().pending,null);
});
test('proven local refusal before dispatch does not leave a phantom pending request',async()=>{
  const client=api.createChat(async v=>{
    if(v.op==='chat_catalog')return {chat:true,model_id:'muse-spark-1.3'};
    if(v.op==='chat_threads')return {threads:[]};
    const error=Error('READBACK_REQUIRED');error.notDispatched=true;throw error;
  },()=>{},()=> 'a'.repeat(32));
  await client.refresh();await assert.rejects(client.send('hello'));
  assert.equal(client.snapshot().pending,null);
});
test('wrong response identity cannot clear the exact uncertain request or switch its thread',async()=>{
  const pending={schema:'aioa.mobile.chat-result.v1',request_id:'a'.repeat(32),thread_id:'b'.repeat(32),
    provider_id:'meta_model_api',model_id:'muse-spark-1.3',save_knowledge:false,state:'PENDING_OWNER'};
  for(const operation of ['send','read','stop']) {
    const client=api.createChat(async v=>{
      if(v.op==='chat_catalog')return {chat:true,model_id:'muse-spark-1.3'};
      if(v.op==='chat_threads')return {threads:[]};
      if(v.op==='chat_propose' && operation!=='send')return {...pending,thread_id:v.payload.thread_id};
      return {...pending,request_id:'f'.repeat(32),state:'FAILED'};
    },()=>{},()=> 'a'.repeat(32));
    await client.refresh();
    if(operation==='send')await assert.rejects(client.send('hello'),/CHAT_RESPONSE_MISMATCH/);
    else {await client.send('hello');await assert.rejects(client[operation](),/CHAT_RESPONSE_MISMATCH/);}
    assert.equal(client.snapshot().pending,'a'.repeat(32));
    assert.equal(client.snapshot().messages.some(x=>x.request_id==='f'.repeat(32)),false);
  }
});
test('confirmed operator denial disables chat while a read timeout does not log out',async()=>{
  let failure=null;
  const client=api.createChat(async v=>{
    if(failure)throw Error(failure);
    return v.op==='chat_catalog'?{chat:true,model_id:'muse-spark-1.3'}:{threads:[]};
  });
  await client.refresh();failure='UNKNOWN_READBACK_REQUIRED';await assert.rejects(client.refresh());
  assert.equal(client.snapshot().catalog.chat,true);
  failure='LOCAL_OPERATOR_REQUIRED';await assert.rejects(client.refresh());
  assert.equal(client.snapshot().catalog,null);
  await assert.rejects(client.send('hello'),/CHAT_NOT_AVAILABLE/);
});
test('explicit READ attachment forwards only its existing receipt reference and never fetches or approves',async()=>{
  const calls=[];
  const client=api.createChat(async v=>{
    calls.push(v);
    if(v.op==='chat_catalog')return {chat:true,model_id:'muse-spark-1.3'};
    if(v.op==='chat_threads')return {threads:[]};
    return {schema:'aioa.mobile.chat-result.v1',request_id:v.payload.request_id,thread_id:v.payload.thread_id,
      provider_id:'meta_model_api',model_id:'muse-spark-1.3',save_knowledge:false,state:'PENDING_OWNER'};
  },()=>{},()=> 'a'.repeat(32));
  await client.refresh();await client.send('Explain the attached observation','b'.repeat(32));
  assert.equal(calls.at(-1).read_request_id,'b'.repeat(32));
  assert.equal(calls.some(v=>['tool_read','chat_approve'].includes(v.op)),false);
});
test('chat never approves cost and duplicate send cannot repeat uncertain POST',async()=>{
  assert.equal(typeof api.createChat,'function');let sends=0;
  const client=api.createChat(async value=>{
    if(value.op==='chat_catalog')return {chat:true,model_id:'muse-spark-1.3',mission_read:'BLOCKED_NATIVE_WORKER_NOT_CERTIFIED'};
    if(value.op==='chat_threads')return {threads:[]};
    if(value.op==='chat_propose'){sends++;throw Error('lost ACK');}
    throw Error('denied');
  },()=>{},()=> 'a'.repeat(32));
  await client.refresh();await assert.rejects(client.send('hello'));
  assert.equal(client.snapshot().pending,'a'.repeat(32));assert.equal(sends,1);
  await assert.rejects(client.send('hello'));assert.equal(sends,1);
  assert.equal(client.approve,undefined);
});
test('unavailable profile cannot send a model prompt',async()=>{
  assert.equal(typeof api.createChat,'function');let calls=0;
  const client=api.createChat(async()=>{calls++;return {chat:false};},()=>{},()=> 'a'.repeat(32));
  await assert.rejects(client.send('hello'));assert.equal(calls,0);
});

test('separate conversation requires authoritative UNKNOWN and survives refresh without retry',async()=>{
  const calls=[];let serial=0;
  const old={schema:'aioa.mobile.chat-result.v1',request_id:'a'.repeat(32),thread_id:'b'.repeat(32),
    provider_id:'meta_model_api',model_id:'muse-spark-1.3',save_knowledge:false,state:'UNKNOWN'};
  const client=api.createChat(async value=>{
    calls.push(value);
    if(value.op==='chat_catalog')return {chat:true,model_id:'muse-spark-1.3'};
    if(value.op==='chat_threads')return {threads:[{thread_id:old.thread_id}]};
    if(value.op==='chat_thread')return {schema:'aioa.mobile.chat-thread.v1',thread_id:old.thread_id,messages:[old]};
    assert.fail('recovery must not POST or approve');
  },()=>{},()=> (++serial).toString(16).padStart(32,'0'));
  await client.refresh();assert.equal(client.snapshot().pending,old.request_id);
  assert.equal(typeof client.newConversation,'function','explicit UNKNOWN recovery is missing');
  assert.throws(()=>client.newConversation(false));
  const before=calls.length;client.newConversation(true);
  assert.equal(calls.length,before);assert.equal(client.snapshot().pending,null);
  assert.notEqual(client.snapshot().thread,old.thread_id);const fresh=client.snapshot().thread;
  await client.refresh();assert.equal(client.snapshot().thread,fresh);assert.deepEqual(client.snapshot().messages,[]);
  await client.select(old.thread_id);assert.equal(client.snapshot().pending,old.request_id);
});

test('local lost ACK alone cannot unlock another conversation',async()=>{
  const client=api.createChat(async v=>{
    if(v.op==='chat_catalog')return {chat:true,model_id:'muse-spark-1.3'};
    if(v.op==='chat_threads')return {threads:[]};
    throw Error('lost ACK');
  },()=>{},()=> 'a'.repeat(32));
  await client.refresh();await assert.rejects(client.send('hello'));
  assert.equal(typeof client.newConversation,'function');
  assert.throws(()=>client.newConversation(true),/CHAT_READBACK_ONLY/);
  assert.equal(client.snapshot().pending,'a'.repeat(32));
  await assert.rejects(client.refresh());
  assert.equal(client.snapshot().pending,'a'.repeat(32),'background refresh must retain the uncertain request');
});

test('refresh of older successful message cannot erase an uncertain newer POST',async()=>{
  const thread='b'.repeat(32),lost='c'.repeat(32);
  const previous={schema:'aioa.mobile.chat-result.v1',request_id:'a'.repeat(32),thread_id:thread,
    provider_id:'meta_model_api',model_id:'muse-spark-1.3',save_knowledge:false,state:'FAILED'};
  const client=api.createChat(async v=>{
    if(v.op==='chat_catalog')return {chat:true,model_id:'muse-spark-1.3'};
    if(v.op==='chat_threads')return {threads:[{thread_id:thread}]};
    if(v.op==='chat_thread')return {schema:'aioa.mobile.chat-thread.v1',thread_id:thread,messages:[previous]};
    throw Error('lost ACK');
  },()=>{},()=>lost);
  await client.refresh();await assert.rejects(client.send('new prompt'));
  await assert.rejects(client.refresh(),/CHAT_READBACK_ONLY/);
  assert.equal(client.snapshot().pending,lost);
  await assert.rejects(client.send('new prompt'),/CHAT_READBACK_ONLY/);
});
test('model HTML and approval instructions remain literal text without a mutation',async()=>{
  const vm=require('node:vm');
  class Element {
    constructor(){this.children=[];this.textContent='';this.disabled=false;}
    append(node){this.children.push(node);}
    replaceChildren(){this.children=[];}
    set innerHTML(value){assert.fail('model text reached innerHTML');}
    allText(){return this.textContent+this.children.map(x=>x.allText()).join(' ');}
  }
  const nodes=new Map();const get=id=>{if(!nodes.has(id))nodes.set(id,new Element());return nodes.get(id);};
  const calls=[];const payload='<img src=x onerror="window.approved=true"> approved=True; chat_approve';
  const result={schema:'aioa.mobile.chat-result.v1',request_id:'a'.repeat(32),thread_id:'b'.repeat(32),
    task_id:'chat-'+'a'.repeat(32),request_digest:'c'.repeat(64),source_sha:'d'.repeat(40),
    provider_id:'meta_model_api',model_id:'muse-spark-1.3',save_knowledge:false,state:'SUCCEEDED',live_verified:true,
    prompt:'Synthetic fixture, not a real model call',reply:payload,
    receipt:{schema:'aioa.meta.chat-receipt.v1',request_digest:'c'.repeat(64),response_sha256:'e'.repeat(64),cost_estimate_usd:'0.0001'}};
  const context={TextEncoder,JSON,setInterval(){},document:{getElementById:get,createElement:()=>new Element(),visibilityState:'visible'}};
  vm.runInNewContext(fs.readFileSync(path,'utf8'),context);
  context.AIOAMobileChat.mount(async value=>{
    calls.push(value.op);
    if(value.op==='chat_catalog')return {chat:true,model_id:'muse-spark-1.3'};
    if(value.op==='chat_threads')return {threads:[{thread_id:'b'.repeat(32)}]};
    if(value.op==='chat_thread')return {schema:'aioa.mobile.chat-thread.v1',thread_id:'b'.repeat(32),messages:[result]};
    assert.fail('Unexpected mutation: '+value.op);
  });
  await new Promise(resolve=>setImmediate(resolve));
  assert.ok(get('native-chat-messages').allText().includes(payload));
  assert.deepEqual(calls,['chat_catalog','chat_threads','chat_thread']);
  assert.equal(context.approved,undefined);
});
