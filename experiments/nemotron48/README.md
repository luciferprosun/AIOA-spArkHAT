# NEMOTRON 48H — Data Sniffer (AIOA spArkHAT)

**Status: experimental code committed on isolated branch. NOT a LIVE 48-hour run.**
The module uses only Python 3.11+ standard library. No second AIOA Core, no heavy model runtime, no daemon, no deployment.

## Implemented structure

This is a finite Web Design/documentation mission with official-source admission, opt-in HTTPS/robots-aware link discovery, bounded text extraction, source SHA-256, deduplication, owner-scoped SQLite candidate index, SHADOW pheromone tags, local event hash chain, checkpoint head, STOP, manual resume, export and status reports. An optional exact-model Nebius/OpenRouter summarizer requires separate network and cost authorization, timestamped prices, reserved budget and response model-identity validation. Candidates are never trained into an LLM or promoted into trusted HAT automatically.

- policy.py: HTTPS official-site allowlist, public DNS, private state-dir gate
- transport.py: TLS verification, pinned public-address sockets, no redirects/proxies/retries, robots, MIME and byte caps
- extract.py: inert HTML parser, bounded links, metadata and tags
- storage.py: private SQLite, event receipts, SHADOW knowledge, per-user pheromone tags and budget reservations
- mission.py: bounded research scheduler; STOP, resume and UNKNOWN handling
- model.py: optional disabled-by-default exact-model inference adapter
- __main__.py: operator CLI
- fixtures: synthetic documents only, not copies of official pages

## Safe OFFLINE test (no internet and no API charges)

From a clean copy of the repository root:

~~~sh
python3 -m unittest discover -s experiments/nemotron48/tests -v
STATE="/var/tmp/aioa-nemotron48-$(id -u)"
python3 -m experiments.nemotron48 init --state-dir "$STATE" --owner-scope local_research_user
python3 -m experiments.nemotron48 run --state-dir "$STATE" --max-items 30
python3 -m experiments.nemotron48 status --state-dir "$STATE"
python3 -m experiments.nemotron48 verify --state-dir "$STATE"
python3 -m experiments.nemotron48 export --state-dir "$STATE"
~~~

Use a new private /var/tmp path for each fresh initialization. Reusing an already initialized state fails closed. The synthetic run may finish early (DONE_EARLY_NOT_48H), which is correct and does NOT certify 48 hours of autonomous learning.

## LIVE public document research (a separate human-controlled step)

Network mode is never the default. With independently verified storage, permission to retrieve official public docs, crawl/robots policy and a fresh sandbox, the operator may later choose:

~~~sh
python3 -m experiments.nemotron48 run --state-dir /var/tmp/aioa-nemotron48-APPROVED \
  --live-network --authorize-network --max-items 10
~~~

An existing fixture mission cannot switch to LIVE. A paused mission needs an explicit --resume. There is no general search engine, credentialed scraping or web-account takeover. Unsupported pages, PDFs, redirections, private IPs and disallowed robots paths are rejected.

Optional paid Nemotron / OpenRouter summarization requires ADDITIONAL explicit paid authorization, an exact verified model ID, provider origin, official cost quote not older than 24h, both per-million-token prices, a positive total budget no greater than USD 10, a call cap, and the privately supplied NEMOTRON48_API_KEY. Use --enable-live-model and --authorize-paid together with live-network gates. No secret must enter Git, build artifacts or printed commands. Unknown billing liabilities remain reserved; no blind retry or fallback. Source content sent to a remote model is limited and must satisfy the operator's egress policy.

## Safety and HAT boundary

V1 intentionally refuses state directories on /media, /mnt, /home, USB and the LSC drive (previous storage errors have not been resolved and independently certified). Only a fresh private directory under /tmp or /var/tmp is accepted. Inspect local disk space and health first. Do not bypass this guard to reach external storage. A future LSC adapter will require a separate UUID/health gate and owner decision.

All stored candidates are UNVERIFIED_SHADOW with owner scope, evidence hash, source URL, tag namespace web-design/experimental and disabled HAT promotion. Local hash chain and head.json can detect changes relative to the retained head, but are not external proof of truth or trusted time. The user must review source, rights and accuracy before any future knowledge migration.

STOP marker is checked between bounded work units; failure, ambiguous paid model attempts or an interrupted request may require manual reconciliation. No autostart, Core mutation, MCP WRITE/EXEC, GitHub push, browser control or public release is granted by the experimental model.

## Evidence status

Implementation source is present on the isolated branch. OFFLINE tests must be run on the exact branch SHA before certification. The branch is **not** evidence of 48-hour LIVE Nemotron work, new training weights, validated source originality, trusted knowledge promotion or production readiness.

## New supervised mode and GitHub Actions

The optional `supervise` CLI runs bounded segments on a single authorized host, validates the journal between segments and always leaves certification to the independent `audit` command. It refuses LIVE when the emergency email gate is not configured. `alert-status` reads its configuration status without sending a message. Each critical SMTP alert is one-use and requires Natalia's separately confirmed consent; actual SMTP server acceptance is not proof of receipt. No recipient address is stored in this public repository.

A push-triggered **OFFLINE-only** GitHub Actions workflow lives at `.github/workflows/nemotron48-offline-ci.yml`. The workflow runs synthetic fixtures and exports sanitized synthetic evidence. See `OPERATIONS_RUNBOOK_PL.md` for required LIVE gates, architecture and why the standard GitHub-hosted runner cannot provide a genuine uninterrupted 48-hour test by itself.
