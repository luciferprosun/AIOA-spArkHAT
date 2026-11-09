/* P06 preparation only: UNAPPLIED / NOT RUN while Wave A source is frozen. */
const test = require('node:test');
const assert = require('node:assert/strict');
const api = require('../web/agent_mission.js');

function view(task, state='QUEUED') {
  return {task_id:task,run_id:'run-'+task,task_digest:'a'.repeat(64),state,
    capsule_digest:'b'.repeat(64),authority:'NONE',effects_registered:false};
}
function deferred() {
  let resolve,reject;
  const promise=new Promise((yes,no)=>{resolve=yes;reject=no;});
  return {promise,resolve,reject};
}
function client(fetchJSON) {
  const renders=[],errors=[];
  const value=api.createCodingClient({fetchJSON,render:v=>renders.push(v),error:e=>errors.push(e)});
  return {value,renders,errors};
}

test('latest selected task wins when an older GET finishes afterward',async()=>{
  const older=deferred();
  const c=client(path=>path.endsWith('/task-a')?older.promise:Promise.resolve(view('task-b')));
  const first=c.value.select('task-a');
  await c.value.select('task-b');
  older.resolve(view('task-a','APPROVED'));
  await first;
  assert.deepEqual(c.renders.map(v=>v.task_id),['task-b']);
});

test('a refresh for a previous task cannot replace the new selection',async()=>{
  const older=deferred();
  const c=client(path=>path.endsWith('/task-a')?older.promise:Promise.resolve(view('task-b')));
  c.value.adopt(view('task-a','RUNNING'));
  const refresh=c.value.refresh();
  await c.value.select('task-b');
  older.resolve(view('task-a','VERIFIED'));
  await refresh;
  assert.deepEqual(c.renders.map(v=>v.task_id),['task-a','task-b']);
});

test('late mutation ACK does not adopt a different task or repeat the POST',async()=>{
  const ack=deferred();let posts=0;
  const c=client((_path,options={})=>{
    if(options.method==='POST'){posts++;return ack.promise;}
    throw Error('No automatic read for an obsolete selection');
  });
  c.value.adopt(view('task-a'));
  const start=c.value.start();
  c.value.adopt(view('task-b'));
  ack.resolve(view('task-a','RUNNING'));
  await start;
  assert.equal(posts,1);
  assert.deepEqual(c.renders.map(v=>v.task_id),['task-a','task-b']);
});

test('same-task out-of-order refresh cannot restore an older approval',async()=>{
  const first=deferred(),second=deferred();let gets=0;
  const c=client(()=>++gets===1?first.promise:second.promise);
  c.value.adopt(view('task-a','RUNNING'));
  const one=c.value.refresh(),two=c.value.refresh();
  second.resolve(view('task-a','VERIFIED'));await two;
  first.resolve(view('task-a','APPROVED'));await one;
  assert.deepEqual(c.renders.map(v=>v.state),['RUNNING','VERIFIED']);
});

test('close invalidates pending responses and sends no STOP or other effect',async()=>{
  const pending=deferred();let requests=0;
  const c=client(()=>{requests++;return pending.promise;});
  assert.equal(typeof c.value.close,'function','Coding client has no session-close boundary');
  const select=c.value.select('task-a');
  c.value.close();
  pending.resolve(view('task-a','APPROVED'));await select;
  assert.equal(requests,1);
  assert.deepEqual(c.renders,[]);
  assert.throws(()=>c.value.adopt(view('task-b')));
  await assert.rejects(c.value.select('task-b'));
  await assert.rejects(c.value.start());
  await assert.rejects(c.value.stop());
  assert.equal(requests,1);
});

test('lost ACK after close cannot launch a readback or restore private data',async()=>{
  const pending=deferred();let requests=0;
  const c=client(()=>{requests++;return pending.promise;});
  assert.equal(typeof c.value.close,'function','Coding client has no session-close boundary');
  c.value.adopt(view('task-a'));
  const start=c.value.start();
  c.value.close();
  pending.reject(Error('ACK lost'));
  await start;
  assert.equal(requests,1);
  assert.deepEqual(c.renders.map(v=>v.task_id),['task-a']);
  assert.deepEqual(c.errors,[],'Obsolete session must not change the current UI error');
});

test('panel pagehide clears private task evidence and exact approval selection',async()=>{
  const previousDocument=global.document,previousAdd=global.addEventListener,previousRemove=global.removeEventListener;
  const nodes=new Map(),events=new Map();
  global.document={querySelector:id=>{
    if(!nodes.has(id))nodes.set(id,{value:'task-a',checked:false,disabled:false,textContent:''});
    return nodes.get(id);
  }};
  global.addEventListener=(name,callback)=>events.set(name,callback);
  global.removeEventListener=(name,callback)=>{if(events.get(name)===callback)events.delete(name);};
  try {
    api.mountCodingPanel(async()=>({...view('task-a','REVIEW_REQUIRED'),
      effect_preview:{operation_digest:'c'.repeat(64),capsule_digest:'b'.repeat(64)}}));
    await nodes.get('#coding-select').onclick();
    nodes.get('#coding-confirm').checked=true;
    nodes.get('#coding-confirm').onchange();
    assert.equal(nodes.get('#coding-approve').disabled,false);
    assert.equal(typeof events.get('pagehide'),'function','Pagehide is not bound to the existing coding panel');
    events.get('pagehide')();
    assert.equal(nodes.get('#coding-evidence').textContent,'');
    assert.equal(nodes.get('#coding-confirm').checked,false);
    for(const action of ['create','select','start','stop','review','approve','apply','deny','reconcile','refresh']){
      assert.equal(nodes.get('#coding-'+action).disabled,true,action+' remained active after session close');
    }
  } finally {
    if(previousDocument===undefined)delete global.document;else global.document=previousDocument;
    if(previousAdd===undefined)delete global.addEventListener;else global.addEventListener=previousAdd;
    if(previousRemove===undefined)delete global.removeEventListener;else global.removeEventListener=previousRemove;
  }
});

test('obsolete GET rejection cannot replace the new task with an old UI error',async()=>{
  const old=deferred();
  const c=client(path=>path.endsWith('/task-a')?old.promise:Promise.resolve(view('task-b')));
  const pending=c.value.select('task-a');
  await c.value.select('task-b');
  old.reject(Error('Old task read failed'));
  await assert.doesNotReject(pending);
  assert.deepEqual(c.renders.map(v=>v.task_id),['task-b']);
  assert.deepEqual(c.errors,[]);
});

test('unauthorized GET closes the client without another request or stale adoption',async()=>{
  let calls=0;const denied=Object.assign(Error('Expired session'),{status:401});
  const c=client(()=>{calls++;return Promise.reject(denied);});
  c.value.adopt(view('task-a','APPROVED'));
  await c.value.refresh();
  assert.throws(()=>c.value.adopt(view('task-b')));
  await assert.rejects(c.value.select('task-b'));
  assert.equal(calls,1);
  assert.deepEqual(c.errors,[]);
});

test('unauthorized POST locks rather than launching an automatic readback',async()=>{
  let calls=0;const denied=Object.assign(Error('Authorization required'),{status:403});
  const c=client(()=>{calls++;return Promise.reject(denied);});
  c.value.adopt(view('task-a'));
  await c.value.start();
  await assert.rejects(c.value.start());
  assert.throws(()=>c.value.adopt(view('task-b')));
  assert.equal(calls,1);
  assert.deepEqual(c.errors,[]);
});

test('authorization loss clears mounted private evidence and exact approval immediately',async()=>{
  const previousDocument=global.document;const nodes=new Map();let calls=0;
  global.document={querySelector:id=>{
    if(!nodes.has(id))nodes.set(id,{value:'task-a',checked:false,disabled:false,textContent:''});
    return nodes.get(id);
  }};
  try {
    api.mountCodingPanel(async()=>{
      if(++calls===1)return {...view('task-a','REVIEW_REQUIRED'),
        effect_preview:{operation_digest:'c'.repeat(64),capsule_digest:'b'.repeat(64)}};
      throw Object.assign(Error('Expired session'),{status:401});
    });
    await nodes.get('#coding-select').onclick();
    nodes.get('#coding-confirm').checked=true;nodes.get('#coding-confirm').onchange();
    assert.equal(nodes.get('#coding-approve').disabled,false);
    await nodes.get('#coding-refresh').onclick();
    assert.equal(nodes.get('#coding-evidence').textContent,'');
    assert.equal(nodes.get('#coding-confirm').checked,false);
    for(const action of ['create','select','start','stop','review','approve','apply','deny','reconcile','refresh']){
      assert.equal(nodes.get('#coding-'+action).disabled,true);
    }
    assert.equal(calls,2);
  } finally {
    if(previousDocument===undefined)delete global.document;else global.document=previousDocument;
  }
});


test('transient states from the canonical coding controller remain observable',()=>{
  const c=client(async()=>{});
  for(const state of ['PLANNED','PATCH_READY','TESTING'])c.value.adopt(view('task-a',state));
  assert.deepEqual(c.renders.map(v=>v.state),['PLANNED','PATCH_READY','TESTING']);
});

test('STOP remains available for every transient active coding state',async()=>{
  for(const state of ['PLANNED','PATCH_READY','TESTING']){
    let posts=0;
    const c=client(async(path,options)=>{
      assert.equal(path,'/api/agent/coding/stop');assert.equal(options.method,'POST');posts++;
      return view('task-a','CANCELLED');
    });
    c.value.adopt(view('task-a',state));await c.value.stop();assert.equal(posts,1);
    assert.equal(c.renders.at(-1).state,'CANCELLED');
  }
});

test('mounted panel enables STOP when Core reports a transient active state',async()=>{
  const previousDocument=global.document;const nodes=new Map();let state='PLANNED';
  global.document={querySelector:id=>{
    if(!nodes.has(id))nodes.set(id,{value:'task-a',checked:false,disabled:false,textContent:''});
    return nodes.get(id);
  }};
  try {
    const panel=api.mountCodingPanel(async()=>view('task-a',state));
    for(state of ['PLANNED','PATCH_READY','TESTING']){
      await nodes.get('#coding-select').onclick();
      assert.equal(nodes.get('#coding-stop').disabled,false,state);
      assert.equal(nodes.get('#coding-approve').disabled,true);
      assert.equal(nodes.get('#coding-apply').disabled,true);
    }
    panel?.close();
  } finally {
    if(previousDocument===undefined)delete global.document;else global.document=previousDocument;
  }
});
