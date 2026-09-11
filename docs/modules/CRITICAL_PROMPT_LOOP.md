# Critical Prompt Loop contract — AIOA spArkHAT

Contract `cpl-1plus3plus1-v1`; prompt `desktop-5ec74f8-cpl-v1`.

```text
PLANNED --one-use hash/nonce approval--> AUTHORIZED
  -> DRAFTING -> REVIEWING_1 -> REVIEWING_2 -> REVIEWING_3
  -> REVISING -> COMPLETED
Any execution failure -> FAILED; operator cancel -> CANCELLED
Unfinished state reopened after process exit -> INTERRUPTED (no replay)
```

The draft and final revision use the same captured primary OpenRouter model. Three critics have exact roles in order: `Logic & Claims`, `Safety & Authority`, `Evidence & Consistency`. They may share one model, which is explicitly recorded. Critics 2/3 receive bounded earlier report metadata plus the same immutable snapshot, so this is mutually informed review, not independent consensus. Negative findings are valid completed reviews; malformed reports/provider failures stop the loop. There are no repair calls, retries, parallel critics or fallback substitutions.

## Plan, execution and identity

A canonical JSON plan binds prompt, quoted evidence/source references, four exact model IDs, three roles, per-stage limits, scope and cost policy, creation/expiry and the ordered five-call sequence. Hash and random nonce must both match. The server consumes the nonce atomically, once, with a five-minute default expiry. Model selection elsewhere cannot mutate a plan. Editing UI inputs invalidates the pending local approval. `approved=true` is not authorization.

Draft/revision output maxima: 1024 each; each critic: 512; total requested output maximum: 3584. Conservative input admission units are UTF-8 bytes plus message/schema framing, capped at 32768 per request. This is not measured model usage. Success/error HTTP bodies are capped at 65536 bytes; call timeout defaults to 20 seconds (hard maximum 30), run deadline 120 (hard maximum 180). Limits may be reduced. Response identity must be present and exactly match; choices must contain one complete text answer with finish reason `stop`. Actual usage, when absent, remains null/missing, never an invented zero. Complete usage above caps fails closed after receipt.

Only `ProviderManager.generate_exact` is used. LIVE binds to the real HTTPS OpenRouter endpoint; TEST is explicitly injected loopback HTTP. Direct `http.client` transport has no automatic redirects, proxies, retry or fallback. No key is loaded for the explicit fixture; ordinary cloud generation is blocked in that mode. Other providers are not supported for strict CPL until their identity/limits contract is implemented and tested.

Call/run watchdogs close active sockets and terminate the visible run at its deadline, including trickling HTTP headers. System DNS resolution cannot be forcibly interrupted by Python socket cancellation; if it finishes late, a pre-send check rejects the request. A terminal run never starts another generation, and a still-cleaning worker keeps the single-worker slot reserved. This OS-level latency and real TLS/provider behavior are not certified by the loopback fixture.

## Cost boundary

LIVE is off by default. An operator-authored policy and positive session/run budgets are required. Every chosen model must have a timestamped USD input/output quote (maximum age 24 hours), bound into the plan with `utf8-bytes-plus-framing-v1`. Unknown or stale prices and unsupported/automatic model IDs fail closed. Admission reserves an upper estimate for all five requests, including full input caps and output caps. Reservations are not refunded after uncertain transport/cancellation. This is conservative admission, **not a billing guarantee**: provider pricing, tokenization, server-side execution after cancellation and reporting are external facts. Validate real prices/limits before authorizing live. Session reservation is process-local; a new process is a new explicitly authorized session, not an automatic continuation of unused budget.

## Local interfaces

| Surface | Contract |
| --- | --- |
| `/cpl plan PROMPT` | CLI preview; emits a nonce for explicit subsequent start in the same process |
| `/cpl plan-json JSON` | Same preview with explicit evidence, four models, limits and per-run budget |
| `/cpl start ID HASH NONCE` | Start and wait for terminal transport cleanup |
| `/cpl status [ID]`, `/cpl cancel ID` | Read/cancel without tools or provider generation |
| `/cpl verify ID` | Verify persisted trace without model calls |
| `/cpl fixture` | Explicit TEST plan/start flow; fails if session is not fixture mode |
| `GET /api/session` | Same-origin loopback session token |
| `POST /api/cpl/plan` | Validated plan; no model request |
| `POST /api/cpl/start` | Exactly `run_id`, `plan_hash`, `nonce` |
| `GET /api/cpl/status`, `/api/cpl/runs/ID` | Worker/status snapshot |
| `POST /api/cpl/cancel` | Exactly `run_id`; local cancellation is responsive |
| `GET /api/cpl/runs/ID/trace` | Local manifest verifier |
| `POST /api/cpl/verify` | Exactly `run_id`, retained external `manifest` |

Loopback bind only. Host, supplied Origin and session token are checked; absent Origin does not waive the token. Body maximum 24000 bytes; duplicate JSON keys/nonfinite numbers and conflicting framing are rejected. No wildcard CORS. A bounded single worker leaves status/cancel responsive. `/api/chat` refuses CPL execution and cannot substitute for plan/start. The UI uses text nodes, not HTML, for all model content. This is not a public/multi-user authentication design; local processes able to read the session endpoint are inside the local operator trust boundary.

## Evidence Chain and authority

Shared provenance records include ordered event IDs, run/trace IDs, sequence, phase, payload/previous/entry hashes, UTC local timestamp and source description, canonicalization/redaction versions, base implementation commit, plan, configuration, evidence references, requested/reported identity and actual approval scope. Secrets are redacted **before** persistence and hashing. The nonce/token are not persisted in the shareable trace.

The exportable manifest has run ID, event count and terminal hash. The verifier detects edits, reorder/removal/foreign events and tail truncation relative to a retained manifest. An actor who can rewrite both log and local manifest can construct a consistent chain. External retained head/count is needed to detect that rollback; hashes do not prove truth, authorship, trusted time or originality. No external timestamp publication or new signing identity is used.

Quotas: 64 runs, 24 events/run, 2 MiB/run, 64 MiB total (admission reserves room). Trace paths reject symlinks; logs/manifests are private. One process owns each trace root. Completed views reopen after restart; unfinished views become INTERRUPTED without provider replay. Verify/export before manually managing a full trace directory; no automatic deletion is implemented.

`TRACE_PERSISTENCE=ENABLED`, `KNOWLEDGE_PROMOTION=DISABLED`, `MODEL_TRAINING=NONE`, `authority=ADVISORY_ONLY`. CPL never invokes executor, shell, approval, database migrations or Memory Patch. Drafts and reports are untrusted data. A future human-reviewed candidate interface is documentation only; no activation backend exists here. The deterministic dated `/review` remains a separate provider-free engine.
