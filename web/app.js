const state = {
  currentModel: "",
  scenario: null,
  sessionToken: null,
  cplPlan: null,
  cplStatus: null,
  cplPoll: null,
  cplRunId: null,
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
  elements.chatLog.appendChild(node);
  elements.chatLog.scrollTop = elements.chatLog.scrollHeight;
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
  const model = elements.modelSelect.value;
  elements.modelNote.textContent = `Switching to ${model}…`;
  const payload = await jsonFetch("/api/model", {
    method: "POST",
    body: JSON.stringify({ model }),
  });
  elements.modelNote.textContent =
    payload.notice || `Assistant model switched to ${payload.model}. Evidence review remains local.`;
  applyStatus(payload.status);
  hydrateModelSelect(payload.status.available_models, payload.status.model);
}

async function sendPrompt(prompt) {
  addMessage("You", prompt);
  const payload = await jsonFetch("/api/chat", {
    method: "POST",
    body: JSON.stringify({ prompt }),
  });
  addMessage("AIOA spArkHAT", payload.transcript);
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
    await refreshStatus();
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
  if (document.querySelector('#assistant-mode').value === 'cpl') {
    document.querySelector('#cpl-request-status').textContent = 'CPL remains active. Use Preview immutable plan; ordinary chat is not a fallback.';
    return;
  }
  const prompt = elements.promptInput.value.trim();
  if (!prompt) {
    return;
  }
  elements.promptInput.value = "";
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
  const [statusResult, scenarioResult] = await Promise.allSettled([
    refreshStatus(),
    loadReviewScenario(),
  ]);
  if (statusResult.status === "rejected") {
    addMessage("System", `Runtime startup failed: ${statusResult.reason}`);
  }
  if (scenarioResult.status === "rejected") {
    elements.reviewRequestStatus.textContent = `Evidence registry failed to load: ${scenarioResult.reason}`;
  }
  setAssistantMode(localStorage.getItem('aioa-assistant-mode') === 'cpl' ? 'cpl' : 'chat');
}

function cplElement(id) {
  return document.querySelector(`#cpl-${id}`);
}

function setAssistantMode(mode) {
  document.querySelector('#assistant-mode').value = mode;
  cplElement('panel').hidden = mode !== 'cpl';
  elements.chatLog.hidden = mode === 'cpl';
  elements.composer.hidden = mode === 'cpl';
  localStorage.setItem('aioa-assistant-mode', mode);
}

function applyCPLStatus(status) {
  state.cplStatus = status;
  cplElement('mode').textContent = status.mode === 'TEST' ? 'TEST · local HTTP fixture' : 'LIVE · awaiting configuration and budget';
  cplElement('transport-note').textContent = status.mode === 'TEST'
    ? 'Synthetic responses travel through the real strict HTTP adapter on loopback. No cloud models or model API charges. Ordinary cloud chat is disabled in this explicit test session.'
    : `Live execution requires an enabled strict provider, an explicit cost policy, a run budget and approval of one immutable plan. Session budget: ${status.session_budget_usd || '0'} USD. No automatic fixture fallback.`;
  cplElement('load-fixture').disabled = status.mode !== 'TEST';
  if (!state.cplRunId && status.run_ids && status.run_ids.length) {
    state.cplRunId = status.run_ids[status.run_ids.length - 1];
    jsonFetch(`/api/cpl/runs/${state.cplRunId}`).then(renderCPL).catch(cplError);
  }
}

function cplError(error) {
  cplElement('request-status').textContent = `CPL stopped: ${error}. The selected CPL mode has not fallen back to chat.`;
  cplElement('start').disabled = true;
}

function renderCPL(result) {
  state.cplRunId = result.run_id;
  const terminal = ['COMPLETED', 'FAILED', 'CANCELLED', 'INTERRUPTED'].includes(result.execution_status);
  cplElement('state').textContent = result.execution_status;
  cplElement('run-id').textContent = `${result.run_id} · requests ${result.generation_requests}/5 · ${result.authority}`;
  cplElement('draft').textContent = result.draft || 'Not available';
  cplElement('final').textContent = result.execution_status === 'COMPLETED' ? result.final_answer : 'Not delivered';
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
  for (const element of cplElement('plan-form').querySelectorAll('input,textarea,button')) element.disabled = running;
  if (state.cplStatus && state.cplStatus.mode !== 'TEST') cplElement('load-fixture').disabled = true;
  if (result.error) cplError(result.error);
  else cplElement('request-status').textContent = terminal
    ? 'Run complete. Review the draft, three reports and final revision. Completion is not proof of truth.'
    : (running ? 'Bounded worker is running. Status and cancel remain responsive.' : 'Inspect the exact plan before starting.');
  if (running) {
    clearTimeout(state.cplPoll);
    state.cplPoll = setTimeout(() => jsonFetch(`/api/cpl/runs/${result.run_id}`).then(renderCPL).catch(cplError), 180);
  }
}

document.querySelector('#assistant-mode').addEventListener('change', event => setAssistantMode(event.target.value));
cplElement('plan-form').addEventListener('input', () => {
  if (state.cplPlan) {
    state.cplPlan = null;
    cplElement('start').disabled = true;
    cplElement('request-status').textContent = 'Input changed. Preview a new immutable plan; the previous approval cannot authorize these changes.';
  }
});
cplElement('load-fixture').addEventListener('click', async () => {
  try {
    const fixture = await jsonFetch('/api/cpl/fixture');
    cplElement('prompt').value = fixture.prompt;
    cplElement('evidence').value = fixture.evidence;
    cplElement('models').value = Array(4).fill(fixture.model).join('\n');
    cplElement('budget').value = '0';
    state.cplPlan = null;
    cplElement('start').disabled = true;
    cplElement('request-status').textContent = 'Synthetic dated example loaded. Preview the plan, then explicitly start the fixture.';
  } catch (error) { cplError(error); }
});
cplElement('plan-form').addEventListener('submit', async event => {
  event.preventDefault();
  clearTimeout(state.cplPoll);
  state.cplPlan = null;
  cplElement('start').disabled = true;
  try {
    const models = cplElement('models').value.split('\n').map(value => value.trim()).filter(Boolean);
    const payload = {prompt: cplElement('prompt').value, evidence: cplElement('evidence').value,
      run_budget_usd: cplElement('budget').value};
    if (models.length) payload.models = models;
    const result = await jsonFetch('/api/cpl/plan', {method: 'POST', body: JSON.stringify(payload)});
    state.cplPlan = {run_id: result.run_id, plan_hash: result.plan_hash, nonce: result.nonce};
    renderCPL(result);
    cplElement('start').textContent = result.plan.scope === 'TEST' ? 'Authorize TEST plan and run fixture' : 'Approve displayed budget and run LIVE plan';
    cplElement('start').disabled = false;
  } catch (error) { cplError(error); }
});
cplElement('start').addEventListener('click', async () => {
  if (!state.cplPlan) return;
  const authorization = state.cplPlan;
  state.cplPlan = null;
  cplElement('start').disabled = true;
  try {
    renderCPL(await jsonFetch('/api/cpl/start', {method: 'POST', body: JSON.stringify(authorization)}));
  } catch (error) { cplError(error); }
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
  } catch (error) { cplError(error); }
});

bootstrap();
