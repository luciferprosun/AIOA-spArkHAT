/* Exact preview approval, GET-only readback and STOP reuse AIOA/Nebius UX ideas.
 * This controller belongs to the existing web UI; it never grants authority. */
(function (root) {
  'use strict';
  function providerLabel(value) {
    if (value && value.state === 'LIVE_PENDING_AUTHORIZATION') return 'Muse Spark · LIVE BLOCKED';
    return value && value.state === 'LIVE_VERIFIED' && value.live_verified === true
      ? 'Muse Spark · LIVE VERIFIED' : 'Muse Spark · OFFLINE FIXTURE';
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
        ++generation; attempted = value.state !== 'PREVIEWED'; invalid = false;
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
        if (!current || current.state !== 'PREVIEWED' || attempted || invalid) throw new Error('A current exact preview is required.');
        attempted = true; const version = generation;
        try {
          const value = await fetchJSON('/api/meta/run', {method:'POST',
            headers:{'X-AIOA-Intent':'meta-run-fixture-v1'},body:JSON.stringify({task_id:current.task_id,preview_digest:current.preview_digest})});
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
  const api = {createMissionClient, providerLabel};
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.AIOAMetaMissions = api;
})(typeof globalThis !== 'undefined' ? globalThis : this);
