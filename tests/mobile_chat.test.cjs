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
