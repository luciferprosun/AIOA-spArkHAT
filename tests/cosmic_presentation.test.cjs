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

test('expired owner session stays locked until a fresh owner session performs readback',async()=>{
  let denied=false;
  let calls=0;
  const fetcher=async()=>{calls++;return {ok:!denied,status:denied?403:200,
    json:async()=>({ok:true,data:{pending:[],devices:[{revoked:false,active_sessions:1}]}})};};
  const client=api.createDeviceConsole('T'.repeat(43),fetcher);
  assert.equal(typeof api.presentation,'function','Cosmic overview presentation is missing');
  assert.equal(api.presentation(client.snapshot()).operatorReady,false);
  await client.refresh();assert.equal(api.presentation(client.snapshot()).trustedDevices,1);
  denied=true;await assert.rejects(client.refresh(),/LOCAL_OPERATOR_REQUIRED/);
  assert.equal(api.presentation(client.snapshot()).trustedDevices,null);
  denied=false;
  const callsAtLock=calls;
  await assert.rejects(client.refresh(),/LOCAL_OPERATOR_REQUIRED/);
  assert.equal(calls,callsAtLock,'locked client must not issue a new request');
  assert.equal(api.presentation(client.snapshot()).trustedDevices,null);
  const renewed=api.createDeviceConsole('U'.repeat(43),fetcher);
  assert.equal(api.presentation(renewed.snapshot()).trustedDevices,null);
  await renewed.refresh();assert.equal(api.presentation(renewed.snapshot()).trustedDevices,1);
  renewed.close();
  client.close();assert.equal(api.presentation(client.snapshot()).operatorReady,false);
});
