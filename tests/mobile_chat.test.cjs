const test=require('node:test');const assert=require('node:assert/strict');const fs=require('node:fs');
const path=require('node:path').join(__dirname,'../web/mobile_chat.js');const api=fs.existsSync(path)?require(path):{};
test('chat never approves cost and duplicate send cannot repeat uncertain POST',async()=>{
  assert.equal(typeof api.createChat,'function');let sends=0;
  const client=api.createChat(async value=>{
    if(value.op==='chat_catalog')return {chat:true,model_id:'muse-spark-1.3',mission_read:'BLOCKED_NATIVE_WORKER_NOT_BOUND'};
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
