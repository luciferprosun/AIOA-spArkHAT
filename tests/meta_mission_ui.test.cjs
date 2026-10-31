const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const file = path.join(__dirname, '../web/meta_mission.js');

function api() {
  assert.ok(fs.existsSync(file), 'Mission Control client missing');
  return require(file);
}
const preview = {task_id:'meta-fixture', preview_digest:'a'.repeat(64), state:'PREVIEWED', live_verified:false};
const done = {...preview, state:'OFFLINE_FIXTURE', result:{status:'OFFLINE_LINKED_UNVERIFIED'}};

test('preview/run/readback use one POST and keep mock result OFFLINE', async () => {
  const {createMissionClient, providerLabel} = api(); const calls=[]; const renders=[];
  const client=createMissionClient({fetchJSON:async (url,options={})=>{
    calls.push([url,options.method||'GET']);
    return url.endsWith('/preview')?preview:url.endsWith('/run')?{...preview,state:'RUNNING'}:done;
  },render:value=>renders.push(value),error:()=>{},delay:async()=>{}});
  await client.preview({instruction:'Read'}); await client.run();
  assert.equal(calls.filter(([,method])=>method==='POST').length,2);
  assert.equal(renders.at(-1).state,'OFFLINE_FIXTURE');
  assert.equal(providerLabel(done),'Muse Spark · OFFLINE FIXTURE');
  assert.notEqual(providerLabel({...done,live_verified:true}),'Muse Spark · LIVE VERIFIED');
  assert.equal(providerLabel({...preview,state:'LIVE_PENDING_AUTHORIZATION'}),'Muse Spark · LIVE BLOCKED');
});

test('lost run ACK triggers GET readback, never another POST', async () => {
  const {createMissionClient}=api();const calls=[];
  const client=createMissionClient({fetchJSON:async(url,options={})=>{
    calls.push([url,options.method||'GET']);
    if(url.endsWith('/preview'))return preview;
    if(url.endsWith('/run'))throw new Error('lost ACK');
    return done;
  },render:()=>{},error:()=>{},delay:async()=>{}});
  await client.preview({instruction:'Read'});await client.run();
  assert.equal(calls.filter(([url])=>url.endsWith('/run')).length,1);
  assert.equal(calls.at(-1)[1],'GET');
  await assert.rejects(()=>client.run());
});

test('STOP sends only its task and invalidated preview cannot run', async () => {
  const {createMissionClient}=api();const calls=[];
  const client=createMissionClient({fetchJSON:async(url,options={})=>{
    calls.push([url,options]);return url.endsWith('/stop')?{...preview,state:'STOPPED'}:preview;
  },render:()=>{},error:()=>{},delay:async()=>{}});
  await client.preview({instruction:'Read'});client.invalidate();
  await assert.rejects(()=>client.run()); await client.stop();
  assert.deepEqual(JSON.parse(calls.at(-1)[1].body),{task_id:'meta-fixture'});
  assert.equal(calls.at(-1)[1].headers['X-AIOA-Intent'],'meta-stop-v1');
});

test('page reload can adopt server evidence and STOP without re-running', async () => {
  const {createMissionClient}=api();const calls=[];
  const client=createMissionClient({fetchJSON:async(url,options)=>{
    calls.push([url,options]);return {...preview,state:'STOPPED'};
  },render:()=>{},error:()=>{},delay:async()=>{}});
  assert.equal(typeof client.adopt,'function');
  client.adopt({...preview,state:'RUNNING'});
  await assert.rejects(()=>client.run());await client.stop();
  assert.equal(calls.length,1);assert.equal(calls[0][0],'/api/meta/stop');
});

test('native-bound preview sends one approved intent and never fixture execution', async () => {
  const {createMissionClient}=api();const calls=[];
  const bound={...preview,state:'LIVE_PENDING_AUTHORIZATION',mode:'LIVE',native_spend_binding:'BOUND'};
  const client=createMissionClient({fetchJSON:async(url,options={})=>{
    calls.push([url,options]);return {...bound,state:'BLOCKED',error:'CHROME_LIVE_BLOCKED_CONTAINMENT'};
  },render:()=>{},error:()=>{},delay:async()=>{}});
  client.adopt(bound);await client.run();
  assert.equal(calls[0][1].headers['X-AIOA-Intent'],'meta-run-approved-v1');
  assert.deepEqual(JSON.parse(calls[0][1].body),{task_id:bound.task_id,preview_digest:bound.preview_digest});
  await assert.rejects(()=>client.run());
});

test('unbound LIVE and uncertain states are never labelled fixture or allowed to run', async () => {
  const {providerLabel,createMissionClient}=api();
  assert.equal(providerLabel({state:'UNKNOWN',mode:'LIVE'}),'Muse Spark · UNKNOWN');
  assert.equal(providerLabel({state:'BLOCKED',mode:'LIVE'}),'Muse Spark · LIVE BLOCKED');
  const client=createMissionClient({fetchJSON:()=>{throw Error('must not send');},render:()=>{},error:()=>{}});
  client.adopt({...preview,state:'LIVE_PENDING_AUTHORIZATION',mode:'LIVE'});
  await assert.rejects(()=>client.run());
});
