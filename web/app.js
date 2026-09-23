const state = {
  currentModel: "",
  scenario: null,
  sessionToken: null,
  cplPlan: null,
  cplStatus: null,
  cplPreset: null,
  cplPoll: null,
  cplRunId: null,
  cplRevision: 0,
  cplRunning: false,
  cplDelivered: new Set(),
  cplAsked: new Set(),
  modelSwitchPending: false,
};

const elements = {
  modelSelect: document.querySelector("#model-select"),
  modelPicker: document.querySelector("#model-picker"),
  currentModelBadge: document.querySelector("#current-model-badge"),
  modelNote: document.querySelector("#model-note"),
  chatLog: document.querySelector("#chat-log"),
  promptInput: document.querySelector("#prompt-input"),
  composer: document.querySelector("#composer"),
  sessionModel: document.querySelector("#session-model"),
  sessionSummary: document.querySelector("#session-summary"),
  statusCwd: document.querySelector("#status-cwd"),
  statusBrowser: document.querySelector("#status-browser"),
  statusUrl: document.querySelector("#status-url"),
  statusVault: document.querySelector("#status-vault"),
  metricTools: document.querySelector("#metric-tools"),
  metricCommands: document.querySelector("#metric-commands"),
  metricOutputs: document.querySelector("#metric-outputs"),
  viewTitle: document.querySelector("#view-title"),
  reviewForm: document.querySelector("#review-form"),
  reviewInput: document.querySelector("#review-input"),
  reviewScenarioTitle: document.querySelector("#review-scenario-title"),
  reviewScenarioMeta: document.querySelector("#review-scenario-meta"),
  reviewPrompt: document.querySelector("#review-prompt"),
  reviewAsOf: document.querySelector("#review-as-of"),
  reviewEvidence: document.querySelector("#review-evidence"),
  reviewRequestStatus: document.querySelector("#review-request-status"),
  reviewValueStatus: document.querySelector("#review-value-status"),
  reviewDecision: document.querySelector("#review-decision"),
  reviewCriticalCount: document.querySelector("#review-critical-count"),
  reviewWarningCount: document.querySelector("#review-warning-count"),
  reviewInfoCount: document.querySelector("#review-info-count"),
  reviewFindings: document.querySelector("#review-findings"),
  reviewEvidenceDigest: document.querySelector("#review-evidence-digest"),
  reviewSnapshotHash: document.querySelector("#review-snapshot-hash"),
  reviewNextStep: document.querySelector("#review-next-step"),
  authorityEffectBadge: document.querySelector("#authority-effect-badge"),
  authorityTimelineSummary: document.querySelector("#authority-timeline-summary"),
  authorityTimeline: document.querySelector("#authority-timeline"),
  competitionProviderMode: document.querySelector("#competition-provider-mode"),
  competitionProviderAvailability: document.querySelector("#competition-provider-availability"),
  competitionProviderEvidence: document.querySelector("#competition-provider-evidence"),
  competitionEvaluationSummary: document.querySelector("#competition-evaluation-summary"),
  competitionUseCaseSummary: document.querySelector("#competition-use-case-summary"),
  competitionTaskSuccess: document.querySelector("#competition-task-success"),
  competitionVerifiedEffects: document.querySelector("#competition-verified-effects"),
  competitionDuplicateEffects: document.querySelector("#competition-duplicate-effects"),
  competitionMemoryBackend: document.querySelector("#competition-memory-backend"),
  competitionVerifiedReuse: document.querySelector("#competition-verified-reuse"),
  competitionDynamicsMode: document.querySelector("#competition-dynamics-mode"),
  competitionAuthorityBoundary: document.querySelector("#competition-authority-boundary"),
  competitionMissionHeartbeat: document.querySelector("#competition-mission-heartbeat"),
  competitionReceiptState: document.querySelector("#competition-receipt-state"),
  competitionMeasurementState: document.querySelector("#competition-measurement-state"),
  competitionRestartRecovery: document.querySelector("#competition-restart-recovery"),
  competitionRecoveryStatus: document.querySelector("#competition-recovery-status"),
  competitionNonzeroReadiness: document.querySelector("#competition-nonzero-readiness"),
  competitionNonzeroApproval: document.querySelector("#competition-nonzero-approval"),
  competitionNonzeroReceipt: document.querySelector("#competition-nonzero-receipt"),
  competitionEffectExecutor: document.querySelector("#competition-effect-executor"),
  competitionNonzeroBoundary: document.querySelector("#competition-nonzero-boundary"),
};

async function jsonFetch(url, options = {}) {
  const response = await fetch(url, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...(state.sessionToken ? {"X-AIOA-Session-Token": state.sessionToken} : {}),
      ...(options.headers || {}),
    },
  });
  const payload = await response.json();
  if (!response.ok) {
    throw new Error(payload.detail || payload.error || `Request failed: ${response.status}`);
  }
  return payload;
}

function addMessage(role, body) {
  const template = document.querySelector("#message-template");
  const node = template.content.firstElementChild.cloneNode(true);
  node.querySelector(".message-role").textContent = role;
  node.querySelector(".message-body").textContent = body || "(empty)";
  if (role === "You") {
    node.classList.add("message-user");
  }
  if (role.startsWith('AIOA spArkHAT')) node.classList.add('message-product');
  elements.chatLog.appendChild(node);
  elements.chatLog.scrollTop = elements.chatLog.scrollHeight;
  return node;
}

function applyStatus(status) {
  state.currentModel = status.model;
  elements.currentModelBadge.textContent = status.model;
  elements.sessionModel.textContent = status.model;
  elements.sessionSummary.textContent = status.browser_active
    ? "Browser session is active and ready for operator-approved actions."
    : "Browser is idle. Local routing, evidence review, shell, and filesystem tools are ready.";
  elements.statusCwd.textContent = status.cwd;
  elements.statusBrowser.textContent = status.browser_active ? "active" : "inactive";
  elements.statusUrl.textContent = status.current_url || "(none)";
  elements.statusVault.textContent = status.vault_dir;
  elements.metricTools.textContent = String((status.tools || []).length);
  elements.metricCommands.textContent = String((status.previous_commands || []).length);
  elements.metricOutputs.textContent = String((status.recent_outputs || []).length);
  if (status.critical_loop) applyCPLStatus(status.critical_loop);
}

async function refreshStatus() {
  const payload = await jsonFetch("/api/status");
  applyStatus(payload);
  hydrateModelSelect(payload.available_models, payload.model);
}

function renderAuthorityTimeline(payload) {
  elements.authorityEffectBadge.textContent = payload.effect_authority || "UNAVAILABLE";
  elements.authorityTimelineSummary.textContent = payload.timeline_is_read_only_projection
    ? "Read-only projection: model, CPL, memory and DVM can advise; only Core/human-bound gates may authorize effects."
    : "Authority projection unavailable.";
  elements.authorityTimeline.replaceChildren();
  for (const event of payload.events || []) {
    const node = document.createElement("article");
    node.className = "finding";
    const authority = document.createElement("span");
    authority.className = "finding-severity";
    authority.textContent = event.authority || "UNKNOWN";
    const body = document.createElement("div");
    const title = document.createElement("h4");
    title.textContent = (event.stage || "stage").replaceAll("_", " ");
    const detail = document.createElement("p");
    detail.textContent = `${event.status || "UNAVAILABLE"} · ${event.source || "runtime"}`;
    body.append(title, detail);
    node.append(authority, body);
    elements.authorityTimeline.appendChild(node);
  }
}

async function refreshAuthorityTimeline() {
  renderAuthorityTimeline(await jsonFetch("/api/authority-timeline"));
}

function renderCompetitionEvaluation(payload) {
  elements.competitionProviderMode.textContent = payload.provider_mode || "EXTERNAL_UNAVAILABLE";
  elements.competitionEvaluationSummary.textContent = payload.status === "PASS"
    ? "PASS · explicit trajectory/outcome metrics only; hidden reasoning is not requested or stored."
    : `${payload.status || "UNAVAILABLE"} · competition evidence is not being presented as a successful run.`;
  elements.competitionTaskSuccess.textContent = Number.isFinite(payload.task_success_rate)
    ? `${Math.round(payload.task_success_rate * 100)}%` : "—";
  elements.competitionVerifiedEffects.textContent = String(payload.tool_usage?.verified_effects ?? "—");
  elements.competitionDuplicateEffects.textContent = String(payload.tool_usage?.duplicate_effects ?? "—");
  const memory = payload.memory || {};
  elements.competitionMemoryBackend.textContent = memory.backend_mode === "LIVE_COCKROACH"
    ? "CockroachDB LIVE"
    : memory.backend_mode === "TEST_FIXTURE"
      ? "Fixture"
      : "Unknown";
  elements.competitionVerifiedReuse.textContent = memory.reuse_zero_write === true
    ? "ZERO_WRITE" : "UNVERIFIED";
  elements.competitionDynamicsMode.textContent = memory.dvm_pheromone_mode || "UNKNOWN";
  const nonzero = payload.nonzero || {};
  elements.competitionNonzeroReadiness.textContent = nonzero.status || "UNAVAILABLE";
  elements.competitionNonzeroApproval.textContent = nonzero.approval_status || "UNVERIFIED";
  elements.competitionNonzeroReceipt.textContent = nonzero.receipt_status || "UNVERIFIED";
  elements.competitionEffectExecutor.textContent = nonzero.competition_effect_executor || "UNKNOWN";
  elements.competitionNonzeroBoundary.textContent = nonzero.nonzero_executor_invoked === false
    ? `Non-Zero ${nonzero.implementation || "UNKNOWN"} · ${nonzero.mode || "UNKNOWN"}/${nonzero.provider || "UNKNOWN"} · ${nonzero.relationship || "read-only"}. Competition receipt stays owned by ${nonzero.receipt_source || "ServiceGuard"}; Non-Zero executor was not invoked.`
    : "Non-Zero boundary unavailable or inconsistent.";
  const reliability = payload.reliability || {};
  elements.competitionAuthorityBoundary.textContent =
    reliability.human_bound_effect_authority === true
    && reliability.provider_output_authority === false
      ? "CORE + HUMAN" : "UNVERIFIED";
  const replay = reliability.restart_replay_status || "UNAVAILABLE";
  const independent = reliability.independent_effect_verified === true ? "VERIFIED" : "UNVERIFIED";
  const verifiedMode = reliability.independent_measurement_state || "UNAVAILABLE";
  const duplicateEffects = payload.tool_usage?.duplicate_effects;
  elements.competitionUseCaseSummary.textContent =
    `Use case: long-running service maintenance. The agent observes and prepares a transition; after the human-bound gate, Service Guard applies one disposable local effect. Verified target state: ${verifiedMode}; duplicate effects after restart: ${duplicateEffects ?? "—"}.`;
  elements.competitionMissionHeartbeat.textContent = reliability.mission_heartbeat_state || "UNAVAILABLE";
  elements.competitionReceiptState.textContent = reliability.durable_receipt_verified === true
    ? "VERIFIED" : "UNVERIFIED";
  elements.competitionMeasurementState.textContent = reliability.independent_measurement_state || "UNAVAILABLE";
  elements.competitionRestartRecovery.textContent = reliability.restart_recovery_state || "UNAVAILABLE";
  const attempts = payload.trajectory_efficiency?.effect_attempts_per_verified_effect;
  elements.competitionRecoveryStatus.textContent =
    `Memory: ${memory.backend_id || "UNKNOWN"} (${memory.schema_profile || "UNKNOWN"}) · receipt: ${reliability.receipt_state || "UNAVAILABLE"} · restart/replay: ${replay} · independent measurement: ${independent} · effect attempts/verified effect: ${attempts ?? "—"}.`;
}

async function refreshCompetitionEvaluation() {
  renderCompetitionEvaluation(await jsonFetch("/api/competition-evaluation"));
}

function renderProviderAvailability(payload) {
  const mode = payload.provider_mode || "UNKNOWN";
  elements.competitionProviderAvailability.textContent = mode;
  if (payload.evidence_available === true) {
    const checked = payload.checked_at_utc || "unknown time";
    const model = payload.model || "unknown model";
    const reason = payload.reason ? ` · reason: ${payload.reason}` : "";
    elements.competitionProviderEvidence.textContent =
      `${payload.status || mode} · ${model} · checked ${checked}${reason} · read-only evidence.`;
  } else {
    elements.competitionProviderEvidence.textContent =
      `${payload.status || "UNAVAILABLE"} · no explicit provider-availability evidence configured.`;
  }
}

async function refreshProviderAvailability() {
  renderProviderAvailability(await jsonFetch("/api/provider-availability"));
}

function parseModelChoices(availableModels) {
  return (availableModels || []).map((line) => {
    const [aliasPart, modelPart] = line.split("->").map((item) => item.trim());
    return {
      label: aliasPart,
      value: modelPart,
    };
  });
}

function hydrateModelSelect(availableModels, currentModel) {
  const choices = parseModelChoices(availableModels);
  elements.modelSelect.innerHTML = "";
  for (const choice of choices) {
    const option = document.createElement("option");
    option.value = choice.value;
    option.textContent = `${choice.label} -> ${choice.value}`;
    option.selected = choice.value === currentModel;
    elements.modelSelect.appendChild(option);
  }

  if (!choices.some((choice) => choice.value === currentModel)) {
    const option = document.createElement("option");
    option.value = currentModel;
    option.textContent = currentModel;
    option.selected = true;
    elements.modelSelect.appendChild(option);
  }
  hydrateModelPicker(choices, currentModel);
}

function hydrateModelPicker(choices, currentModel) {
  elements.modelPicker.innerHTML = "";
  for (const choice of choices) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "model-pill";
    button.dataset.model = choice.value;
    button.textContent = choice.label;
    button.title = choice.value;
    button.setAttribute("aria-pressed", String(choice.value === currentModel));
    if (choice.value === currentModel) {
      button.classList.add("model-pill-active");
    }
    button.addEventListener("click", async () => {
      elements.modelSelect.value = choice.value;
      try {
        await switchModel();
      } catch (error) {
        elements.modelNote.textContent = String(error);
      }
    });
    elements.modelPicker.appendChild(button);
  }
}

async function switchModel() {
  invalidateCPLPlan('Model selection changed. Preview a new immutable plan.');
  state.modelSwitchPending = true;
  const model = elements.modelSelect.value;
  elements.modelNote.textContent = `Switching to ${model}…`;
  try {
    const payload = await jsonFetch("/api/model", {
    method: "POST",
    body: JSON.stringify({ model }),
    });
    elements.modelNote.textContent =
    payload.notice || `Assistant model switched to ${payload.model}. Evidence review remains local.`;
    applyStatus(payload.status);
    hydrateModelSelect(payload.status.available_models, payload.status.model);
  } finally {
    state.modelSwitchPending = false;
  }
}

async function sendPrompt(prompt) {
  addMessage("You", prompt);
  const payload = await jsonFetch("/api/chat", {
    method: "POST",
    body: JSON.stringify({ prompt, mode: document.querySelector('#assistant-mode').value }),
  });
  // A command or explicit bypass must never be labeled as a CPL final.
  if (payload.mode === 'cpl') throw new Error('Unexpected plan response; no unapproved final delivered.');
  addMessage(payload.mode === 'plain' ? 'AIOA spArkHAT · Plain Chat · NOT CPL reviewed' : 'Core command', payload.transcript);
  applyStatus(payload.status);
}

function setView(view) {
  for (const tab of document.querySelectorAll(".view-tab")) {
    const selected = tab.dataset.view === view;
    tab.classList.toggle("view-tab-active", selected);
    tab.setAttribute("aria-selected", String(selected));
  }
  document.querySelector("#assistant-view").hidden = view !== "assistant";
  document.querySelector("#review-view").hidden = view !== "review";
  elements.viewTitle.textContent = view === "review" ? "Dated evidence review" : "Assistant runtime";
}

function renderEvidence(evidence) {
  elements.reviewEvidence.innerHTML = "";
  const template = document.querySelector("#evidence-template");
  for (const source of evidence || []) {
    const node = template.content.firstElementChild.cloneNode(true);
    node.querySelector(".evidence-title").textContent = source.title;
    node.querySelector(".evidence-meta").textContent =
      `${source.publisher} · effective ${source.effective_from} · checked ${source.checked_at}`;
    node.querySelector(".evidence-fact").textContent = source.fact;
    const link = node.querySelector(".evidence-link");
    link.href = source.url;
    link.setAttribute("aria-label", `Open official source: ${source.title}`);
    elements.reviewEvidence.appendChild(node);
  }
}

async function loadReviewScenario() {
  const scenario = await jsonFetch("/api/review/scenario");
  state.scenario = scenario;
  elements.reviewScenarioTitle.textContent = scenario.title;
  elements.reviewScenarioMeta.textContent =
    `${scenario.jurisdiction} · ${scenario.domain} · ${scenario.risk_domain}`;
  elements.reviewPrompt.textContent = scenario.prompt;
  elements.reviewInput.value = scenario.candidate_answer;
  elements.reviewAsOf.textContent = `as of ${scenario.as_of_date}`;
  renderEvidence(scenario.evidence);
}

function readableStatus(status) {
  return String(status || "unknown")
    .toLowerCase()
    .split("_")
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

function renderReview(result) {
  elements.reviewValueStatus.textContent = readableStatus(result.value_status);
  elements.reviewDecision.textContent = readableStatus(result.decision_state);
  elements.reviewDecision.className = "badge badge-warning";
  elements.reviewCriticalCount.textContent = String(result.severity_counts.critical);
  elements.reviewWarningCount.textContent = String(result.severity_counts.warning);
  elements.reviewInfoCount.textContent = String(result.severity_counts.info);
  elements.reviewEvidenceDigest.textContent = result.evidence_digest;
  elements.reviewSnapshotHash.textContent = result.snapshot_hash;
  elements.reviewNextStep.textContent = result.operator_next_step;
  renderEvidence(result.evidence);

  elements.reviewFindings.innerHTML = "";
  const template = document.querySelector("#finding-template");
  for (const finding of result.findings) {
    const node = template.content.firstElementChild.cloneNode(true);
    node.classList.add(`finding-${finding.severity}`);
    const severity = node.querySelector(".finding-severity");
    severity.textContent = finding.severity;
    severity.classList.add(`severity-${finding.severity}`);
    node.querySelector(".finding-title").textContent = finding.title;
    node.querySelector(".finding-detail").textContent = finding.detail;
    elements.reviewFindings.appendChild(node);
  }
}

async function runReview() {
  const candidateAnswer = elements.reviewInput.value.trim();
  if (!candidateAnswer) {
    elements.reviewRequestStatus.textContent = "Candidate answer is required.";
    return;
  }
  elements.reviewRequestStatus.textContent = "Running deterministic comparison…";
  const result = await jsonFetch("/api/review", {
    method: "POST",
    body: JSON.stringify({ candidate_answer: candidateAnswer }),
  });
  renderReview(result);
  elements.reviewRequestStatus.textContent =
    `Completed locally as ${result.review_id}; no provider or network call was used.`;
}

document.querySelector("#switch-model").addEventListener("click", async () => {
  try {
    await switchModel();
  } catch (error) {
    elements.modelNote.textContent = String(error);
  }
});

document.querySelector("#refresh-status").addEventListener("click", async () => {
  try {
    await Promise.all([refreshStatus(), refreshAuthorityTimeline(), refreshCompetitionEvaluation(), refreshProviderAvailability()]);
  } catch (error) {
    addMessage("System", `Refresh failed: ${error}`);
  }
});

for (const tab of document.querySelectorAll(".view-tab")) {
  tab.addEventListener("click", () => setView(tab.dataset.view));
}

for (const button of document.querySelectorAll(".quick-action")) {
  button.addEventListener("click", () => {
    setView("assistant");
    elements.promptInput.value = button.dataset.prompt || "";
    elements.promptInput.focus();
  });
}

elements.composer.addEventListener("submit", async (event) => {
  event.preventDefault();
  const prompt = elements.promptInput.value;
  if (!prompt.trim() || state.cplRunning) {
    return;
  }
  if (document.querySelector('#assistant-mode').value === 'cpl' && !prompt.trimStart().startsWith('/')) {
    await previewCPL();
    return;
  }
  invalidateCPLPlan();
  try {
    await sendPrompt(prompt);
  } catch (error) {
    addMessage("System", `Request failed: ${error}`);
  }
});

elements.promptInput.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    elements.composer.requestSubmit();
  }
});

elements.reviewForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  try {
    await runReview();
  } catch (error) {
    elements.reviewRequestStatus.textContent = `Review failed: ${error}`;
  }
});

document.querySelector("#load-stale").addEventListener("click", () => {
  if (state.scenario) {
    elements.reviewInput.value = state.scenario.candidate_answer;
  }
});

document.querySelector("#load-corrected").addEventListener("click", () => {
  if (state.scenario) {
    elements.reviewInput.value = state.scenario.corrected_example;
  }
});

async function bootstrap() {
  try {
    state.sessionToken = (await jsonFetch('/api/session')).token;
  } catch (error) {
    addMessage('System', `Local session setup failed: ${error}`);
    return;
  }
  addMessage(
    "System",
    "AIOA spArkHAT is ready. Assistant, deterministic Evidence Review and Critical Prompt Loop use one local runtime."
  );
  const [statusResult, scenarioResult, timelineResult, evaluationResult, providerResult, cplPresetResult] = await Promise.allSettled([
    refreshStatus(),
    loadReviewScenario(),
    refreshAuthorityTimeline(),
    refreshCompetitionEvaluation(),
    refreshProviderAvailability(),
    refreshCPLPreset(),
  ]);
  if (statusResult.status === "rejected") {
    addMessage("System", `Runtime startup failed: ${statusResult.reason}`);
  }
  if (scenarioResult.status === "rejected") {
    elements.reviewRequestStatus.textContent = `Evidence registry failed to load: ${scenarioResult.reason}`;
  }
  if (timelineResult.status === "rejected") {
    elements.authorityTimelineSummary.textContent = `Authority timeline failed to load: ${timelineResult.reason}`;
  }
  if (evaluationResult.status === "rejected") {
    elements.competitionEvaluationSummary.textContent = `Competition evaluation failed to load: ${evaluationResult.reason}`;
  }
  if (providerResult.status === "rejected") {
    elements.competitionProviderEvidence.textContent = `Provider availability failed to load: ${providerResult.reason}`;
  }
  if (cplPresetResult.status === "rejected") {
    cplElement('preset-status').textContent = `Competition CPL preset failed to load: ${cplPresetResult.reason}`;
  }
}

function cplElement(id) {
  return document.querySelector(`#cpl-${id}`);
}

function setAssistantMode(mode) {
  if (!['cpl', 'plain'].includes(mode)) mode = 'cpl';
  if (state.cplRunning && mode !== 'cpl') {
    document.querySelector('#assistant-mode').value = 'cpl';
    cplElement('request-status').textContent = 'Cancel or finish the active CPL run before selecting Plain Chat.';
    return;
  }
  invalidateCPLPlan();
  document.querySelector('#assistant-mode').value = mode;
  cplElement('panel').hidden = mode !== 'cpl';
  elements.chatLog.hidden = false;
  elements.composer.hidden = false;
  document.querySelector('#assistant-submit').textContent = mode === 'cpl' ? 'Preview CPL plan' : 'Send · bypass CPL';
  document.querySelector('#assistant-mode-note').textContent = mode === 'cpl'
    ? 'CPL DEFAULT · Sending only previews a plan. Exactly five bounded requests require one-use approval. No automatic chat fallback.'
    : 'PLAIN CHAT BYPASS · Responses are NOT CPL reviewed. The existing Core routing, provider and action-approval policies still apply.';
  // No legacy preference can silently opt a fresh page into the old chat path.
}

function applyCPLStatus(status) {
  state.cplStatus = status;
  cplElement('mode').textContent = status.mode === 'TEST' ? 'TEST · local HTTP fixture' : 'LIVE · awaiting configuration and budget';
  cplElement('transport-note').textContent = status.mode === 'TEST'
    ? 'Synthetic responses travel through the real strict HTTP adapter on loopback. No cloud models or model API charges. Ordinary cloud chat is disabled in this explicit test session.'
    : `Live execution requires an enabled strict provider, an explicit cost policy, a run budget and approval of one immutable plan. Session budget: ${status.session_budget_usd || '0'} USD. No automatic fixture fallback.`;
  cplElement('load-fixture').disabled = status.mode !== 'TEST';
  cplElement('load-fixture').hidden = status.mode !== 'TEST';
  if (!state.cplRunId && status.run_ids && status.run_ids.length) {
    state.cplRunId = status.run_ids[status.run_ids.length - 1];
    jsonFetch(`/api/cpl/runs/${state.cplRunId}`).then(renderCPL).catch(cplError);
  }
}

function renderCPLPreset(preset) {
  state.cplPreset = preset;
  const mapping = [
    `primary ${preset.primary_model}`,
    ...(preset.observer_models || []).map((model, index) => `${preset.roles?.[index] || `observer-${index + 1}`} ${model}`),
  ].join(' · ');
  if (preset.scope === 'TEST') {
    cplElement('preset-status').textContent = `PREPARED · TEST fixture only · ${mapping}. Loading this preset does not call OpenRouter.`;
  } else if (preset.live_preconditions_ready) {
    cplElement('preset-status').textContent = `PREPARED · LIVE preconditions present · ${mapping}. Planning and one-use approval are still required before any provider call.`;
  } else {
    cplElement('preset-status').textContent = `PREPARED · LIVE NOT READY (${(preset.blocking_reasons || []).join(', ') || 'UNKNOWN'}) · ${mapping}. Loading only edits local form fields.`;
  }
}

async function refreshCPLPreset() {
  renderCPLPreset(await jsonFetch('/api/cpl/preset'));
}

function cplError(error) {
  cplElement('request-status').textContent = `CPL stopped: ${error}. The selected CPL mode has not fallen back to chat.`;
  cplElement('start').disabled = true;
}

function invalidateCPLPlan(message) {
  state.cplRevision += 1;
  state.cplPlan = null;
  cplElement('start').disabled = true;
  if (message) cplElement('request-status').textContent = message;
}

function setCPLBusy(running) {
  state.cplRunning = running;
  elements.promptInput.disabled = running;
  document.querySelector('#assistant-submit').disabled = running;
  for (const element of cplElement('plan-form').querySelectorAll('input,textarea,button')) element.disabled = running;
  cplElement('load-preset').disabled = running;
  if (state.cplStatus && state.cplStatus.mode !== 'TEST') cplElement('load-fixture').disabled = true;
}

function cplInputs() {
  const payload = {prompt: elements.promptInput.value, evidence: cplElement('evidence').value,
    run_budget_usd: cplElement('budget').value};
  const models = cplElement('models').value.split('\n').map(value => value.trim()).filter(Boolean);
  if (models.length) payload.models = models;
  if (cplElement('limits').value.trim()) payload.limits = JSON.parse(cplElement('limits').value);
  return payload;
}

function inputSignature() {
  // Includes raw fields and model selector, so even programmatic edits cannot
  // authorize a stale preview. The server separately verifies hash + nonce.
  return JSON.stringify([elements.promptInput.value, cplElement('evidence').value,
    cplElement('models').value, cplElement('limits').value, cplElement('budget').value,
    elements.modelSelect.value, document.querySelector('#assistant-mode').value]);
}

async function previewCPL() {
  if (state.cplRunning || state.modelSwitchPending) {
    cplError('Wait for the active run or model selection to finish.');
    return;
  }
  invalidateCPLPlan('Preparing a bounded plan; no generation has been authorized.');
  clearTimeout(state.cplPoll);
  const revision = state.cplRevision;
  const signature = inputSignature();
  try {
    const result = await jsonFetch('/api/chat', {method: 'POST',
      body: JSON.stringify({mode: 'cpl', ...cplInputs()})});
    if (revision !== state.cplRevision || signature !== inputSignature()) return;
    if (result.mode !== 'cpl' || result.cpl.execution_status !== 'PLANNED' || result.transcript !== null) {
      throw new Error('Invalid plan response; no generation authorized.');
    }
    const planned = result.cpl;
    state.cplPlan = {authorization: {run_id: planned.run_id, plan_hash: planned.plan_hash, nonce: planned.nonce}, signature};
    renderCPL(planned);
    cplElement('start').textContent = planned.plan.scope === 'TEST' ? 'Authorize TEST plan and run fixture' : 'Approve displayed budget and run LIVE plan';
    cplElement('start').disabled = false;
  } catch (error) {
    if (revision === state.cplRevision) cplError(error);
  }
}

function pollCPL(runId) {
  jsonFetch(`/api/cpl/runs/${runId}`).then(result => {
    if (state.cplRunId === runId) renderCPL(result);
  }).catch(error => { if (state.cplRunId === runId) cplError(error); });
}

function renderCPL(result) {
  state.cplRunId = result.run_id;
  if (result.approval && !state.cplAsked.has(result.run_id)) {
    addMessage('You', result.plan.prompt);
    state.cplAsked.add(result.run_id);
  }
  const terminal = ['COMPLETED', 'FAILED', 'CANCELLED', 'INTERRUPTED'].includes(result.execution_status);
  cplElement('state').textContent = result.execution_status;
  cplElement('run-id').textContent = `${result.run_id} · requests ${result.generation_requests}/5 · ${result.authority}`;
  cplElement('draft').textContent = result.draft || 'Not available';
  cplElement('final').textContent = result.execution_status === 'COMPLETED' ? result.final_answer : 'Not delivered';
  if (result.execution_status === 'COMPLETED' && !state.cplDelivered.has(result.run_id)) {
    const finalNode = addMessage(`AIOA spArkHAT · ${result.plan.scope === 'TEST' ? 'TEST fixture · ' : ''}CPL final · advisory / human review required`, result.final_answer);
    finalNode.dataset.cplRunId = result.run_id;
    state.cplDelivered.add(result.run_id);
  }
  cplElement('conflicts').textContent = JSON.stringify({conflicts: result.conflicts,
    uncertainty: (result.reviews || []).flatMap(review => review.uncertainty || [])}, null, 2);
  cplElement('reviews').replaceChildren();
  const roles = result.plan.roles;
  roles.forEach((role, index) => {
    const card = document.createElement('section');
    card.className = 'cpl-stage';
    const title = document.createElement('h4');
    title.textContent = `${index + 1}. ${role}`;
    const body = document.createElement('pre');
    body.className = 'cpl-data';
    body.textContent = result.reviews[index] ? JSON.stringify(result.reviews[index], null, 2) : 'Not completed';
    card.append(title, body);
    cplElement('reviews').appendChild(card);
  });
  cplElement('trace').textContent = JSON.stringify({manifest: result.evidence_chain,
    snapshot_hash: result.snapshot_hash, providers: result.provider_results,
    approval: result.approval, live_provider_status: result.live_provider_status}, null, 2);
  cplElement('plan-preview').textContent = JSON.stringify({plan_hash: result.plan_hash, plan: result.plan}, null, 2);
  cplElement('cancel').disabled = terminal;
  cplElement('verify').disabled = !terminal;
  const running = !terminal && result.execution_status !== 'PLANNED';
  setCPLBusy(running);
  if (result.error) cplError(result.error);
  else cplElement('request-status').textContent = result.execution_status === 'COMPLETED'
    ? 'Run complete. Review the draft, three reports and final revision. Completion is not proof of truth.'
    : (running ? 'Bounded worker is running. Status and cancel remain responsive.' : 'Inspect the exact plan before starting.');
  clearTimeout(state.cplPoll);
  if (running) {
    state.cplPoll = setTimeout(() => pollCPL(result.run_id), 180);
  }
}

document.querySelector('#assistant-mode').addEventListener('change', event => setAssistantMode(event.target.value));
const changedCPLInput = () => invalidateCPLPlan('Input changed. Preview a new immutable plan; the previous approval cannot authorize these changes.');
cplElement('plan-form').addEventListener('input', changedCPLInput);
elements.promptInput.addEventListener('input', changedCPLInput);
elements.modelSelect.addEventListener('change', changedCPLInput);
cplElement('load-preset').addEventListener('click', () => {
  if (!state.cplPreset || state.cplRunning) return;
  invalidateCPLPlan();
  cplElement('models').value = state.cplPreset.models.join('\n');
  cplElement('budget').value = state.cplPreset.scope === 'LIVE'
    ? state.cplPreset.run_budget_usd_suggestion : '0';
  cplElement('limits').value = '';
  cplElement('options').open = true;
  invalidateCPLPlan('Competition OpenRouter preset loaded locally. No provider call occurred; preview a new immutable plan before any authorization.');
});

cplElement('load-fixture').addEventListener('click', async () => {
  invalidateCPLPlan();
  const revision = state.cplRevision;
  try {
    const fixture = await jsonFetch('/api/cpl/fixture');
    if (revision !== state.cplRevision) return;
    elements.promptInput.value = fixture.prompt;
    cplElement('evidence').value = fixture.evidence;
    cplElement('models').value = Array(4).fill(fixture.model).join('\n');
    cplElement('budget').value = '0';
    cplElement('limits').value = '';
    invalidateCPLPlan();
    cplElement('request-status').textContent = 'Synthetic dated example loaded. Preview the plan, then explicitly start the fixture.';
  } catch (error) { cplError(error); }
});
cplElement('plan-form').addEventListener('submit', async event => {
  event.preventDefault();
  await previewCPL();
});
cplElement('start').addEventListener('click', async () => {
  if (!state.cplPlan) return;
  if (state.cplPlan.signature !== inputSignature() || state.modelSwitchPending) {
    changedCPLInput();
    return;
  }
  const authorization = state.cplPlan.authorization;
  invalidateCPLPlan();
  setCPLBusy(true);
  try {
    renderCPL(await jsonFetch('/api/cpl/start', {method: 'POST', body: JSON.stringify(authorization)}));
  } catch (error) {
    cplError(error);
    // A lost HTTP response is not proof that the server did not start. Read
    // status; never retry start or unlock into a silent Plain Chat bypass.
    pollCPL(authorization.run_id);
  }
});
cplElement('cancel').addEventListener('click', async () => {
  clearTimeout(state.cplPoll);
  try {
    renderCPL(await jsonFetch('/api/cpl/cancel', {method: 'POST', body: JSON.stringify({run_id: state.cplRunId})}));
  } catch (error) { cplError(error); }
});
cplElement('verify').addEventListener('click', async () => {
  try {
    const result = await jsonFetch(`/api/cpl/runs/${state.cplRunId}/trace`);
    cplElement('trace').textContent = JSON.stringify(result, null, 2);
    cplElement('request-status').textContent = result.ok
      ? 'Evidence Chain verified against the local manifest. This is integrity, not truth or external time attestation.'
      : 'Evidence Chain verification FAILED. Do not trust the stored run.';
    cplElement('trace').closest('details').open = true;
    cplElement('inspector').open = true;
  } catch (error) { cplError(error); }
});

setAssistantMode('cpl');
bootstrap();
