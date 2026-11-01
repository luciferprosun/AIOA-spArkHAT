// Android SOURCE contract checks; these do not execute Compose or certify a phone.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const dir = path.join(__dirname, '../clients/android/app/src/main/java/eu/sparkhat/aioa/companion');
const read = name => fs.readFileSync(path.join(dir, name), 'utf8');

test('SOURCE: small-screen UI scrolls with insets and has no mobile Run approval', () => {
  const ui = read('MainActivity.kt');
  for (const text of ['verticalScroll(rememberScrollState())','safeDrawingPadding()','imePadding()',
    'Evidence','STOP własnej misji','Billing Unverified','Not yet available']) assert.ok(ui.includes(text));
  assert.ok(!/onClick\s*=\s*model::(?:run|approve)/.test(ui));
});
test('SOURCE: process death does not recover token or automatically resend a proposal', () => {
  const vm = read('MissionViewModel.kt'), client = read('MobileClient.kt');
  assert.ok(vm.indexOf('putString("pending_proposal"') < vm.indexOf('client.preview('));
  assert.ok(vm.includes('generation.generation == epoch'));
  assert.ok(vm.includes('generation.invalidate("STALE")'));
  assert.ok(client.includes('retryOnConnectionFailure(false)'));
  assert.ok(!/putString\("(?:token|code|instruction)"/.test(vm));
});
test('SOURCE: UNKNOWN is not a stoppable success and TLS fixture pairing is blocked', () => {
  const freshness = read('Freshness.kt'), client = read('MobileClient.kt');
  assert.ok(freshness.includes('setOf("PREVIEWED","RUNNING","LIVE_PENDING_AUTHORIZATION")'));
  assert.ok(client.includes('Wire.text(caps,"profile") != "OFFLINE_FIXTURE"'));
  assert.ok(client.includes('"REMOTE_DEPLOYMENT_BLOCKED"'));
});
