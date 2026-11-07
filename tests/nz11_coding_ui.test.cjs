const test=require('node:test');const assert=require('node:assert/strict');
const api=require('../web/agent_mission.js');
function view(state='QUEUED'){return {task_id:'task-1',run_id:'run-1',task_digest:'a'.repeat(64),state,
  capsule_digest:'b'.repeat(64),authority:'NONE',effects_registered:false};}
function client(fetchJSON){assert.equal(typeof api.createCodingClient,'function','coding panel controller missing');
  return api.createCodingClient({fetchJSON,render:()=>{},error:()=>{}});}
test('coding approval and apply are separate exact actions; ACK loss never repeats POST',async()=>{
  let posts=0;const c=client(async(path,options={})=>{
    if(options.method==='POST'){posts++;throw Error('lost ACK');}
    return view('UNKNOWN');});
  const p={...view('REVIEW_REQUIRED'),effect_preview:{operation_digest:'c'.repeat(64),capsule_digest:'b'.repeat(64)}};
  c.adopt(p);await assert.rejects(c.approve('d'.repeat(64)));assert.equal(posts,0);
  await c.approve('c'.repeat(64));assert.equal(posts,1);
  await assert.rejects(c.approve('c'.repeat(64)));assert.equal(posts,1);
});
test('UNKNOWN has readback but cannot execute; STOP uses the admitted task identity',async()=>{
  const calls=[];const c=client(async(path,options={})=>{calls.push([path,options.method]);return view('UNKNOWN');});
  c.adopt(view('UNKNOWN'));await assert.rejects(c.apply('c'.repeat(64)));assert.equal(calls.length,0);
  await c.reconcile();assert.deepEqual(calls,[['/api/agent/coding/reconcile','POST']]);
  c.adopt(view('RUNNING'));await c.stop();assert.equal(calls[1][0],'/api/agent/coding/stop');
});
test('cross-task replies and model-supplied authority cannot be adopted',()=>{
  const c=client(async()=>{});assert.throws(()=>c.adopt({...view(),authority:'OWNER'}));
  c.adopt(view());assert.throws(()=>c.adopt({...view(),state:'LIVE_VERIFIED'}));
});
