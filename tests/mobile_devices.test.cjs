const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const file = require('node:path').join(__dirname, '../web/mobile_devices.js');
const api = fs.existsSync(file) ? require(file) : {};

test('chat403 clears outer private DOM and inputs immediately while a foreground request is pending',async()=>{
  const vm=require('node:vm'),h=privacyConsole();await h.seed();
  class Element {
    constructor(){this.children=[];this.dataset={};this.listeners={};this.textContent='';this.value='';this.classList={add(){}};}
    append(child){this.children.push(child);} replaceChildren(){this.children=[];}
    addEventListener(name,fn){this.listeners[name]=fn;} getContext(){return {clearRect(){}};}
  }
  const ids=new Map(),get=id=>{if(!ids.has(id))ids.set(id,new Element());return ids.get(id);};
  const document={body:new Element(),getElementById:get,createElement:()=>new Element()};
  let chatCall,closed=0;
  vm.runInNewContext(fs.readFileSync(require('node:path').join(__dirname,'../web/mobile_devices_dom.js'),'utf8'),{
    location:{pathname:'/devices'},history:{replaceState(){}},document,Date,JSON,setInterval(){},
    window:{addEventListener(){}},AIOAMobileDevices:{...api,createDeviceConsole:()=>h.client},
    AIOAMobileChat:{mount:call=>{chatCall=call;return {close:()=>{closed++;}};}},
    fetch:async()=>({ok:true,json:async()=>({ok:true,csrf_token:'T'.repeat(43),profile:'NATIVE_ADVISORY_CHAT_V1'})})
  });
  await new Promise(resolve=>setImmediate(resolve));assert.equal(typeof chatCall,'function');
  const inputs=['cosmic-proposal-chat','cosmic-command-input','cosmic-cpt-input',
    'cosmic-mail-sender','cosmic-mail-to','cosmic-mail-subject','cosmic-mail-body'];
  for(const id of inputs)get(id).value=h.marker;
  assert.ok(get('cosmic-proposal-result').textContent.includes(h.marker));
  const deferred=h.deferStatus(),pending=h.client.githubStatus(),settle=await deferred;
  const rejected=assert.rejects(pending,/LOCAL_OPERATOR_REQUIRED/);
  h.setDenied(403);await assert.rejects(chatCall({op:'chat_catalog'}),/LOCAL_OPERATOR_REQUIRED/);
  assert.ok(closed>0,'mounted chat closes on denial');
  for(const id of inputs)assert.equal(get(id).value,'',id);
  for(const id of ['cosmic-proposal-result','cosmic-advisory-result','cosmic-github-receipt'])
    assert.equal(get(id).textContent.includes(h.marker),false,id);
  assert.equal(get('cosmic-github-approve').disabled,true);
  assert.equal(get('cosmic-github-history-read').disabled,true);
  assert.match(get('devices-message').textContent,/local operator session/);
  settle({operation_id:'d'.repeat(32),review:{private:h.marker}});await rejected;
});


function privacyConsole() {
  const marker='PRIVATE_OWNER_DRAFT',calls=[];
  let deny=0,pendingReply=null;
  const client=api.createDeviceConsole('T'.repeat(43),async(_,options)=>{
    const request=JSON.parse(options.body);calls.push(request);
    if(deny)return {ok:false,status:deny};
    if(request.op==='github_write_status' && pendingReply)return pendingReply;
    let data;
    if(request.op==='pairing_list')data={pending:[],devices:[]};
    else if(request.op==='tool_read')data={data:{private:marker},receipt:{
      schema:'aioa.native-tool-read-receipt.v1',effect:'READ',request_id:request.request_id,operation:request.operation,
      observed_at:100,source_sha:'a'.repeat(40),capsule_digest:'b'.repeat(64),data_sha256:'c'.repeat(64)}};
    else if(request.op==='mail_preview')data={data:{private:marker},receipt:{
      schema:'aioa.native-advisory-receipt.v1',effect:'ADVISORY_PREVIEW',request_id:request.request_id,
      operation:request.op,execution_authorized:false,provider_calls:0,external_calls:0,automatic_retry:false}};
    else if(request.op==='github_write_list')data={operations:[{operation_id:'d'.repeat(32),private:marker}]};
    else if(request.op==='tool_proposal' || request.op==='github_write_approve' || request.op==='github_write_status')data={
      operation_id:'d'.repeat(32),status:request.op==='github_write_approve'?'GITHUB_APPROVED':'GITHUB_PROPOSED',
      execution_authorized:false,approval_available:true,review_digest:'a'.repeat(64),
      review:{files:{'agent-demo/note.md':marker}},
      proposal:{operation:'code.commit_draft_pr',source_chat_request_id:'b'.repeat(32)}};
    else if(request.op==='chat_catalog')data={private:marker};
    else assert.fail('unexpected '+request.op);
    return {ok:true,json:async()=>({ok:true,data})};
  });
  const seed=async()=>{
    await client.refresh();await client.readTool('github.demo_context','c'.repeat(32));
    await client.preview('mail_preview',{body_text:marker},'e'.repeat(32));
    await client.githubHistory();await client.proposeTool('b'.repeat(32));
    assert.ok(JSON.stringify(client.snapshot()).includes(marker));
  };
  return {client,calls,marker,seed,setDenied:status=>{deny=status;},
    deferStatus:()=>new Promise(resolve=>{pendingReply=new Promise(reply=>resolve((data,status=200)=>reply(
      status===200?{ok:true,json:async()=>({ok:true,data})}:{ok:false,status})));})};
}
test('HTTP403 erases saved private READ, review, history and advisory after proposal or approval',async()=>{
  for(const approved of [false,true]) {
    const h=privacyConsole();await h.seed();
    if(approved)await h.client.githubApprove();
    h.setDenied(403);await assert.rejects(h.client.refresh(),/LOCAL_OPERATOR_REQUIRED/);
    const state=h.client.snapshot();
    assert.equal(state.phase,'UNKNOWN');assert.equal(state.message,'LOCAL_OPERATOR_REQUIRED');
    assert.equal(state.observed,false);
    assert.equal(JSON.stringify(state).includes(h.marker),false,'denied operator retains private result');
    assert.equal(state.githubOperation,undefined);
    const count=h.calls.length;
    await assert.rejects(h.client.githubApprove());await h.client.refresh({background:true});
    assert.equal(h.calls.length,count,'denial never dispatches another request');
  }
});
test('HTTP403 invalidates a pending response before it can restore the previous private review',async()=>{
  const h=privacyConsole();await h.seed();
  const deferred=h.deferStatus();const pending=h.client.githubStatus();
  const settle=await deferred;const rejected=assert.rejects(pending,/LOCAL_OPERATOR_REQUIRED/);
  h.setDenied(403);await assert.rejects(h.client.chatCall({op:'chat_catalog'}),/LOCAL_OPERATOR_REQUIRED/);
  settle({operation_id:'d'.repeat(32),status:'GITHUB_PROPOSED',review:{private:h.marker}});
  await rejected;
  assert.equal(JSON.stringify(h.client.snapshot()).includes(h.marker),false);
  assert.equal(h.client.snapshot().phase,'UNKNOWN');
});
test('a late HTTP403 after LOCK cannot change the locked state or restore private review',async()=>{
  const h=privacyConsole();await h.seed();
  const deferred=h.deferStatus();const pending=h.client.githubStatus();
  const settle=await deferred;const rejected=assert.rejects(pending,/LOCAL_OPERATOR_REQUIRED/);
  h.client.close();settle({},403);await rejected;
  assert.equal(h.client.snapshot().phase,'LOCKED');
  assert.equal(JSON.stringify(h.client.snapshot()).includes(h.marker),false);
});
test('401 and 429 remain uncertain, never successful and never repeat a mutation automatically',async()=>{
  for(const status of [401,429]) {
    const h=privacyConsole();await h.seed();h.setDenied(status);
    await assert.rejects(h.client.githubApprove(),/UNKNOWN_READBACK_REQUIRED/);
    assert.equal(h.client.snapshot().phase,'UNKNOWN');
    assert.equal(h.client.snapshot().observed,false);
    const count=h.calls.length;await h.client.refresh({background:true});
    await assert.rejects(h.client.githubApprove());assert.equal(h.calls.length,count);
    assert.equal(h.calls.filter(x=>x.op==='github_write_approve').length,1);
  }
});
test('fresh console session with another request ID cannot inherit a denied console review',async()=>{
  const h=privacyConsole();await h.seed();h.setDenied(403);
  await assert.rejects(h.client.refresh(),/LOCAL_OPERATOR_REQUIRED/);
  const next=api.createDeviceConsole('U'.repeat(43),async(_,options)=>{
    const r=JSON.parse(options.body),data=r.op==='pairing_list'?{pending:[],devices:[]}:{data:{fresh:true},
      receipt:{schema:'aioa.native-tool-read-receipt.v1',effect:'READ',request_id:r.request_id,operation:r.operation}};
    return {ok:true,json:async()=>({ok:true,data})};
  });
  await next.refresh();
  await next.readTool('github.demo_context','f'.repeat(32));
  assert.equal(next.snapshot().toolResult.receipt.request_id,'f'.repeat(32));
  assert.equal(next.snapshot().toolProposal,null);
  assert.equal(next.snapshot().githubOperation,undefined);
  assert.equal(JSON.stringify(next.snapshot()).includes(h.marker),false);
  next.close();
});

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
test('remote code review requires exact owner action and cannot repeat an approval after lost ACK',async()=>{
  let id;let approvals=0;
  const {client,calls}=harness(v=>{
    if(v.op==='pairing_list')return {pending:[],devices:[]};
    if(v.op==='tool_proposal') {id=v.request_id;return {operation_id:id,status:'GITHUB_PROPOSED',
      execution_authorized:false,approval_available:true,review_digest:'a'.repeat(64),
      proposal:{operation:'code.commit_draft_pr',source_chat_request_id:v.chat_request_id}};}
    if(v.op==='github_write_approve'){approvals++;assert.equal(v.operation_id,id);
      assert.equal(v.review_digest,'a'.repeat(64));throw Error('lost ACK');}
    if(v.op==='github_write_status')return {operation_id:id,status:'GITHUB_UNKNOWN',approval_available:false};
    assert.fail('unexpected '+v.op);
  });
  await client.refresh();await client.proposeTool('b'.repeat(32));
  assert.equal(approvals,0);assert.equal(client.snapshot().githubWrite.status,'GITHUB_PROPOSED');
  await assert.rejects(client.githubApprove());await client.githubStatus();
  await assert.rejects(client.githubApprove());assert.equal(approvals,1);
  assert.equal(calls.filter(c=>JSON.parse(c.options.body).op==='github_write_reconcile').length,0);
});
test('remote approval is unavailable with Core blockers and result reads never send a write',async()=>{
  const {client,calls}=harness(v=>{
    if(v.op==='pairing_list')return {pending:[],devices:[]};
    if(v.op==='tool_proposal')return {operation_id:v.request_id,status:'GITHUB_PROPOSED',execution_authorized:false,
      approval_available:false,blockers:['BLOCKED_OWNER_LIABILITY_UNKNOWN'],review_digest:'a'.repeat(64),
      proposal:{operation:'code.commit_draft_pr',source_chat_request_id:v.chat_request_id}};
    if(v.op==='github_write_status')return {operation_id:v.operation_id,status:'GITHUB_UNKNOWN',approval_available:false};
    assert.fail('must not dispatch '+v.op);
  });
  await client.refresh();await client.proposeTool('b'.repeat(32));await assert.rejects(client.githubApprove());
  await client.githubStatus();
  assert.equal(calls.filter(c=>JSON.parse(c.options.body).op==='github_write_approve').length,0);
});
test('failed read polling recovers without blocking a separately authorized chat send',async()=>{
  let fail=false;
  const {client,calls}=harness(v=>{
    if(v.op==='pairing_list') {if(fail)throw Error('read timeout');return {pending:[],devices:[]};}
    if(v.op==='chat_send')return {state:'RUNNING'};
    assert.fail('unexpected dispatch');
  });
  await client.refresh();fail=true;
  await assert.rejects(client.refresh({background:true}));
  assert.equal(client.snapshot().observed,false);
  await client.chatCall({op:'chat_send'});
  assert.equal(client.snapshot().observed,false);
  fail=false;await client.refresh({background:true});
  assert.equal(client.snapshot().phase,'READY');
  assert.equal(client.snapshot().observed,true);
  assert.equal(calls.filter(x=>JSON.parse(x.options.body).op==='chat_send').length,1);
});
test('background recovery never resolves a lost mutation ACK or reopens rejected authentication',async()=>{
  const {client,calls}=harness(v=>{
    if(v.op==='pairing_list')return {pending:[pending],devices:[]};
    throw Error('lost approval ACK');
  });
  await client.refresh();await assert.rejects(client.approve(pending.request_id,pending.request_digest));
  await client.refresh({background:true});
  assert.equal(calls.length,2);assert.equal(client.snapshot().phase,'UNKNOWN');
  let requests=0;
  const denied=api.createDeviceConsole('T'.repeat(43),async()=>{requests++;return {ok:false,status:403};});
  await assert.rejects(denied.refresh());await denied.refresh({background:true});
  await assert.rejects(denied.chatCall({op:'chat_send'}),/LOCAL_OPERATOR_REQUIRED/);
  assert.equal(requests,1);
});
test('chat transport cannot enable spending authority or forward private approvals',async()=>{
  const {client,calls}=harness(()=>assert.fail('Private authority must never reach HTTP'));
  for(const op of ['chat_session_start','chat_approve','budget_approve','operator_renew'])
    await assert.rejects(client.chatCall({op}),/LOCAL_OPERATOR_REQUIRED/);
  assert.equal(calls.length,0);
});
test('session reads preserve uncertain pairing while session mutations require current console readback',async()=>{
  const {client,calls}=harness(value=>{
    if(value.op==='pairing_list')return {pending:[pending],devices:[]};
    if(value.op==='chat_session_status')return {state:'ACTIVE'};
    throw Error('lost pairing approval ACK');
  });
  await client.refresh();await assert.rejects(client.approve(pending.request_id,pending.request_digest));
  assert.equal((await client.chatCall({op:'chat_session_status'})).state,'ACTIVE');
  assert.equal(client.snapshot().phase,'UNKNOWN');
  for(const op of ['chat_send','chat_session_stop'])
    await assert.rejects(client.chatCall({op}),error=>error.message==='READBACK_REQUIRED' && error.notDispatched===true);
  assert.equal(calls.filter(x=>['chat_send','chat_session_stop'].includes(JSON.parse(x.options.body).op)).length,0);
});
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
  let consumed=false,phase='READY',poll,githubWrite=null,approvals=0;const refreshes=[];
  const client={snapshot:()=>({phase,observed:true,pending:[],devices:[device],busy:false,githubWrite,
    githubOperation:githubWrite?.operation_id}),refresh:async options=>{refreshes.push(options);},
    githubApprove:async()=>{approvals++;}};
  vm.runInNewContext(fs.readFileSync(require('node:path').join(__dirname,'../web/mobile_devices_dom.js'),'utf8'),{
    location:{pathname:'/devices',hash:'',search:''},history:{replaceState(){}},document,
    AIOAMobileDevices:{...api,createDeviceConsole:token=>{
      assert.equal(token,'T'.repeat(43));assert.equal(credential.value,'');
      consumed=true;return client;
    }},AIOAMobileChat:{mount:()=>assert.fail('status-only profile must not invoke chat APIs')},
    fetch:async()=>({ok:true,json:async()=>({ok:true,csrf_token:'T'.repeat(43),profile:'NATIVE_STATUS_READ_ONLY_V1'})}),
    window:{addEventListener(){}},setInterval(fn){poll=fn;},Date,JSON});
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
  // A stale read must reach the real transport's recovery decision; the DOM
  // must not permanently suppress polling just because presentation is UNKNOWN.
  document.visibilityState='visible';phase='UNKNOWN';poll();
  await new Promise(resolve=>setImmediate(resolve));
  assert.equal(refreshes.length,2);assert.equal(refreshes[1].background,true);
  phase='READY';githubWrite={status:'GITHUB_PROPOSED',operation_id:'d'.repeat(32),approval_available:true,
    review_digest:'a'.repeat(64),blockers:[],authorization:{status:'APP_CONFIGURED_SCOPE_CHECK_AT_START'}};
  get('cosmic-github-reviewed').listeners.change();
  assert.equal(get('cosmic-github-approve').disabled,true,'an available Core review is not owner consent');
  get('cosmic-github-reviewed').checked=true;get('cosmic-github-reviewed').listeners.change();
  assert.equal(get('cosmic-github-approve').disabled,false);
  get('cosmic-github-approve').listeners.click();await new Promise(resolve=>setImmediate(resolve));
  assert.equal(approvals,1);
  githubWrite={...githubWrite,review_digest:'b'.repeat(64),result:{receipt:{live_verified:true,
    github_url:'javascript:alert(1)',pr_url:'https://attacker.invalid/pull/1'}}};
  get('cosmic-github-reviewed').listeners.change();
  assert.equal(get('cosmic-github-reviewed').checked,false,'changed exact review invalidates the checkbox');
  assert.equal(get('cosmic-github-approve').disabled,true);
  assert.equal(get('cosmic-github-links').children.length,0,'untrusted receipt URLs never become links');
  githubWrite={...githubWrite,status:'GITHUB_UNKNOWN',owner_approval:true};
  get('cosmic-github-reviewed').listeners.change();
  assert.match(get('cosmic-github-write-state').textContent,/^UNKNOWN ·/,'a prior receipt must not hide current uncertainty');
  githubWrite={...githubWrite,status:'GITHUB_PROPOSED',blockers:['BLOCKED_OWNER_LIABILITY_UNKNOWN']};
  get('cosmic-github-reviewed').listeners.change();
  assert.match(get('cosmic-github-write-state').textContent,/^BLOCKED ·/);
  // A manually supplied legacy hash cannot supply a credential to a public GET.
  vm.runInNewContext(fs.readFileSync(require('node:path').join(__dirname,'../web/mobile_devices_dom.js'),'utf8'),{
    location:{pathname:'/devices',hash:'#operator='+'T'.repeat(43)},history:{replaceState(){}},
    document:{...document,getElementById:id=>id==='aioa-console-credential'?null:get(id)},
    AIOAMobileDevices:{...api,createDeviceConsole:()=>assert.fail('URL credential accepted')},
    fetch:async()=>({ok:false}),window:{addEventListener(){}},setInterval(){},Date,JSON});
});
test('owner LOCK and pagehide close mounted chat and erase the proposal without accepting a late bootstrap',async()=>{
  const vm=require('node:vm');
  for(const action of ['lock','pagehide','late-bootstrap']) {
    class Element {
      constructor(){this.children=[];this.dataset={};this.listeners={};this.textContent='';this.value='';this.classList={add(){}};}
      append(child){this.children.push(child);} replaceChildren(){this.children=[];}
      addEventListener(event,fn){this.listeners[event]=fn;} getContext(){return {clearRect(){}};}
    }
    const ids=new Map(),get=id=>{if(!ids.has(id))ids.set(id,new Element());return ids.get(id);};
    const events={};let phase='READY',mounted=0,closed=0,bootstrap;
    const document={body:new Element(),getElementById:get,createElement:()=>new Element()};
    const client={snapshot:()=>({phase,observed:true,pending:[],devices:[],busy:false,
      toolProposal:phase==='LOCKED'?null:{private:'proposal bytes'}}),refresh:async()=>{},close:()=>{phase='LOCKED';}};
    vm.runInNewContext(fs.readFileSync(require('node:path').join(__dirname,'../web/mobile_devices_dom.js'),'utf8'),{
      location:{pathname:'/devices',hash:'',search:''},history:{replaceState(){}},document,
      AIOAMobileDevices:{...api,createDeviceConsole:()=>client},
      AIOAMobileChat:{mount:()=>{mounted++;return {close:()=>{closed++;}};}},
      fetch:()=>new Promise(resolve=>{bootstrap=()=>resolve({ok:true,json:async()=>({ok:true,
        csrf_token:'T'.repeat(43),profile:'NATIVE_ADVISORY_CHAT_V1'})});}),
      window:{addEventListener:(name,fn)=>{events[name]=fn;}},setInterval(){},Date,JSON});
    if(action==='late-bootstrap')events.pagehide();
    bootstrap();await new Promise(resolve=>setImmediate(resolve));
    if(action==='late-bootstrap'){assert.equal(mounted,0);continue;}
    assert.equal(mounted,1);assert.match(get('cosmic-proposal-result').textContent,/proposal bytes/);
    get('cosmic-proposal-chat').value='private request';
    if(action==='lock')get('devices-lock').listeners.click();else events.pagehide();
    assert.ok(closed>0);assert.equal(phase,'LOCKED');
    assert.equal(get('cosmic-proposal-chat').value,'');
    assert.equal(get('cosmic-proposal-result').textContent,'No proposal selected.');
  }
});
test('local advisory preview uses existing console and cannot claim execution or send permission',async()=>{
  const calls=[];
  const client=api.createDeviceConsole('a'.repeat(43),async(url,options)=>{
    const request=JSON.parse(options.body);calls.push(request);
    return {ok:true,json:async()=>({ok:true,data:request.op==='pairing_list'?{pending:[],devices:[]}:{
      data:{status:'DRAFT_PREVIEW_ONLY'},receipt:{schema:'aioa.native-advisory-receipt.v1',
        request_id:request.request_id,operation:request.op,effect:'ADVISORY_PREVIEW',
        execution_authorized:false,provider_calls:0,external_calls:0,automatic_retry:false}}})};
  });
  await client.refresh();await client.preview('mail_preview',{subject:'Literal <script> text',body_text:'Local preview'},'b'.repeat(32));
  assert.equal(client.snapshot().advisoryPreview.receipt.execution_authorized,false);
  const count=calls.length;await assert.rejects(client.preview('mail_send',{},'c'.repeat(32)));
  assert.equal(calls.length,count);assert.deepEqual(calls.map(x=>x.op),['pairing_list','mail_preview']);
});
test('ordinary preview input bounds do not dispatch or invalidate the owner panel',async()=>{
  const {client,calls}=harness(()=>({pending:[],devices:[]}));await client.refresh();const count=calls.length;
  for(const [op,payload] of [['command_advice',{command:''}],['command_advice',{command:'ą'.repeat(1001)}],
      ['mail_preview',{body_text:'ą'.repeat(4097)}],['mail_preview',{body_text:'ok',subject:'x'.repeat(12000)}],
      ['critic_transform_preview',{prompt:''}],['critic_transform_preview',{prompt:'ą'.repeat(4001)}]]) {
    await assert.rejects(client.preview(op,payload,'a'.repeat(32)),/PREVIEW_INPUT_LIMIT/);
    assert.equal(client.snapshot().phase,'READY');assert.equal(client.snapshot().observed,true);
  }
  assert.equal(calls.length,count);
});
function cptReply(request) {
  const crypto=require('node:crypto');
  const canonical=value=>JSON.stringify(Object.fromEntries(Object.keys(value).sort().map(k=>[k,value[k]])));
  const sha=text=>crypto.createHash('sha256').update(text).digest('hex');
  const text='Literal <script> draft';
  const data={status:'CPT_DRAFT_PREVIEW_ONLY',input_sha256:sha(request.payload.prompt),
    execution_authorized:false,human_review_required:true,template_version:'synthetic-v1',transformation_version:'synthetic-v1',
    review_input_sha256:sha(request.payload.prompt),transformed_prompt_sha256:sha(text),transformed_prompt_bytes:Buffer.byteLength(text)};
  const receipt={schema:'aioa.native-advisory-receipt.v1',request_id:request.request_id,operation:request.op,
    request_digest:'a'.repeat(64),data_sha256:sha(canonical(data)),source_sha:'a'.repeat(40),capsule_digest:'b'.repeat(64),
    core_instance_id:'c'.repeat(64),observed_at:100,effect:'ADVISORY_PREVIEW',execution_authorized:false,
    provider_calls:0,external_calls:0,automatic_retry:false};
  const {privateKey}=crypto.generateKeyPairSync('ec',{namedCurve:'prime256v1'});
  return {data,receipt,preview:{transformed_prompt:text},signature:crypto.sign('sha256',Buffer.from(canonical(receipt)),privateKey).toString('base64')};
}
test('critical previews are explicitly repeatable without chat send or automatic follow-up',async()=>{
  const {client,calls}=harness(v=>v.op==='pairing_list'?{pending:[],devices:[]}:cptReply(v));
  await client.refresh();
  await client.preview('critic_transform_preview',{prompt:'First prompt'},'b'.repeat(32));
  await client.preview('critic_transform_preview',{prompt:'Second prompt'},'c'.repeat(32));
  assert.equal(client.snapshot().advisoryPreview.preview.transformed_prompt,'Literal <script> draft');
  assert.deepEqual(calls.map(c=>JSON.parse(c.options.body).op),['pairing_list','critic_transform_preview','critic_transform_preview']);
  client.close();assert.equal(client.snapshot().advisoryPreview,undefined);
});
test('critical preview refuses changed text, metadata, unknown status and missing receipt fields',async()=>{
  const mutations=[r=>{r.preview.transformed_prompt='Altered text';},r=>{r.data.transformed_prompt_bytes++;},
    r=>{r.data.template_version='changed';},r=>{delete r.signature;},r=>{delete r.receipt.data_sha256;},
    r=>{r.data.status='CANONICAL';},r=>{r.data.status='INPUT_REJECTED';},r=>{r.data.execution_authorized=true;}];
  for(const mutate of mutations) {
    const {client,calls}=harness(v=>{
      if(v.op==='pairing_list')return {pending:[],devices:[]};
      const reply=cptReply(v);mutate(reply);return reply;
    });
    await client.refresh();
    await assert.rejects(client.preview('critic_transform_preview',{prompt:'Review'},'b'.repeat(32)));
    assert.equal(client.snapshot().advisoryPreview,undefined);
    assert.equal(calls.length,2,'no automatic retry after malformed readback');
  }
});
test('locking during asynchronous preview validation cannot restore private text',async()=>{
  const crypto=require('node:crypto').webcrypto;
  const previous=Object.getOwnPropertyDescriptor(globalThis,'crypto');
  let release,entered;
  const blocked=new Promise(resolve=>{release=resolve;});
  const started=new Promise(resolve=>{entered=resolve;});
  Object.defineProperty(globalThis,'crypto',{configurable:true,value:{subtle:{digest:async(...args)=>{
    entered();await blocked;return crypto.subtle.digest(...args);
  }}}});
  try {
    const {client}=harness(v=>v.op==='pairing_list'?{pending:[],devices:[]}:cptReply(v));
    await client.refresh();
    const pending=client.preview('critic_transform_preview',{prompt:'Private'},'b'.repeat(32));
    await started;client.close();release();
    await assert.rejects(pending,/LOCAL_OPERATOR_REQUIRED/);
    assert.equal(client.snapshot().phase,'LOCKED');assert.equal(client.snapshot().advisoryPreview,undefined);
  } finally {
    if(previous)Object.defineProperty(globalThis,'crypto',previous);else delete globalThis.crypto;
  }
});
