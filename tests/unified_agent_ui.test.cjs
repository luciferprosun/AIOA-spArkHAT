const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
function api() {
  assert.ok(fs.existsSync(require('node:path').join(__dirname,'../web/agent_mission.js')), 'unified UI controller missing');
  return require('../web/agent_mission.js');
}
function pending() { return {schema:'aioa.agent.mission.v2', task_id:'agent-'+'c'.repeat(32), state:'AGENT_PENDING',
  mode:'OFFLINE_FIXTURE', provider_id:'meta_model_api',model_id:'muse-spark-1.3', source_sha:'1'.repeat(40),
  capsule_digest:'a'.repeat(64),task_digest:'b'.repeat(64),preview_digest:'d'.repeat(64),
  operation:{operation_class:'SANDBOX_EXEC'},receipt:null,model_invoked:false}; }

test('approval ACK loss performs GET readback and never sends a second operation', async () => {
  const {createAgentClient}=api();let posts=0;const p=pending();
  const client=createAgentClient({fetchJSON:async (path,options={}) => {
    if (options.method==='POST') { posts++;throw new Error('lost ACK'); }
    return {...p,state:'AGENT_COMPLETED',receipt:{local_readback_verified:true}};
  },render:()=>{},error:()=>{},delay:async()=>{}});
  client.adopt(p);
  const done=await client.approve(p.preview_digest);
  assert.equal(done.state,'AGENT_COMPLETED');assert.equal(posts,1);
  await assert.rejects(client.approve(p.preview_digest));assert.equal(posts,1);
});
test('changed preview digest and unsupported provider never dispatch', async () => {
  const {createAgentClient}=api();let dispatched=false;
  const client=createAgentClient({fetchJSON:async()=>{dispatched=true;},render:()=>{},error:()=>{}});
  client.adopt(pending());
  await assert.rejects(client.approve('f'.repeat(64)));assert.equal(dispatched,false);
  assert.throws(()=>client.adopt({...pending(),provider_id:'fake-live'}));
});
test('UNKNOWN remains UNKNOWN on readback and cannot be approved again', async () => {
  const {createAgentClient}=api();const p={...pending(),state:'AGENT_UNKNOWN'};let posts=0;
  const client=createAgentClient({fetchJSON:async(path,options={})=>{if(options.method==='POST')posts++;return p;},
    render:()=>{},error:()=>{},delay:async()=>{}});
  client.adopt(p);assert.equal((await client.refresh()).state,'AGENT_UNKNOWN');
  await assert.rejects(client.approve(p.preview_digest));assert.equal(posts,0);
});
test('local verified effects never become model LIVE verification', () => {
  const {presentation}=api();const view=presentation({...pending(),state:'AGENT_COMPLETED',
    receipt:{local_readback_verified:true},model_invoked:false});
  assert.match(view.effect,/readback verified/i);assert.match(view.model,/not invoked/i);
  assert.doesNotMatch(view.model,/LIVE VERIFIED/);
});
test('UNKNOWN reconciliation requests readback without sending a run', async () => {
  const {createAgentClient}=api();const paths=[];
  const client=createAgentClient({fetchJSON:async(path,options={})=>{
    paths.push(path);return {...pending(),state:'AGENT_COMPLETED',receipt:{local_readback_verified:true}};
  },render:()=>{},error:()=>{}});
  client.adopt({...pending(),state:'AGENT_UNKNOWN'});
  assert.equal(typeof client.reconcile,'function','independent readback control missing');
  assert.equal((await client.reconcile()).state,'AGENT_COMPLETED');
  assert.deepEqual(paths,['/api/agent/reconcile']);
});
