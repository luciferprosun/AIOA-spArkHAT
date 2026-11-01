# META-P1-04 Network Threat Review (OFFLINE)

- task_id: META-P1-04
- phase_status: PASS (audit PASS; G2-LIVE BLOCKED)
- source_sha: 6180941b1043d5ac425869e16b8ad353f60d253c
- changed_files:
  - tests/test_meta_p1_network_vectors.py
  - docs/meta/META_P1_04_NETWORK_THREAT_REVIEW.md
- tests: PYTHONDONTWRITEBYTECODE=1 python3 -B -m unittest discover -s tests -p 'test_meta_p1_*.py' -q
- cost: UNKNOWN
- next_gate: META-P1-05 remains OWNER_APPROVAL_REQUIRED; no automatic next.

## 1. Function-by-function threat mapping

### contracts.valid_page_url / _url_parts (syntactic URL gate)
Checks: https-only, no userinfo/port/query/fragment/`@%#?\`, no literal IP host,
2+ DNS labels, TLD regex, blocked suffixes (.local/.localhost/.internal/.onion/
.lan/.home/.arpa/.test/.example/.invalid), strict path charset, no `//`/`.`/`..`,
origin allowlist match.
Gaps (no bypass; proposed patch only): normalization is syntactic, not
canonical — no punycode/IDNA-vs-display analysis, no case/percent/dot-segment
canonicalization beyond rejection, no open-redirect or redirect-chain review,
no subresource/iframe/service-worker/download/cookie/header/tab/profile model.
Treat model/web content as untrusted: never derive scope from page text.
FINDING F1: open-redirect targets inside allowed origin are not distinguished
from planned navigation at this layer. Proposed patch (P1-05): exact
target_url pin + per-request/redirect revalidation in Core route handler.
FINDING F2: no Chromium controls exist here. Proposed: real-profile, tab,
click/submit, screenshot/provenance controls must be defined in P1-05 LIVE plan.

### network_admission._public_ips (DNS answer preview)
Checks: 1-16 string answers, each parses via ipaddress; denies
is_multicast/is_unspecified/is_loopback/is_link_local FIRST, then requires
is_global; rejects IPv4-mapped IPv6. No network calls.
Covers: loopback/private/link-local/reserved/unspecified/multicast (v4+v6:
ff02::1, ff0e::1, 224.0.0.1, 239.255.255.250), mapped, mixed safe+multicast,
metadata 169.254.169.254, empty/malformed.
SECURITY BUG (ChatGPT independent QA): ip.is_global is True for multicast
(ff02::1, 224.0.0.1, 239.255.255.250, ff0e::1), so the prior is_global-only
gate admitted them as safe. Previous first iteration was FIX_REQUIRED and
had deleted ff02::1 from the rejected vector to go green (99/99 before
multicast fix). Muse QA1 patch: explicit is_multicast deny before the
global check + negative regression vectors in both suites; valid public
unicast stays preview-only (CORE_AND_EGRESS_POLICY_REQUIRED,
dispatch_allowed=False), never authorized.
Gaps: TOCTOU/IP rebinding — Python preview does NOT establish OS network
containment; real browser may re-resolve. FINDING F3: no egress enforcement.
No LIVE Chromium run here; no OS egress enforcement claimed. Proposed
patch: OS/process-level egress allowlist + per-request DNS re-check in
Chromium route handler (P1-05, OWNER_APPROVAL_REQUIRED).

### network_admission.review_browser_network
Order: STOP -> expiry -> non-GET deny -> subresource/non-main-frame deny ->
credentials deny -> scope -> exact target_url pin -> DNS preview. Always
dispatch_allowed=False (DENY or CORE_AND_EGRESS_POLICY_REQUIRED).
Threat coverage: non-GET, credentialed, subresource/iframe, cross-origin,
wrong-path same-origin, STOP/expired, private IPs incl. IPv6/mapped.
Missing real-Chromium controls: cookies/headers, downloads, service workers
(denied here as non-document), multiple tabs, personal profile, click/submit,
screenshots/provenance — none exist in this offline module; must NOT be
claimed.

### offline_state.OfflineTaskState (synthetic state machine)
preview: NEW->PREVIEWED/STOPPED/DENIED/TIMED_OUT; observe: digest+scope+clock
checks; follow_redirect: scope revalidation only, DENIED on out-of-scope,
stays PREVIEWED otherwise (does not auto-navigate). dispatch_allowed always
False; environment always OFFLINE_FIXTURE.

## 2. Risk / STOP matrix

| Vector | Verdict | Reason |
|---|---|---|
| non-GET | DENY | NON_GET_DENIED |
| credentials | DENY | CREDENTIALS_DENIED |
| private/loopback/link-local/metadata IPv4/IPv6/mapped | DENY | UNSAFE_DNS_RESPONSE |
| cross-origin redirect | DENY | DENIED (state machine) |
| same-origin wrong path | DENY | UNPLANNED_NAVIGATION_DENIED |
| STOP / expired | DENY | STOP / TASK_EXPIRED / TIMED_OUT |
| subresource/iframe/service-worker | DENY | SUBRESOURCE_OR_FRAME_DENIED |
| would-be allowed | NO DISPATCH | CORE_AND_EGRESS_POLICY_REQUIRED, dispatch_allowed=False |

STOP/cancel: review(stopped=True)->STOP; state preview/observe stop()->STOPPED.
Screenshots/provenance: no browser; observations are UNVERIFIED candidates.

## 3. Missing isolation gate (P1-05 LIVE checklist, BLOCKED)
DO NOT perform or authorize LIVE. Required before any LIVE:
1. OS/process network isolation: dedicated browser UID/netns, default-deny
egress firewall allowing only resolved-in-scope IPs, no host profile (fresh
ephemeral profile), single tab, downloads disabled, service workers disabled.
2. Empirical process-egress proof: packet/tracer log showing browser PID
egress only to allowlisted IPs during a navigation (at least one proof run).
3. Distinct owner allowlist approval record (signed scope digest + sha).
4. External-effect review sign-off (no writes/sends/uploads).
Status: BLOCKED — none performed here; META-P1-05 remains
OWNER_APPROVAL_REQUIRED.

## 4. Counters (OFFLINE, no sockets created)
Planned: unittest classes 8, assert vectors ~45 subtests; run commands per task.
No production module changes. No secrets included.
