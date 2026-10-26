# Meta G2 — browser network safety preview (26 October 2026)

**Scope:** offline preparation only, not a Chromium driver and not a network security certification.

Added \`runtime/meta_hackathon/network_admission.py\` and a hermetic unittest suite.
A proposed network request is evaluated against the planned task URL, HTTPS
origin, fixed GET main-frame-only policy, STOP/deadline, credential-free
execution, and synthetic DNS answers. Every verdict has
\`dispatch_allowed=False\`; even a pass signals that independent AIOA Core
admission and OS-level egress isolation are still required.

**Threat-model note:** Python DNS lookups do not pin the DNS resolution used
by Chromium and do not defeat DNS rebinding. If Chromium resolves an address
later, a syntactically approved hostname can map to an internal address.
Therefore this preview MUST NOT be wired to LIVE Chromium as an authorization
mechanism until a separate network-isolated browser worker enforces actual
egress restrictions and redirect/request checks. Block subresources, service
workers and downloads by default, use an isolated ephemeral profile, and
verify all tasks and receipts using existing AIOA Core policy.

**Validation command:**
\`PYTHONDONTWRITEBYTECODE=1 python3 -B -m unittest discover -s tests -p 'test_meta_hackathon*.py' -v\`

**Verified on isolated Linux checkout:** 38/38 offline tests PASS on 26 October.
No installed Playwright, no real browser launch, no Meta API call, no use of
the stored API key, and no charges incurred by this test. The local test
checkout is disposable and does not share an active Codex worktree.

**Next gates:** G2 requires reviewed chromium adapter + OS egress isolation
and reproducible public-page navigation evidence; G3 requires an exact
owner-approved API call budget and a signed-off Model API use plan.
