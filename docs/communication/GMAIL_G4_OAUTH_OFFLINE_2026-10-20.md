# AIOA Gmail Gateway — G4 Desktop OAuth offline preparation

**Date:** 2026-10-20  
**Target branch:** feature/aioa-gmail-gateway  
**Status:** OFFLINE CONTRACT PASS; LIVE GMAIL / AUTHORIZATION / TOKEN EXCHANGE BLOCKED.

## What was built

- runtime/communication/gmail/oauth_native.py: pure Python standard-library Google Desktop OAuth client-metadata parser, fail-closed scope limited to gmail.send, cryptographic PKCE S256 code challenge, random one-use state, loopback callback URI bound exactly to 127.0.0.1:ephemeral-port/oauth2callback, 180-second monotonic lifetime, and strict parser for the returned callback.
- New file does NOT launch the browser, start a loopback listener, request or exchange an OAuth token, read any local client files, access keyring, open a network connection, approve sending, or access Gmail data.
- Synthetic desktop client export parsing ignores client secrets and does not retain them. Google AI/Gemini API keys or Web OAuth client configurations are NOT accepted as Desktop OAuth client IDs.
- Callback is single-use even across concurrent calls; secrets are removed from the completed session. Ticket and session repr are redacted. Authorization code and verifier remain memory-only data destined for a future reviewed exchange flow.
- No data retrieved from an actual Gmail mailbox and no account connected.

## Verification evidence

- RED: new OAuth tests initially failed due to missing module.
- GREEN: 21/21 OAuth tests on Python 3.12.
- Hardened callback: removed public test-time override of monotonic clock, rejected malformed client-secret type and invalid UTF-8 in callback, checked same-state concurrency.
- Final isolated Python 3.12 combined test run: **88 PASS, 0 FAIL, 0 ERROR, 0 SKIP** (64 previously qualified G3 methods + 24 new G4 methods); result OK, measured unittest runtime approximately 5 seconds.
- Existing seven changed G3 source/test file Git blobs were matched to the prior GitHub source commit 149d6aa3abadadc3ece62fcde9541ff1faa54224 before this combined run.
- G4 new file blobs verified against local git hash-object: oauth_native.py 1583bca903557e554c6888fdd81ff50464a1376b; test_gmail_oauth_native.py 58473df68d571282827d84bebd3ebf659229f143.
- Work executed through ChatGPT Android control using a small, isolated scratch directory; no Codex agent session, sprint34, GOLD72 or production runtime changed.
- This is a **focused source-slice qualification** (not full AIOA repo regression or independent C1 security acceptance).

## Existing Google configuration discovery

Metadata-only inspection of the named LSC project locations and adjacent connector scratch directories found **no identifiable Gmail Desktop OAuth client export**. No secret values or tokens were read. This does not establish that no Google credentials exist elsewhere or that any Google AI key is invalid for its own original purpose. A generic Google/Gemini API key cannot authorize reading/sending Gmail without per-account OAuth consent.

## Safety boundaries and next gates

1. The returned code/verifier ticket is untrusted data without a token exchange; it cannot grant Core effect authority or Gmail access.
2. The future OAuth implementation must use an officially supported and independently reviewed Google client library for token exchange, current OAuth policy verification, a Linux-only credential store and explicit user consent. Tokens may never enter GitHub, Android model context or plain logs.
3. No live HTTP Gmail sender is installed; no actual AIOA Core owner warrant or STOP/nonce binding has been added. The previous public approval fixture test key never grants real authority.
4. An independent read-only C1 security review of prior G3 and new G4 source plus a complete on-target project regression are still required.
5. Later owner work: choose a dedicated Google Cloud project, enable Gmail API, configure an External Testing consent screen with the intended account as test user, create a Desktop OAuth client. Store its JSON in a private Linux-only path; do NOT paste secrets into chat.
6. Scope remains gmail.send only. Reading selected replies with gmail.readonly is a separate restricted-scope/privacy gate.
7. No automatic resend after UNKNOWN_SEND. No real OAuth consent, Google networking, emailing, account linking, Chromium, main merge or new GOLD72 execution authorized by these tests.

## Official primary sources

- https://developers.google.com/identity/protocols/oauth2/native-app
- https://developers.google.com/workspace/gmail/api/auth/scopes
- https://developers.google.com/identity/protocols/oauth2/resources/oob-migration

**Verdict: G4 OAuth intent/callback preparation implemented and Python 3.12 focused tests PASS; real account connection and external effects remain BLOCKED.**
