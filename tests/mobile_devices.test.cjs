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
test('only bounded READ dispatch gets the enclosing 30-second transport budget',async()=>{
  const original=global.setTimeout,delays=[];
  global.setTimeout=(fn,ms)=>{delays.push(ms);return original(fn,ms);};
  try {
    const {client}=harness(v=>v.op==='pairing_list'?{pending:[],devices:[]}:{
      receipt:{schema:'aioa.native-tool-read-receipt.v1',effect:'READ',request_id:'a'.repeat(32),operation:'git.status'},data:{}});
    await client.refresh();await client.readTool('git.status','a'.repeat(32));
    assert.deepEqual(delays,[8000,30000]);
  } finally {global.setTimeout=original;}
});
test('explicit uncertain READ readback displays its fixed timeout code and cannot redispatch',async()=>{
  const {client,calls}=harness(v=>{
    if(v.op==='pairing_list')return {pending:[],devices:[]};
    if(v.op==='tool_read')throw Error('lost ACK');
    return {state:'UNKNOWN',request_id:'a'.repeat(32),error_code:'TOOL_READ_TIMEOUT',automatic_retry:false};
  });
  await client.refresh();await assert.rejects(client.readTool('git.status','a'.repeat(32)));
  await client.readToolResult();
  assert.equal(client.snapshot().toolError,'TOOL_READ_TIMEOUT');
  assert.equal(client.snapshot().toolState,'UNKNOWN');
  assert.equal(calls.filter(c=>JSON.parse(c.options.body).op==='tool_read').length,1);
});
test('fixed READ goes through same console, rejects WRITE and keeps exact public receipt',async()=>{
  const result={receipt:{schema:'aioa.native-tool-read-receipt.v1',effect:'READ',request_id:'a'.repeat(32),
    operation:'github.repository'},data:{repository:'luciferprosun/AIOA-spArkHAT'},signature:'public-fixture'};
  const {client,calls}=harness(v=>v.op==='pairing_list'?{pending:[],devices:[]}:result);
  assert.equal(typeof client.readTool,'function','same-Core READ control is absent');
  await client.refresh();
  await assert.rejects(client.readTool('issue.create'),/TOOL_OPERATION_DENIED/);
  assert.equal(calls.length,1);
  await client.readTool('github.repository','a'.repeat(32));
  assert.deepEqual(JSON.parse(calls[1].options.body),{op:'tool_read',request_id:'a'.repeat(32),operation:'github.repository'});
  assert.deepEqual(client.snapshot().toolResult,result);
  assert.equal(JSON.stringify(client.snapshot()).includes('T'.repeat(43)),false);
});
test('lost newer READ ACK and UNKNOWN readback never present the old result as current',async()=>{
  let fail=false;
  const {client}=harness(v=>{
    if(v.op==='pairing_list')return {pending:[],devices:[]};
    if(v.op==='tool_readback')return {state:'UNKNOWN',request_id:'b'.repeat(32),automatic_retry:false};
    if(fail)throw Error('lost ACK');
    return {receipt:{schema:'aioa.native-tool-read-receipt.v1',effect:'READ',request_id:'a'.repeat(32),operation:'github.repository'},data:{}};
  });
  await client.refresh();await client.readTool('github.repository','a'.repeat(32));fail=true;
  await assert.rejects(client.readTool('github.repository','b'.repeat(32)));
  assert.equal(client.snapshot().toolResult,null);
  await client.readToolResult();
  assert.equal(client.snapshot().toolState,'UNKNOWN');
  assert.equal(client.snapshot().toolResult,null);
});
test('duplicate READ while busy cannot replace the request awaiting its ACK',async()=>{
  let complete;
  const {client}=harness(v=>v.op==='pairing_list'?{pending:[],devices:[]}:new Promise(r=>{complete=r;}));
  await client.refresh();const first=client.readTool('git.status','a'.repeat(32));
  await assert.rejects(client.readTool('git.log','b'.repeat(32)),/BUSY/);
  assert.equal(client.snapshot().toolRequest,'a'.repeat(32));
  complete({receipt:{schema:'aioa.native-tool-read-receipt.v1',effect:'READ',request_id:'a'.repeat(32),operation:'git.status'},data:{}});
  await first;
});
test('owner transport holds credential only in request header, not public state or body', async()=>{
  const {client,calls}=harness(()=>({pending:[pending],devices:[]}));
  await client.refresh();
  assert.equal(calls[0].url,'/api/native-operator');
  assert.equal(calls[0].options.headers['X-AIOA-Session-Token'],'T'.repeat(43));
  assert.equal(calls[0].options.redirect,'error');
  assert.equal(calls[0].options.credentials,'same-origin');
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

test('successful background chat reads cannot resolve an uncertain pairing approval',async()=>{
  const {client,calls}=harness(v=>{
    if(v.op==='pairing_list')return {pending:[pending],devices:[]};
    if(v.op==='chat_catalog')return {models:[]};
    throw Error('lost approval ACK');
  });
  await client.refresh();
  await assert.rejects(client.approve(pending.request_id,pending.request_digest));
  await client.chatCall({op:'chat_catalog'});
  assert.equal(client.snapshot().phase,'UNKNOWN');
  assert.equal(client.snapshot().observed,false);
  await assert.rejects(client.invite(),/READBACK_REQUIRED/);
  assert.equal(calls.filter(c=>JSON.parse(c.options.body).op==='pairing_invite').length,0);
  await client.refresh();
  assert.equal(client.snapshot().phase,'READY');
});

test('background chat read neither takes nor releases a foreground mutation lock',async()=>{
  let finishRead,finishInvite;
  const {client,calls}=harness(v=>{
    if(v.op==='pairing_list')return {pending:[],devices:[]};
    if(v.op==='chat_catalog')return new Promise(resolve=>{finishRead=resolve;});
    if(v.op==='pairing_invite')return new Promise(resolve=>{finishInvite=resolve;});
    assert.fail('unexpected operation');
  });
  await client.refresh();const read=client.chatCall({op:'chat_catalog'});
  assert.equal(client.snapshot().busy,false);
  const invite=client.invite();assert.equal(client.snapshot().busy,true);
  finishRead({chat:true});await read;
  assert.equal(client.snapshot().busy,true);
  await assert.rejects(client.invite(),/BUSY/);
  finishInvite({invite:'synthetic'});await invite;
  assert.equal(client.snapshot().busy,false);
  assert.equal(calls.filter(c=>JSON.parse(c.options.body).op==='pairing_invite').length,1);
});
test('background registry polling cannot block chat or overwrite a newer device approval',async()=>{
  let finish,defer=false;
  const {client}=harness(v=>{
    if(v.op==='pairing_list')return defer?new Promise(resolve=>{finish=resolve;}):{pending:[pending],devices:[]};
    if(v.op==='chat_propose')return {state:'PENDING_OWNER'};
    if(v.op==='pairing_approve')return {...pending,state:'APPROVED'};
    assert.fail('unexpected operation');
  });
  await client.refresh();defer=true;const poll=client.refresh({background:true});
  assert.equal(client.snapshot().busy,false);
  await client.chatCall({op:'chat_propose',payload:{}});
  await client.approve(pending.request_id,pending.request_digest);
  finish({pending:[pending],devices:[]});await poll;
  assert.equal(client.snapshot().pending[0].state,'APPROVED');
});

test('core history read requires registry readback and cannot resolve uncertain approval',async()=>{
  const status={profile:'NATIVE_STATUS_READ_ONLY_V1',source_sha:'a'.repeat(40),capsule_digest:'b'.repeat(64),
    origin:'https://host.invalid',tls_spki_pin:'sha256/public',host_spki:'public',model_calls:0,
    operator_authentication:'OS_POLICYKIT',sessions:[],observations:[],history_truncated:false};
  const {client,calls}=harness(v=>{
    if(v.op==='pairing_list')return {pending:[pending],devices:[]};
    if(v.op==='status')return status;
    throw Error('lost ACK');
  });
  assert.equal(typeof client.status,'function');
  await assert.rejects(client.status(),/READBACK_REQUIRED/);assert.equal(calls.length,0);
  await client.refresh();await client.status();
  assert.deepEqual(client.snapshot().coreStatus,status);
  assert.equal(client.snapshot().coreStatusAt,100);
  await assert.rejects(client.approve(pending.request_id,pending.request_digest),/UNKNOWN_READBACK_REQUIRED/);
  await assert.rejects(client.status(),/READBACK_REQUIRED/);
  assert.equal(calls.filter(c=>JSON.parse(c.options.body).op==='status').length,1);
  assert.equal(client.snapshot().phase,'UNKNOWN');
  // Keep previous public data as historical; never restore mutation availability.
  assert.deepEqual(client.snapshot().coreStatus,status);
  await client.refresh();await client.status();assert.equal(client.snapshot().phase,'READY');
  client.close();assert.equal(client.snapshot().coreStatus,null);
});

test('malformed Core history cannot render as trusted observations or restore controls',async()=>{
  const {client}=harness(v=>v.op==='pairing_list'?{pending:[],devices:[]}:{
    profile:'NATIVE_STATUS_READ_ONLY_V1',model_calls:0,sessions:[],history_truncated:false,
    observations:[{proof:{issued_at:'invalid',expires_at:200},signature:'unverified'}]});
  await client.refresh();
  await assert.rejects(client.status(),/UNKNOWN_READBACK_REQUIRED/);
  assert.equal(client.snapshot().phase,'UNKNOWN');assert.equal(client.snapshot().coreStatus,null);
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

test('revoked QR trust still exposes revocation of fresh legacy sessions and grants',async()=>{
  for (const counts of [{active_sessions:1,pending_enrollments:0},{active_sessions:0,pending_enrollments:1}]) {
    const device={device_id:'b'.repeat(64),revoked:true,...counts};
    const {client,calls}=harness(v=>v.op==='pairing_list'?{pending:[],devices:[device]}:{device_id:device.device_id,revoked:true,revoked_sessions:counts.active_sessions});
    await client.refresh();await client.revoke(device.device_id);
    assert.equal(calls.length,2);
    assert.deepEqual(JSON.parse(calls[1].options.body),{op:'pairing_revoke',device_id:device.device_id});
    const after=client.snapshot().devices[0];
    assert.equal(after.revoked,true);
    assert.equal(after.active_sessions,0);
    assert.equal(after.pending_enrollments,0);
    await assert.rejects(client.revoke(device.device_id),/REVIEW_REQUIRED/);
    assert.equal(calls.length,2);
  }
});
test('device panel renders revoked reconnect separately from active legacy access and its revoke control',async()=>{
  const vm=require('node:vm');
  class Element {
    constructor(tag='div') {this.tag=tag;this.children=[];this.dataset={};this.listeners={};this.textContent='';this.classList={add(){}};}
    remove(){this.removed=true;this.value='';}
    append(child){this.children.push(child);}
    replaceChildren(){this.children=[];}
    addEventListener(event,fn){this.listeners[event]=fn;}
    getContext(){return {clearRect(){}};}
    text(){return this.textContent+this.children.map(x=>x.text()).join(' ');}
  }
  const ids=new Map();const get=id=>{if(!ids.has(id))ids.set(id,new Element());return ids.get(id);};
  const device={device_id:'b'.repeat(64),device_name:'Phone',revoked:true,active_sessions:1,pending_enrollments:1};
  const document={body:new Element('body'),getElementById:get,createElement:tag=>new Element(tag)};
  const credential=get('aioa-console-credential');credential.value='';
  let consumed=false;
  const client={snapshot:()=>({phase:'READY',pending:[],devices:[device],busy:false}),refresh:async()=>{}};
  vm.runInNewContext(fs.readFileSync(require('node:path').join(__dirname,'../web/mobile_devices_dom.js'),'utf8'),{
    location:{pathname:'/devices',hash:'',search:''},history:{replaceState(){}},document,
    AIOAMobileDevices:{...api,createDeviceConsole:token=>{
      assert.equal(token,'T'.repeat(43));assert.equal(credential.value,'');
      consumed=true;return client;
    }},AIOAMobileChat:{mount:()=>assert.fail('status-only profile must not invoke chat APIs')},
    fetch:async()=>({ok:true,json:async()=>({ok:true,csrf_token:'T'.repeat(43),profile:'NATIVE_STATUS_READ_ONLY_V1'})}),
    window:{addEventListener(){}},setInterval(){},Date,JSON});
  await new Promise(resolve=>setImmediate(resolve));
  assert.equal(consumed,true,'memory client must obtain anti-CSRF value through the cookie-authenticated JSON bootstrap');
  const card=get('devices-trusted').children[0];
  assert.match(card.text(),/Reconnect revoked/);
  assert.match(card.text(),/Active sessions: 1/);
  assert.match(card.text(),/Pending codes: 1/);
  const button=card.children.find(x=>x.tag==='button');
  assert.ok(button,'fresh legacy access must retain a revoke action');
  assert.equal(button.disabled,false);
  assert.equal(button.dataset.deviceFocus,JSON.stringify(['revoke',device.device_id]));
  // A manually supplied legacy hash cannot supply a credential to a public GET.
  vm.runInNewContext(fs.readFileSync(require('node:path').join(__dirname,'../web/mobile_devices_dom.js'),'utf8'),{
    location:{pathname:'/devices',hash:'#operator='+'T'.repeat(43)},history:{replaceState(){}},
    document:{...document,getElementById:id=>id==='aioa-console-credential'?null:get(id)},
    AIOAMobileDevices:{...api,createDeviceConsole:()=>assert.fail('URL credential accepted')},
    fetch:async()=>({ok:false}),window:{addEventListener(){}},setInterval(){},Date,JSON});
});
