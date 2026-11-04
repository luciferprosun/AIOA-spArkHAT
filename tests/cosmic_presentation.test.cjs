const test = require('node:test');
const assert = require('node:assert/strict');
const api = require('../web/mobile_devices.js');

test('Cosmic overview never turns remembered devices into an online claim', () => {
  assert.equal(typeof api.presentation, 'function', 'Cosmic overview presentation is missing');
  const view = api.presentation({phase:'READY',observed:true,
    pending:[{state:'COMPLETED'},{state:'PENDING'}],
    devices:[{revoked:false,active_sessions:0},{revoked:true,active_sessions:2}]});
  assert.deepEqual(view,{operatorReady:true,trustedDevices:1,pendingApprovals:1,activeSessions:2});
  assert.equal('phoneOnline' in view,false);
});

test('loss of operator readback hides positive counts while keeping review records', () => {
  assert.equal(typeof api.presentation, 'function', 'Cosmic overview presentation is missing');
  const record={phase:'UNKNOWN',observed:false,pending:[{state:'PENDING'}],
    devices:[{revoked:false,active_sessions:1}]};
  assert.deepEqual(api.presentation(record),{operatorReady:false,trustedDevices:null,pendingApprovals:null,activeSessions:null});
  assert.equal(record.devices.length,1);
  for (const value of [null,{phase:'LOCKED',observed:true}, {phase:'READY',observed:false}]) {
    assert.equal(api.presentation(value).operatorReady,false);
  }
});

test('expired owner session invalidates presentation until a successful explicit readback',async()=>{
  let denied=false;
  const client=api.createDeviceConsole('T'.repeat(43),async()=>({ok:!denied,status:denied?403:200,
    json:async()=>({ok:true,data:{pending:[],devices:[{revoked:false,active_sessions:1}]}})}));
  assert.equal(typeof api.presentation,'function','Cosmic overview presentation is missing');
  assert.equal(api.presentation(client.snapshot()).operatorReady,false);
  await client.refresh();assert.equal(api.presentation(client.snapshot()).trustedDevices,1);
  denied=true;await assert.rejects(client.refresh(),/LOCAL_OPERATOR_REQUIRED/);
  assert.equal(api.presentation(client.snapshot()).trustedDevices,null);
  denied=false;await client.refresh();assert.equal(api.presentation(client.snapshot()).trustedDevices,1);
  client.close();assert.equal(api.presentation(client.snapshot()).operatorReady,false);
});
