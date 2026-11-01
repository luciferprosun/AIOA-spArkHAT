/* Exact preview approval, GET-only readback and STOP reuse AIOA/Nebius UX ideas.
 * This controller belongs to the existing web UI; it never grants authority. */
(function (root) {
  'use strict';
  function providerLabel(value) {
    if (value && value.state === 'UNKNOWN') return 'Muse Spark · UNKNOWN';
    if (value && value.state === 'LIVE_PENDING_AUTHORIZATION') return 'Muse Spark · LIVE BLOCKED';
    if (value && value.mode === 'LIVE' && value.state !== 'LIVE_VERIFIED') return 'Muse Spark · LIVE BLOCKED';
    return value && value.state === 'LIVE_VERIFIED' && value.live_verified === true
      ? 'Muse Spark · LIVE VERIFIED' : 'Muse Spark · OFFLINE FIXTURE';
  }
  function runnable(value) {
    return value && (value.state === 'PREVIEWED' || value.state === 'LIVE_PENDING_AUTHORIZATION'
      && value.mode === 'LIVE' && value.native_spend_binding === 'BOUND');
  }
  function missionText(value) {
    const live=value.mode==='LIVE';
    const boundary=live
      ? 'Native Meta model request governed by Core. Charges require exact owner approval; browser READ requires separate authority and containment.'
      : 'OFFLINE FIXTURE: synthetic Meta response and browser driver, real Core gates. No paid calls or real public Chromium READ.';
    const approval=live ? value.native_spend_binding || 'native authority NOT_BOUND'
      : value.result?.core_warrant_consumed===true ? 'fixture warrant consumed'
      : value.warrant_digest ? 'fixture approval recorded; consumption unverified' : 'exact fixture approval required';
    const progress=value.error || (value.state==='PREVIEWED'
      ? 'Review this exact task, scope and digest. Run approves only the displayed offline READ.'
      : value.state==='RUNNING' ? live
        ? 'Core-bound model request in flight. STOP cannot undo an already sent request; uncertain spend stays UNKNOWN.'
        : 'Core accepted. Reading the bounded fixture. STOP remains available.'
      : live ? `${value.state} · model receipt and browser verification are separate.`
      : `${value.state} · fixture evidence does not certify LIVE operation.`);
    return {boundary,approval,progress};
  }
  function createMissionClient({fetchJSON, render, error, delay = ms => new Promise(resolve => setTimeout(resolve, ms))}) {
    let current = null, attempted = false, invalid = false, generation = 0;
    const publish = value => { current = value; render(value); return value; };
    async function readback(version) {
      for (let read = 0; read < 48 && version === generation; read++) {
        try {
          const value = await fetchJSON(`/api/meta/evidence/${encodeURIComponent(current.task_id)}`);
          if (version !== generation) return current;
          publish(value);
          if (value.state !== 'RUNNING') return value;
        } catch (_) {
          error('Readback unavailable. Outcome UNKNOWN; run will not be resent.');
        }
        await delay(250);
      }
      return current;
    }
    return {
      adopt(value) {
        ++generation; attempted = !runnable(value); invalid = false;
        return publish(value);
      },
      async preview(payload) {
        const version = ++generation;
        const value = await fetchJSON('/api/meta/preview', {method:'POST',
          headers:{'X-AIOA-Intent':'meta-preview-v1'},body:JSON.stringify(payload)});
        if (version !== generation) return current;
        attempted = false; invalid = false; return publish(value);
      },
      invalidate() { invalid = true; },
      async run() {
        if (!runnable(current) || attempted || invalid) throw new Error('A current exact preview is required.');
        attempted = true; const version = generation;
        try {
          const value = await fetchJSON('/api/meta/run', {method:'POST',
            headers:{'X-AIOA-Intent':current.mode === 'LIVE' ? 'meta-run-approved-v1' : 'meta-run-fixture-v1'},body:JSON.stringify({task_id:current.task_id,preview_digest:current.preview_digest})});
          if (version === generation) publish(value);
        } catch (_) { error('Run acknowledgement unavailable. Reading status; no resend.'); }
        return readback(version);
      },
      async stop() {
        if (!current) throw new Error('No mission selected.');
        ++generation;
        const value = await fetchJSON('/api/meta/stop', {method:'POST',
          headers:{'X-AIOA-Intent':'meta-stop-v1'},body:JSON.stringify({task_id:current.task_id})});
        return publish(value);
      },
      async refresh() { return current ? readback(generation) : null; },
    };
  }
  const api = {createMissionClient, providerLabel, missionText};
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.AIOAMetaMissions = api;
})(typeof globalThis !== 'undefined' ? globalThis : this);
