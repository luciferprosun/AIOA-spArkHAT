# G3 roadmap matrix — evidence versus absent production capabilities

Do not equate the 28 new test methods with full coverage of the original 24
roadmap threats. Numbers below are original roadmap IDs. All observed results
are **OFFLINE/FIXTURE** unless explicitly marked unavailable.

| ID | Required behavior | Current evidence / limitation |
|---|---|---|
| T01 | No send without owner consent | Fake rejects wrong admission type; no live sender exists. Genuine Core gate NOT IMPLEMENTED. |
| T02 | JSON approved=true is not authority | Existing fake/type test plus G3-06 revalidation; synthetic only. |
| T03 | Changed To/Bcc after approval | G3-01/23 exact bytes/fingerprint; Bcc remains disabled. Real warrant binding pending. |
| T04 | Changed subject/HTML | G3-23 fingerprint covers both; HTML remains disabled. |
| T05 | Attachment substitution | Attachment hashes affect fingerprint and MIME builder denies attachments; no attachment transport. |
| T06 | Invalid/future/expired approval | Existing expiry test + G3-05/07/08; fixture validity only. |
| T07 | Same consent replay | Existing replay tests + G3-03 logical-task barrier; Core consent consumption pending. |
| T08 | Two models same task | G3-04 two actual spawned processes, one task, different proposal IDs: one winner. |
| T09 | Crash before durable intent | No transport before prepare/begin; no comprehensive power-loss proof. |
| T10 | Crash after intent before HTTP | G3-26 actual abrupt process exit after SENDING; reopen to UNKNOWN, no fake replay. |
| T11 | Provider accepts, ACK lost | Existing fake loss test + G3-03/22; no real Gmail call. |
| T12 | Ambiguous timeout/5xx | Codec rejects uncertain status; fake loss remains UNKNOWN; HTTP transport absent. |
| T13 | Empty Sent query proves nothing | No search or UNKNOWN->NOT_SENT route exists; real reader NOT IMPLEMENTED. |
| T14 | STOP before send | Existing synthetic STOP test, zero fake calls. Persistent Core STOP pending. |
| T15 | STOP during live HTTP | NOT IMPLEMENTED; no live HTTP adapter. |
| T16 | Revoked/expired OAuth | NOT IMPLEMENTED; no credentials/broker. |
| T17 | Read scope absent | SelectedReplyReader is a Protocol only; no mailbox reads available. |
| T18 | Hostile email content | G3-24 inert outgoing fixture text cannot execute; incoming sanitization NOT IMPLEMENTED. |
| T19 | Spoofed incoming reply | NOT IMPLEMENTED; no ReplyCorrelator/HAT ingestion path yet. |
| T20 | Model data exfiltration | Metadata-only ledger + fake tests; actual model egress/consent policy NOT IMPLEMENTED. |
| T21 | 429 safe READ pacing | NOT IMPLEMENTED; no live reader/backoff. Send never auto-retries in the fake. |
| T22 | Provider switch/context reset | G3-03/04 same-task barrier cannot be reset by new proposal; live provider integration pending. |
| T23 | Corrupt ledger/receipts | G3-11/12/18/19/20/21/25/27/28 and original corruption tests; rollback/hostile OS not proven. |
| T24 | External data asks for execution | G3-24 inert fixture; no Gmail/MCP/Chromium execution route introduced. |

**Gate:** offline hardening batch verified; **independent G3 review pending**.
No claim of full G3, full AIOA, real-owner, real Gmail or GOLD72 acceptance.
