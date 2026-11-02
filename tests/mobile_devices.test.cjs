const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const file = require('node:path').join(__dirname, '../web/mobile_devices.js');
const api = fs.existsSync(file) ? require(file) : {};
const pending = {request_id:'1'.repeat(32),request_digest:'a'.repeat(64),device_id:'b'.repeat(64),device_name:'Xiaomi',sas:'123456',state:'PENDING',expires_at:200,automatic_retry:false};
function harness(handler) {
  assert.equal(typeof api.createDeviceConsole, 'function', 'owner console implementation missing');
  const calls=[];
  const client=api.createDeviceConsole('T'.repeat(43), async (url, options) => {
    calls.push({url, options});
    const data=await handler(JSON.parse(options.body));
    return {ok:true,status:200,json:async()=>({ok:true,data})};
  },()=>100);
  return {client,calls};
}
test('owner transport holds credential only in request header, not public state or body', async()=>{
  const {client,calls}=harness(()=>({pending:[pending],devices:[]}));
  await client.refresh();
  assert.equal(calls[0].url,'/api/native-operator');
  assert.equal(calls[0].options.headers['X-AIOA-Session-Token'],'T'.repeat(43));
  assert.equal(calls[0].options.redirect,'error');
  assert.equal(calls[0].options.credentials,'omit');
  assert.equal(JSON.stringify(client.snapshot()).includes('T'.repeat(43)),false);
  assert.deepEqual(JSON.parse(calls[0].options.body),{op:'pairing_list'});
});
test('exact selected request is approved once, double click cannot duplicate mutation',async()=>{
  let release;
  const {client,calls}=harness(v=>v.op==='pairing_list'?{pending:[pending],devices:[]}:new Promise(r=>{release=r;}));
  await client.refresh();
  const op=client.approve(pending.request_id,pending.request_digest);
  await assert.rejects(client.approve(pending.request_id,pending.request_digest),/BUSY/);
  release({...pending,state:'APPROVED'});await op;
  assert.deepEqual(JSON.parse(calls[1].options.body),{op:'pairing_approve',request_id:pending.request_id,request_digest:pending.request_digest,sas:pending.sas});
  await assert.rejects(client.approve(pending.request_id,pending.request_digest),/REVIEW_REQUIRED/);
  assert.equal(calls.length,2);
});
test('changed digest or expired pending request refuses locally without sending approval',async()=>{
  const {client,calls}=harness(()=>({pending:[pending],devices:[]}));await client.refresh();
  await assert.rejects(client.approve(pending.request_id,'c'.repeat(64)),/REVIEW_REQUIRED/);
  assert.equal(calls.length,1);
  const expired=harness(()=>({pending:[{...pending,expires_at:99}],devices:[]}));await expired.client.refresh();
  await assert.rejects(expired.client.approve(pending.request_id,pending.request_digest),/REVIEW_REQUIRED/);
});
test('lost approval ACK stays UNKNOWN until explicit readback and never retries',async()=>{
  let failed=false;
  const {client,calls}=harness(v=>{if(v.op==='pairing_list')return {pending:[pending],devices:[]};failed=true;throw Error('network');});
  await client.refresh();await assert.rejects(client.approve(pending.request_id,pending.request_digest),/UNKNOWN_READBACK_REQUIRED/);
  assert.equal(failed,true);assert.equal(client.snapshot().phase,'UNKNOWN');
  await assert.rejects(client.invite(),/READBACK_REQUIRED/);assert.equal(calls.length,2);
  await client.refresh();assert.equal(calls.length,3);
  assert.equal(client.snapshot().phase,'READY');
});
test('device revoke requires current reviewed device and does not accept arbitrary IDs',async()=>{
  const device={device_id:'b'.repeat(64),revoked:false};
  const {client,calls}=harness(v=>v.op==='pairing_list'?{pending:[],devices:[device]}:{device_id:device.device_id,revoked:true,revoked_sessions:1});
  await client.refresh();await assert.rejects(client.revoke('c'.repeat(64)),/REVIEW_REQUIRED/);
  await client.revoke(device.device_id);assert.equal(calls.length,2);
  assert.equal(client.snapshot().devices[0].revoked,true);
});
test('snapshots cannot alter the reviewed pending request',async()=>{
  const {client,calls}=harness(()=>({pending:[pending],devices:[]}));await client.refresh();
  client.snapshot().pending[0].request_digest='c'.repeat(64);
  await assert.rejects(client.approve(pending.request_id,'c'.repeat(64)),/REVIEW_REQUIRED/);
  assert.equal(calls.length,1);
});
test('closing the owner panel rejects late responses and cannot restore authority state',async()=>{
  let release;
  const {client,calls}=harness(()=>new Promise(r=>{release=r;}));
  const read=client.refresh();client.close();release({pending:[pending],devices:[]});
  await assert.rejects(read,/LOCAL_OPERATOR_REQUIRED/);
  assert.equal(client.snapshot().phase,'LOCKED');
  assert.deepEqual(client.snapshot().pending,[]);
  await assert.rejects(client.refresh(),/LOCAL_OPERATOR_REQUIRED/);
  assert.equal(calls.length,1);
});
