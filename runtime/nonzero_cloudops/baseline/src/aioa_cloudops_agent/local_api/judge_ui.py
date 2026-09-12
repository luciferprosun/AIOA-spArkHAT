"""Self-contained, dependency-free judge console for the portable Local-2 API."""

import base64
import hashlib
from collections.abc import Mapping
from typing import Final

JUDGE_UI_STYLE: Final = r"""
:root {
  color-scheme: dark;
  --ink: #f4f7f5;
  --muted: #a7b4ae;
  --dim: #728079;
  --canvas: #090d0b;
  --surface: #101613;
  --surface-2: #151d19;
  --line: #27322d;
  --mint: #b9f87d;
  --mint-dark: #16351e;
  --amber: #ffbe58;
  --amber-dark: #3a2811;
  --violet: #bba6ff;
  --red: #ff897d;
  --red-dark: #3b1816;
  --radius: 22px;
  font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  background: var(--canvas);
  color: var(--ink);
}
* { box-sizing: border-box; }
html { scroll-behavior: smooth; }
body {
  margin: 0;
  min-width: 320px;
  min-height: 100vh;
  background:
    radial-gradient(circle at 8% -10%, #264126 0, transparent 34rem),
    radial-gradient(circle at 96% 6%, #291f45 0, transparent 30rem),
    var(--canvas);
}
button, input { font: inherit; }
button { min-height: 44px; }
button:focus-visible, input:focus-visible, summary:focus-visible {
  outline: 3px solid var(--violet);
  outline-offset: 3px;
}
.skip-link {
  position: fixed;
  left: 12px;
  top: -80px;
  z-index: 50;
  padding: 10px 14px;
  border-radius: 10px;
  background: var(--ink);
  color: var(--canvas);
}
.skip-link:focus { top: 12px; }
.shell { width: min(1240px, calc(100% - 40px)); margin: 0 auto; }
.topbar {
  position: sticky;
  top: 0;
  z-index: 20;
  border-bottom: 1px solid #ffffff12;
  background: #090d0bd9;
  backdrop-filter: blur(18px);
}
.topbar-inner {
  min-height: 74px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 20px;
}
.brand { display: flex; align-items: center; gap: 12px; font-weight: 850; letter-spacing: -.02em; }
.brand-mark {
  width: 34px;
  height: 34px;
  display: grid;
  place-items: center;
  border: 1px solid #cfff9a66;
  border-radius: 11px;
  background: #b9f87d16;
  color: var(--mint);
  font-size: 18px;
}
.brand-sub { color: var(--muted); font-weight: 520; }
.mode-cluster { display: flex; flex-wrap: wrap; justify-content: flex-end; gap: 8px; }
.pill {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  min-height: 30px;
  padding: 5px 10px;
  border: 1px solid var(--line);
  border-radius: 999px;
  background: #111814;
  color: var(--muted);
  font-size: .74rem;
  font-weight: 760;
  letter-spacing: .055em;
  text-transform: uppercase;
}
.pill::before { content: ""; width: 7px; height: 7px; border-radius: 50%; background: var(--dim); }
.pill.safe { color: var(--mint); border-color: #88bd5d55; }
.pill.safe::before { background: var(--mint); box-shadow: 0 0 14px #b9f87daa; }
.hero { padding: clamp(54px, 8vw, 102px) 0 44px; }
.kicker { color: var(--mint); font-size: .8rem; font-weight: 850; letter-spacing: .16em; text-transform: uppercase; }
h1 {
  max-width: 900px;
  margin: 16px 0 20px;
  font-size: clamp(2.55rem, 7vw, 6rem);
  line-height: .92;
  letter-spacing: -.065em;
  font-weight: 850;
}
.hero-copy { max-width: 750px; margin: 0; color: var(--muted); font-size: clamp(1rem, 2vw, 1.22rem); line-height: 1.65; }
.truth-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px;
  max-width: 850px;
  margin-top: 32px;
}
.truth {
  padding: 15px 16px;
  border: 1px solid var(--line);
  border-radius: 15px;
  background: #111713bb;
}
.truth strong { display: block; color: var(--mint); font-size: 1.05rem; }
.truth span { color: var(--dim); font-size: .78rem; }
.section { margin: 30px 0 72px; }
.section-heading { display: flex; justify-content: space-between; align-items: end; gap: 20px; margin-bottom: 18px; }
.section-number { color: var(--mint); font: 750 .76rem ui-monospace, SFMono-Regular, Menlo, monospace; letter-spacing: .1em; }
h2 { margin: 5px 0 0; font-size: clamp(1.45rem, 3vw, 2.2rem); letter-spacing: -.035em; }
.section-note { max-width: 520px; color: var(--muted); line-height: 1.5; text-align: right; }
.scenario-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; }
.scenario {
  position: relative;
  min-height: 250px;
  padding: 25px;
  overflow: hidden;
  border: 1px solid var(--line);
  border-radius: var(--radius);
  background: linear-gradient(145deg, #151d19, #0d120f);
  color: var(--ink);
  text-align: left;
  cursor: pointer;
  transition: transform .18s ease, border-color .18s ease, background .18s ease;
}
.scenario:hover:not(:disabled) { transform: translateY(-3px); border-color: #b9f87d66; background: linear-gradient(145deg, #19241d, #0d120f); }
.scenario:disabled { opacity: .5; cursor: not-allowed; }
.scenario::after {
  content: "→";
  position: absolute;
  right: 22px;
  bottom: 17px;
  color: var(--mint);
  font-size: 2rem;
}
.scenario.deny::after { color: var(--amber); }
.scenario-tag { color: var(--mint); font: 800 .74rem ui-monospace, monospace; letter-spacing: .1em; text-transform: uppercase; }
.scenario.deny .scenario-tag { color: var(--amber); }
.scenario h3 { max-width: 380px; margin: 24px 0 10px; font-size: clamp(1.4rem, 3vw, 2rem); letter-spacing: -.035em; }
.scenario p { max-width: 480px; margin: 0; color: var(--muted); line-height: 1.55; }
.session-strip {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 18px;
  margin-bottom: 14px;
  padding: 14px 16px;
  border: 1px solid var(--line);
  border-radius: 15px;
  background: #101613;
}
.session-copy { display: flex; align-items: center; gap: 10px; color: var(--muted); }
.session-dot { width: 9px; height: 9px; border-radius: 50%; background: var(--amber); }
.session-dot.connected { background: var(--mint); box-shadow: 0 0 14px #b9f87d88; }
.quiet-button {
  width: auto;
  padding: 8px 12px;
  border: 1px solid var(--line);
  border-radius: 10px;
  background: transparent;
  color: var(--muted);
  cursor: pointer;
}
.pipeline {
  display: grid;
  grid-template-columns: repeat(8, minmax(0, 1fr));
  gap: 7px;
  margin: 0 0 16px;
  padding: 0;
  list-style: none;
}
.pipeline li {
  position: relative;
  min-height: 73px;
  padding: 12px 10px;
  border: 1px solid var(--line);
  border-radius: 13px;
  background: #0e1411;
  color: var(--dim);
  font-size: .72rem;
  line-height: 1.35;
}
.pipeline li span { display: block; margin-bottom: 5px; font: 750 .68rem ui-monospace, monospace; }
.pipeline li.done { border-color: #6f995144; background: #122017; color: var(--muted); }
.pipeline li.done span { color: var(--mint); }
.pipeline li.current { border-color: #bba6ff88; background: #211b34; color: var(--ink); }
.pipeline li.safe-stop { border-color: #ffbe5866; background: var(--amber-dark); color: #ffe0ac; }
.workspace-grid { display: grid; grid-template-columns: minmax(0, 1.5fr) minmax(300px, .75fr); gap: 14px; }
.stack { display: grid; gap: 14px; align-content: start; }
.panel {
  border: 1px solid var(--line);
  border-radius: var(--radius);
  background: #101613e8;
  box-shadow: 0 22px 55px #0000002b;
}
.panel-pad { padding: 22px; }
.panel-head { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin-bottom: 20px; }
.panel h3 { margin: 0; font-size: 1rem; letter-spacing: -.01em; }
.state-badge {
  max-width: 100%;
  padding: 6px 9px;
  overflow: hidden;
  border-radius: 8px;
  background: #202a25;
  color: var(--muted);
  font: 800 .68rem ui-monospace, monospace;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.state-badge.success { background: var(--mint-dark); color: var(--mint); }
.state-badge.denied { background: var(--amber-dark); color: var(--amber); }
.facts { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; margin: 0; }
.fact { min-width: 0; padding-top: 12px; border-top: 1px solid var(--line); }
.fact.wide { grid-column: 1 / -1; }
.fact dt { margin-bottom: 5px; color: var(--dim); font-size: .72rem; text-transform: uppercase; letter-spacing: .08em; }
.fact dd { margin: 0; overflow-wrap: anywhere; color: var(--ink); font-size: .91rem; line-height: 1.45; }
.hash { color: var(--violet); font: .78rem ui-monospace, SFMono-Regular, Menlo, monospace; }
.authority-callout {
  margin-top: 18px;
  padding: 15px;
  border: 1px solid #ffbe5844;
  border-radius: 14px;
  background: #2b2112;
  color: #ffe4b8;
  line-height: 1.5;
}
.authority-callout strong { display: block; margin-bottom: 5px; color: var(--amber); }
.controls { display: grid; gap: 9px; }
.button {
  width: 100%;
  padding: 12px 15px;
  border: 1px solid transparent;
  border-radius: 12px;
  background: var(--mint);
  color: #10200d;
  font-weight: 850;
  cursor: pointer;
}
.button:hover:not(:disabled) { filter: brightness(1.05); }
.button:disabled { opacity: .38; cursor: not-allowed; }
.button.secondary { border-color: var(--line); background: #1a231f; color: var(--ink); }
.button.deny { border-color: #ffbe5844; background: var(--amber-dark); color: var(--amber); }
.button-row { display: grid; grid-template-columns: 1fr 1fr; gap: 9px; }
.decision-state { margin: 0 0 14px; color: var(--muted); line-height: 1.5; }
.proof {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 8px;
  margin-top: 16px;
}
.proof div { padding: 12px; border: 1px solid var(--line); border-radius: 12px; background: #0c110e; }
.proof strong { display: block; color: var(--mint); font-size: 1.2rem; }
.proof span { color: var(--dim); font-size: .72rem; }
.outcome {
  margin-top: 16px;
  padding: 15px;
  border-radius: 14px;
  background: #0c110e;
  color: var(--muted);
  line-height: 1.5;
}
.outcome.success { border: 1px solid #b9f87d55; color: #dbffc0; }
.outcome.denied { border: 1px solid #ffbe5855; color: #ffe1af; }
.resource-diff { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin-top: 16px; }
.resource-diff div { min-width: 0; padding: 13px; border: 1px solid var(--line); border-radius: 12px; background: #0b100d; }
.resource-diff span { display: block; margin-bottom: 8px; color: var(--dim); font-size: .72rem; text-transform: uppercase; }
.resource-diff code { overflow-wrap: anywhere; color: var(--muted); font-size: .75rem; white-space: pre-wrap; }
.timeline { margin: 0; padding: 0; list-style: none; }
.timeline li { position: relative; padding: 0 0 20px 27px; }
.timeline li::before { content: ""; position: absolute; left: 4px; top: 5px; width: 9px; height: 9px; border: 2px solid var(--mint); border-radius: 50%; background: var(--surface); }
.timeline li::after { content: ""; position: absolute; left: 9px; top: 18px; bottom: 1px; width: 1px; background: var(--line); }
.timeline li:last-child::after { display: none; }
.timeline strong { display: block; font-size: .87rem; }
.timeline .category { display: inline-block; margin-bottom: 4px; color: var(--mint); font: 750 .62rem ui-monospace, monospace; letter-spacing: .08em; }
.timeline time { display: block; margin: 3px 0; color: var(--dim); font-size: .72rem; }
.timeline code { color: var(--violet); font-size: .68rem; overflow-wrap: anywhere; }
.empty { color: var(--dim); line-height: 1.55; }
details.technical { border-top: 1px solid var(--line); }
.technical-wrap { margin-top: 14px; }
details.technical summary { padding: 17px 22px; color: var(--muted); cursor: pointer; }
details.technical pre {
  max-height: 480px;
  margin: 0 16px 16px;
  padding: 15px;
  overflow: auto;
  border-radius: 12px;
  background: #060906;
  color: #b9c7bf;
  font: .73rem/1.5 ui-monospace, SFMono-Regular, Menlo, monospace;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}
.connection details { border: 1px solid var(--line); border-radius: 15px; background: #0e1411; }
.connection summary { padding: 14px 16px; color: var(--muted); cursor: pointer; }
.connection-form { display: grid; grid-template-columns: 1fr auto auto; gap: 8px; padding: 0 14px 14px; }
.connection input { min-width: 0; padding: 11px; border: 1px solid var(--line); border-radius: 10px; background: #070a08; color: var(--ink); }
.connection .button { width: auto; }
.notice {
  position: fixed;
  right: 20px;
  bottom: 20px;
  z-index: 40;
  width: min(440px, calc(100% - 40px));
  padding: 14px 16px;
  border: 1px solid #b9f87d55;
  border-radius: 14px;
  background: #142019f2;
  box-shadow: 0 18px 55px #0009;
  color: #e6ffd5;
  line-height: 1.45;
}
.notice.error { border-color: #ff897d66; background: #2a1716f2; color: #ffd1cc; }
.footer { padding: 0 0 54px; color: var(--dim); font-size: .78rem; }
[hidden] { display: none !important; }
@media (max-width: 980px) {
  .pipeline { grid-template-columns: repeat(4, 1fr); }
  .workspace-grid { grid-template-columns: 1fr; }
}
@media (max-width: 700px) {
  .shell { width: min(100% - 24px, 1240px); }
  .topbar-inner { min-height: 66px; align-items: flex-start; padding: 13px 0; }
  .brand-sub { display: none; }
  .mode-cluster .pill:nth-child(2) { display: none; }
  .hero { padding-top: 48px; }
  .truth-grid, .scenario-grid, .facts, .resource-diff { grid-template-columns: 1fr; }
  .fact.wide { grid-column: auto; }
  .section-heading { display: block; }
  .section-note { margin: 10px 0 0; text-align: left; }
  .scenario { min-height: 220px; }
  .pipeline { display: flex; overflow-x: auto; padding-bottom: 6px; scroll-snap-type: x mandatory; }
  .pipeline li { flex: 0 0 132px; scroll-snap-align: start; }
  .session-strip { align-items: flex-start; }
  .connection-form { grid-template-columns: 1fr; }
  .connection .button { width: 100%; }
}
@media (prefers-reduced-motion: reduce) {
  html { scroll-behavior: auto; }
  *, *::before, *::after { transition-duration: .001ms !important; }
}
""".strip()

JUDGE_UI_SCRIPT: Final = r"""
(() => {
  'use strict';
  const byId = (id) => document.getElementById(id);
  const ui = {
    connected: false,
    busy: false,
    runId: '',
    challenge: null,
    view: null,
    replayProven: false,
  };
  const labels = {
    RUN_CREATED: 'Run identity created',
    RESOURCE_QUERIED: 'Sandbox resource observed',
    REMEDIATION_PLANNED: 'Bounded remediation proposed',
    APPROVAL_REQUESTED: 'Human approval requested',
    APPROVAL_RECORDED: 'Human decision recorded',
    IDEMPOTENCY_REGISTERED: 'Single-effect intent registered',
    EXECUTION_REQUESTED: 'Approved action sent to sandbox',
    EXECUTION_ACKNOWLEDGED: 'Sandbox receipt persisted',
    VERIFICATION_RECORDED: 'Independent read-back verified',
    POLICY_DENIED: 'Unsafe or stale request rejected',
    MODEL_OUTPUT_REJECTED: 'Untrusted model output rejected',
    NO_ACTION_RECORDED: 'No action required',
    RECOMMENDATION_RECORDED: 'Recommendation only',
  };

  class ApiError extends Error {
    constructor(status, payload) {
      super(String(payload.failure_code || payload.error || 'REQUEST_FAILED'));
      this.status = status;
      this.payload = payload;
    }
  }

  function announce(message, isError = false) {
    const notice = byId('notice');
    notice.textContent = message;
    notice.classList.toggle('error', isError);
    notice.hidden = false;
    window.clearTimeout(announce.timer);
    announce.timer = window.setTimeout(() => { notice.hidden = true; }, 7000);
  }

  function shortHash(value) {
    return typeof value === 'string' && value.length > 18
      ? value.slice(0, 10) + '…' + value.slice(-8)
      : (value || '—');
  }

  function setText(id, value, title = '') {
    const node = byId(id);
    node.textContent = value == null || value === '' ? '—' : String(value);
    node.title = title || (typeof value === 'string' ? value : '');
  }

  function setRunHash() {
    const target = ui.runId ? '#run=' + encodeURIComponent(ui.runId) : location.pathname;
    history.replaceState(null, '', target);
  }

  async function request(path, options = {}) {
    const method = options.method || 'GET';
    const headers = { Accept: 'application/json' };
    if (options.token) headers.Authorization = 'Bearer ' + options.token;
    if (options.body !== undefined) {
      headers['Content-Type'] = 'application/json';
      headers['X-AIOA-Intent'] = 'judge-console-v1';
    }
    const response = await fetch(path, {
      method,
      headers,
      body: options.body === undefined ? undefined : JSON.stringify(options.body),
      cache: 'no-store',
      credentials: 'same-origin',
    });
    let payload;
    try { payload = await response.json(); }
    catch (_) { payload = { error: 'INVALID_SERVER_RESPONSE' }; }
    if (!response.ok) throw new ApiError(response.status, payload);
    return Object.prototype.hasOwnProperty.call(payload, 'result') ? payload.result : payload;
  }

  function renderSession() {
    const dot = byId('session-dot');
    dot.classList.toggle('connected', ui.connected);
    setText('session-state', ui.connected ? 'Protected local session connected' : 'Local session required');
    document.querySelectorAll('[data-scenario]').forEach((button) => {
      button.disabled = !ui.connected || ui.busy;
    });
  }

  function renderRuntime(runtime) {
    if (!runtime) return;
    setText('mode-runtime', runtime.runtime_mode);
    setText('mode-provider', runtime.provider);
    setText('network-count', runtime.process_external_network_calls);
    setText('process-mutations', runtime.process_sandbox_mutations);
    setText('provider-calls', runtime.process_provider_calls);
    setText('model-id', runtime.model_id, runtime.model_id);
  }

  function resourceSummary(resource) {
    if (!resource) return 'Absent (expected for a released address)';
    const summary = {
      type: resource.resource_type,
      id: resource.resource_id,
      region: resource.region,
    };
    if (Object.prototype.hasOwnProperty.call(resource, 'association_id')) summary.association_id = resource.association_id;
    if (Array.isArray(resource.inbound_rules)) summary.inbound_rules = resource.inbound_rules.length;
    if (resource.state) summary.state = resource.state;
    return JSON.stringify(summary, null, 2);
  }

  function renderAudit(events) {
    const list = byId('timeline');
    list.replaceChildren();
    if (!Array.isArray(events) || events.length === 0) {
      const empty = document.createElement('li');
      empty.className = 'empty';
      empty.textContent = 'The immutable timeline appears after a scenario starts.';
      list.append(empty);
      return;
    }
    events.forEach((event) => {
      const item = document.createElement('li');
      const category = document.createElement('span');
      const title = document.createElement('strong');
      const time = document.createElement('time');
      const digest = document.createElement('code');
      category.className = 'category';
      category.textContent = event.category || 'FACT';
      title.textContent = event.summary || labels[event.type] || event.type;
      time.textContent = new Date(event.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
      time.dateTime = event.timestamp;
      digest.textContent = shortHash(event.redacted_payload_hash);
      digest.title = event.redacted_payload_hash;
      item.append(category, title, time, digest);
      list.append(item);
    });
  }

  function markPipeline(view) {
    const checkpoint = view.checkpoint || {};
    const evidence = checkpoint.resource_evidence;
    const proposal = checkpoint.remediation_proposal;
    const approval = checkpoint.approval;
    const receipt = checkpoint.execution_receipt;
    const verification = checkpoint.verification;
    const denied = view.run.state === 'DENIED_BY_HUMAN';
    const flags = {
      observe: Boolean(evidence),
      evidence: Boolean(evidence),
      proposal: Boolean(proposal),
      policy: Boolean(proposal),
      approval: Boolean(approval),
      execution: Boolean(receipt) || denied,
      verification: Boolean(verification) || denied,
      receipt: Boolean(verification) || denied,
    };
    let foundCurrent = false;
    document.querySelectorAll('[data-stage]').forEach((stage) => {
      const complete = flags[stage.dataset.stage];
      stage.classList.toggle('done', complete);
      stage.classList.toggle('safe-stop', denied && complete && ['execution', 'verification', 'receipt'].includes(stage.dataset.stage));
      const current = !complete && !foundCurrent;
      stage.classList.toggle('current', current);
      if (current) foundCurrent = true;
    });
  }

  function renderView(view) {
    ui.view = view;
    const checkpoint = view.checkpoint || {};
    const evidence = checkpoint.resource_evidence || {};
    const proposal = checkpoint.remediation_proposal || {};
    const requestView = checkpoint.approval_request || {};
    const approval = checkpoint.approval || {};
    const receipt = checkpoint.execution_receipt || null;
    const verification = checkpoint.verification || null;
    const state = view.run.state;
    const denied = state === 'DENIED_BY_HUMAN';
    const succeeded = state === 'SUCCESS_WITH_EVIDENCE';

    byId('workspace').hidden = false;
    setText('run-state', state);
    byId('run-state').className = 'state-badge' + (succeeded ? ' success' : denied ? ' denied' : '');
    setText('run-id', shortHash(view.run.run_id), view.run.run_id);
    setText('trace-id', shortHash(view.run.trace_id), view.run.trace_id);
    setText('snapshot-hash', shortHash(view.evidence_snapshot_sha256), view.evidence_snapshot_sha256);
    setText('target', proposal.target_resource_id || evidence.resource?.resource_id);
    setText('resource-type', proposal.target_resource_type || evidence.resource?.resource_type);
    setText('finding', Array.isArray(evidence.findings) ? evidence.findings.join(', ') : '—');
    setText('observed-at', evidence.observed_at ? new Date(evidence.observed_at).toLocaleString() : '—', evidence.observed_at);
    setText('evidence-hash', shortHash(evidence.evidence_hash), evidence.evidence_hash);
    setText('operation', proposal.operation_type || 'No executable proposal');
    setText('impact', proposal.risk_summary || 'The policy engine found no bounded mutation to propose.');
    setText('authority', proposal.authority_class || 'NOT_REQUIRED');
    setText('proposal-hash', shortHash(proposal.proposal_hash), proposal.proposal_hash);
    setText('fingerprint', shortHash(proposal.evidence_fingerprint), proposal.evidence_fingerprint);
    setText('request-hash', shortHash(requestView.request_hash), requestView.request_hash);
    setText('decision-hash', shortHash(approval.decision_hash), approval.decision_hash);
    setText('receipt-hash', shortHash(receipt?.receipt_hash), receipt?.receipt_hash);
    setText('verification-hash', shortHash(verification?.verification_hash), verification?.verification_hash);
    setText('run-mutations', view.run_sandbox_mutations);
    renderRuntime(view.runtime);
    renderAudit(view.audit_events);
    markPipeline(view);

    const decisionCopy = succeeded
      ? 'The approved action executed once. Independent read-back closed the run with evidence.'
      : !proposal.proposal_id
      ? 'No human decision is needed for this evidence.'
      : !requestView.request_id
        ? 'The proposal is inert. Open its exact evidence-bound decision request.'
        : !approval.decision
          ? (ui.challenge ? 'Review the target, operation and hashes. Your decision is the authority boundary.' : 'The page was refreshed or another tab changed the challenge. Reload the exact request before deciding.')
          : approval.decision === 'APPROVED'
            ? 'APPROVED is durable, but execution is still a separate explicit gesture.'
            : 'DENIED_BY_HUMAN is a successful safety outcome. No action receipt exists.';
    setText('decision-copy', decisionCopy);

    byId('review').disabled = ui.busy || !ui.connected || !proposal.proposal_id || Boolean(approval.decision) || state !== 'AWAITING_APPROVAL';
    byId('approve').disabled = ui.busy || !ui.connected || !ui.challenge || Boolean(approval.decision);
    byId('deny').disabled = ui.busy || !ui.connected || !ui.challenge || Boolean(approval.decision);
    byId('execute').disabled = ui.busy || !ui.connected || !['APPROVED', 'SUCCESS_WITH_EVIDENCE'].includes(state);
    setText('execute-label', succeeded ? 'Test replay protection' : 'Execute approved action');

    const outcome = byId('outcome');
    outcome.className = 'outcome' + (succeeded ? ' success' : denied ? ' denied' : '');
    if (succeeded) {
      outcome.textContent = ui.replayProven
        ? 'Replay-safe: the completed receipt was reconciled and no second sandbox mutation occurred.'
        : 'SUCCESS_WITH_EVIDENCE: one bounded sandbox mutation was independently verified. You can now test replay protection.';
    } else if (denied) {
      outcome.textContent = 'DENIED_BY_HUMAN: the resource stayed unchanged and no execution or verification receipt was created.';
    } else {
      outcome.textContent = 'No model output can mutate this sandbox. Policy, exact human authority and a separate execution gesture are required.';
    }
    setText('before-state', resourceSummary(receipt?.before_resource));
    setText('after-state', receipt ? resourceSummary(receipt.after_resource) : 'No mutation receipt');
    byId('raw-output').textContent = JSON.stringify(view, null, 2);
  }

  async function refresh(silent = false) {
    if (!ui.runId) return;
    try {
      const view = await request('/api/runs/' + encodeURIComponent(ui.runId));
      ui.connected = true;
      renderSession();
      renderView(view);
      if (!silent) announce('Durable state refreshed.');
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) {
        ui.connected = false;
        renderSession();
        announce('Reconnect the protected local session to resume this run.', true);
        return;
      }
      throw error;
    }
  }

  async function guarded(action) {
    if (ui.busy) return;
    ui.busy = true;
    renderSession();
    if (ui.view) renderView(ui.view);
    try { await action(); }
    catch (error) {
      const stale = error instanceof ApiError && [403, 409].includes(error.status);
      if (stale && ui.runId) {
        ui.challenge = null;
        await refresh(true).catch(() => {});
        announce('A stale or conflicting action was rejected. Durable truth has been reloaded.', true);
      } else {
        announce(error instanceof ApiError ? error.message : 'Local request failed safely.', true);
      }
    } finally {
      ui.busy = false;
      renderSession();
      if (ui.view) renderView(ui.view);
    }
  }

  async function connect(token) {
    await request('/api/session', { method: 'POST', body: {}, token });
    ui.connected = true;
    renderSession();
  }

  async function startScenario(button) {
    await guarded(async () => {
      const result = await request('/api/runs', {
        method: 'POST',
        body: {
          resource_type: button.dataset.resourceType,
          resource_id: button.dataset.resourceId,
        },
      });
      ui.runId = result.run_id;
      ui.challenge = null;
      ui.replayProven = false;
      setRunHash();
      await refresh(true);
      byId('workspace').scrollIntoView({ behavior: 'smooth', block: 'start' });
      announce('Evidence captured. The proposal is paused at human authority.');
    });
  }

  async function reviewProposal() {
    await guarded(async () => {
      ui.challenge = await request('/api/runs/' + encodeURIComponent(ui.runId) + '/approval-request', { method: 'POST', body: {} });
      await refresh(true);
      announce('Exact request loaded. Approve or deny only the displayed bound action.');
    });
  }

  async function decide(decision) {
    await guarded(async () => {
      if (!ui.challenge) throw new Error('Reload the exact approval request first.');
      const approvalRequest = ui.challenge.request;
      await request('/api/runs/' + encodeURIComponent(ui.runId) + '/decision', {
        method: 'POST',
        body: {
          request_id: approvalRequest.request_id,
          run_id: approvalRequest.run_id,
          proposal_id: approvalRequest.proposal_id,
          request_hash: approvalRequest.request_hash,
          proposal_hash: approvalRequest.proposal_hash,
          evidence_hash: approvalRequest.evidence_hash,
          proposal_version: approvalRequest.proposal_version,
          decision,
          decision_nonce: ui.challenge.decision_nonce,
        },
      });
      ui.challenge = null;
      await refresh(true);
      announce(decision === 'APPROVED' ? 'Approval recorded. No execution has happened yet.' : 'Human denial recorded. Zero mutation for this run.');
    });
  }

  async function executeOrReplay() {
    await guarded(async () => {
      const before = ui.view?.run_sandbox_mutations || 0;
      const result = await request('/api/runs/' + encodeURIComponent(ui.runId) + '/resume', { method: 'POST', body: { confirm_execution: true } });
      await refresh(true);
      if (result.reconciled === true && ui.view.run_sandbox_mutations === before) ui.replayProven = true;
      announce(result.reconciled === true ? 'Existing receipt reconciled. No duplicate mutation.' : 'Approved sandbox action executed and independently verified.');
    });
  }

  async function boot() {
    const fragment = new URLSearchParams(location.hash.slice(1));
    const bootstrapToken = fragment.get('access_token') || '';
    ui.runId = fragment.get('run') || '';
    setRunHash();
    try {
      const ready = await request('/ready');
      renderRuntime(ready.runtime);
      if (bootstrapToken) await connect(bootstrapToken);
      else {
        await request('/api/session');
        ui.connected = true;
      }
      renderSession();
      if (ui.runId) await refresh(true);
    } catch (_) {
      ui.connected = false;
      renderSession();
      if (ui.runId) announce('Run identity restored. Connect the local session to resume.', true);
    }
  }

  document.querySelectorAll('[data-scenario]').forEach((button) => button.addEventListener('click', () => startScenario(button)));
  byId('review').addEventListener('click', reviewProposal);
  byId('approve').addEventListener('click', () => decide('APPROVED'));
  byId('deny').addEventListener('click', () => decide('DENIED'));
  byId('execute').addEventListener('click', executeOrReplay);
  byId('refresh').addEventListener('click', () => guarded(() => refresh(true)));
  byId('connect-form').addEventListener('submit', (event) => {
    event.preventDefault();
    const input = byId('token');
    const token = input.value;
    input.value = '';
    guarded(async () => {
      await connect(token);
      if (ui.runId) await refresh(true);
      announce('Protected browser session established.');
    });
  });
  byId('disconnect').addEventListener('click', () => guarded(async () => {
    await request('/api/session', { method: 'DELETE' });
    ui.connected = false;
    ui.challenge = null;
    renderSession();
    announce('Browser session cleared. Durable run evidence was preserved.');
  }));
  renderSession();
  boot();
})();
""".strip()

_STYLE_HASH = base64.b64encode(
    hashlib.sha256(JUDGE_UI_STYLE.encode("utf-8")).digest()
).decode("ascii")
_SCRIPT_HASH = base64.b64encode(
    hashlib.sha256(JUDGE_UI_SCRIPT.encode("utf-8")).digest()
).decode("ascii")


def judge_ui_headers(base_headers: Mapping[str, str]) -> dict[str, str]:
    """Bind the exact inline assets into a strict no-network CSP."""

    return {
        **base_headers,
        "content-security-policy": (
            "default-src 'none';base-uri 'none';connect-src 'self';frame-ancestors 'none';"
            "form-action 'self';"
            f"style-src 'sha256-{_STYLE_HASH}';script-src 'sha256-{_SCRIPT_HASH}'"
        ),
        "content-type": "text/html; charset=utf-8",
    }


JUDGE_UI_BODY: Final = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="color-scheme" content="dark">
  <title>AIOA — Agents for Humans</title>
  <style>{JUDGE_UI_STYLE}</style>
</head>
<body>
  <a class="skip-link" href="#scenarios">Skip to demo</a>
  <header class="topbar">
    <div class="shell topbar-inner">
      <div class="brand"><span class="brand-mark" aria-hidden="true">A</span><span>AIOA <span class="brand-sub">/ Agents for Humans</span></span></div>
      <div class="mode-cluster" aria-label="Runtime truth">
        <span class="pill safe">Demo sandbox</span>
        <span class="pill safe">Portable / <span id="mode-provider">mock</span></span>
        <span class="pill">Strands</span>
      </div>
    </div>
  </header>

  <main id="main" class="shell">
    <section class="hero" aria-labelledby="hero-title">
      <div class="kicker">Non-Zero control plane · human authority preserved</div>
      <h1 id="hero-title">Evidence first.<br>Humans decide.</h1>
      <p class="hero-copy">A CloudOps agent can investigate and propose. It cannot turn model output into authority. Review one exact action, approve or deny it, and watch the system prove what happened.</p>
      <div class="truth-grid" aria-label="Safety facts">
        <div class="truth"><strong>0 real cloud writes</strong><span>Bounded local state only</span></div>
        <div class="truth"><strong><span id="network-count">0</span> network calls</strong><span>No hidden service dependency</span></div>
        <div class="truth"><strong>Exact hash binding</strong><span>Approval cannot drift to another action</span></div>
      </div>
    </section>

    <section id="scenarios" class="section" aria-labelledby="scenario-title">
      <div class="section-heading">
        <div><div class="section-number">01 / CHOOSE A STORY</div><h2 id="scenario-title">Start with one safe click</h2></div>
        <p class="section-note">Both scenarios use deterministic AWS-shaped fixtures. Nothing here is live AWS.</p>
      </div>
      <div class="session-strip">
        <div class="session-copy"><span id="session-dot" class="session-dot" aria-hidden="true"></span><span id="session-state">Local session required</span></div>
        <button id="refresh" class="quiet-button" type="button">Refresh durable state</button>
      </div>
      <div class="scenario-grid">
        <button class="scenario" type="button" data-scenario data-resource-type="AWS::EC2::EIP" data-resource-id="eipalloc-0123456789abcdef0">
          <span class="scenario-tag">Primary · approval path</span>
          <h3>Release an unattached Elastic IP</h3>
          <p>Observe waste, inspect bound evidence, approve one exact remediation, then verify one sandbox mutation.</p>
        </button>
        <button class="scenario deny" type="button" data-scenario data-resource-type="AWS::EC2::SecurityGroup" data-resource-id="sg-0123456789abcdef0">
          <span class="scenario-tag">Safety proof · denial path</span>
          <h3>Deny a public-ingress change</h3>
          <p>Reach the same human boundary, deny the proposal, and prove the resource stayed unchanged.</p>
        </button>
      </div>
    </section>

    <section id="workspace" class="section" aria-labelledby="workspace-title" hidden>
      <div class="section-heading">
        <div><div class="section-number">02 / INSPECT + DECIDE</div><h2 id="workspace-title">The complete authority path</h2></div>
        <span id="run-state" class="state-badge">READY</span>
      </div>
      <ol class="pipeline" aria-label="Workflow stages">
        <li data-stage="observe"><span>01</span>Observe</li>
        <li data-stage="evidence"><span>02</span>Evidence</li>
        <li data-stage="proposal"><span>03</span>Proposal</li>
        <li data-stage="policy"><span>04</span>Policy</li>
        <li data-stage="approval"><span>05</span>Human</li>
        <li data-stage="execution"><span>06</span>Execute</li>
        <li data-stage="verification"><span>07</span>Verify</li>
        <li data-stage="receipt"><span>08</span>Receipt</li>
      </ol>

      <div class="workspace-grid">
        <div class="stack">
          <article class="panel panel-pad">
            <div class="panel-head"><h3>Observed evidence</h3><span class="state-badge">READ ONLY</span></div>
            <dl class="facts">
              <div class="fact"><dt>Target</dt><dd id="target">—</dd></div>
              <div class="fact"><dt>Resource type</dt><dd id="resource-type">—</dd></div>
              <div class="fact wide"><dt>Finding</dt><dd id="finding">—</dd></div>
              <div class="fact"><dt>Observed</dt><dd id="observed-at">—</dd></div>
              <div class="fact"><dt>Evidence hash</dt><dd id="evidence-hash" class="hash">—</dd></div>
            </dl>
          </article>

          <article class="panel panel-pad">
            <div class="panel-head"><h3>Inert remediation proposal</h3><span class="state-badge">CANNOT EXECUTE</span></div>
            <dl class="facts">
              <div class="fact"><dt>Operation</dt><dd id="operation">—</dd></div>
              <div class="fact"><dt>Required authority</dt><dd id="authority">—</dd></div>
              <div class="fact wide"><dt>Impact / reason</dt><dd id="impact">—</dd></div>
              <div class="fact"><dt>Proposal hash</dt><dd id="proposal-hash" class="hash">—</dd></div>
              <div class="fact"><dt>Evidence fingerprint</dt><dd id="fingerprint" class="hash">—</dd></div>
            </dl>
            <div class="authority-callout"><strong>Why approval is required</strong>The proposal describes an exact change but carries <code>authorizes_execution: false</code>. Only a matching, unexpired human decision can establish authority.</div>
          </article>

          <article class="panel panel-pad">
            <div class="panel-head"><h3>Execution + independent verification</h3><span class="state-badge">SANDBOX ONLY</span></div>
            <dl class="facts">
              <div class="fact"><dt>Request binding</dt><dd id="request-hash" class="hash">—</dd></div>
              <div class="fact"><dt>Decision binding</dt><dd id="decision-hash" class="hash">—</dd></div>
              <div class="fact"><dt>Execution receipt</dt><dd id="receipt-hash" class="hash">—</dd></div>
              <div class="fact"><dt>Verification proof</dt><dd id="verification-hash" class="hash">—</dd></div>
            </dl>
            <div class="resource-diff"><div><span>Before</span><code id="before-state">No mutation receipt</code></div><div><span>After / read-back</span><code id="after-state">No mutation receipt</code></div></div>
          </article>
        </div>

        <aside class="stack">
          <section class="panel panel-pad" aria-labelledby="authority-title">
            <div class="panel-head"><h3 id="authority-title">Human authority</h3></div>
            <p id="decision-copy" class="decision-state">Start a scenario to reach the decision boundary.</p>
            <div class="controls">
              <button id="review" class="button secondary" type="button" disabled>Review exact request</button>
              <div class="button-row"><button id="approve" class="button" type="button" disabled>Approve</button><button id="deny" class="button deny" type="button" disabled>Deny</button></div>
              <button id="execute" class="button secondary" type="button" disabled><span id="execute-label">Execute approved action</span></button>
            </div>
            <div class="proof"><div><strong id="run-mutations">0</strong><span>mutations this run</span></div><div><strong id="process-mutations">0</strong><span>process sandbox mutations</span></div><div><strong id="provider-calls">0</strong><span>deterministic model calls</span></div><div><strong>0</strong><span>real AWS mutations</span></div></div>
            <div id="outcome" class="outcome">No model output can mutate this sandbox.</div>
          </section>

          <section class="panel panel-pad" aria-labelledby="audit-title">
            <div class="panel-head"><h3 id="audit-title">Durable evidence timeline</h3></div>
            <ol id="timeline" class="timeline"><li class="empty">The immutable timeline appears after a scenario starts.</li></ol>
          </section>

          <section class="panel panel-pad">
            <div class="panel-head"><h3>Run identity</h3></div>
            <dl class="facts">
              <div class="fact wide"><dt>Run ID</dt><dd id="run-id" class="hash">—</dd></div>
              <div class="fact wide"><dt>Trace ID</dt><dd id="trace-id" class="hash">—</dd></div>
              <div class="fact wide"><dt>Integrity-verified snapshot</dt><dd id="snapshot-hash" class="hash">—</dd></div>
              <div class="fact wide"><dt>Runtime / model</dt><dd><span id="mode-runtime">portable</span> · <span id="model-id">aioa.mock.deterministic-v1</span></dd></div>
            </dl>
          </section>
        </aside>
      </div>

      <div class="panel technical-wrap">
        <details class="technical"><summary>Inspect sanitized machine-readable evidence</summary><pre id="raw-output">No run selected.</pre></details>
      </div>
    </section>

    <section class="section connection" aria-labelledby="connection-title">
      <details>
        <summary id="connection-title">Manual local-session fallback</summary>
        <form id="connect-form" class="connection-form">
          <input id="token" type="password" autocomplete="off" spellcheck="false" aria-label="Local bearer token" placeholder="Paste owner-only local token">
          <button class="button secondary" type="submit">Connect</button>
          <button id="disconnect" class="button deny" type="button">Disconnect</button>
        </form>
      </details>
    </section>
  </main>
  <footer class="shell footer">AIOA portable judge experience · deterministic model · protected local sandbox · no AWS credentials required</footer>
  <div id="notice" class="notice" role="status" aria-live="polite" hidden></div>
  <script>{JUDGE_UI_SCRIPT}</script>
</body>
</html>"""
