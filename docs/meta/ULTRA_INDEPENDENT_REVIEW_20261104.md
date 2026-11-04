# Independent READ-only security review

Reviewer: `/root/ultra_final_read_security_review`; lead recorded this summary.
The reviewer made no source edits and no live API/provider calls. Exact reviewed
source hashes are in ULTRA_REVIEWED_SOURCE_MANIFEST_20261104.json.

Three Important findings were independently reproduced and fixed before LIVE
qualification: duplicate YAML version parsing could trigger gh migration; TLS
expiry after signing could permit success persistence; a newer uncertain READ
could retain an older successful result in the UI.

The final independent re-review checked all seven critical file hashes and
replayed each original repro. Duplicate YAML is denied before zero children;
expired TLS leaves PENDING; newer UNKNOWN preserves its own request ID and
clears the previous result. The qualified guard performs no nested Core/model
transaction. Tests include the actual chat-enabled composition.

Independent isolated checks of concurrent same-request dispatch, reserve commit
ACK loss and result commit ACK loss showed no duplicate transport. New Native
and HTTP tests19PASS and JavaScript38PASS were reviewed.

Verdict: no remaining Critical/Important blocker was established at this
checkpoint. Controlled READ-only qualification may proceed, subject to the
remaining release checks. This is NOT proof of real GitHub READ, current Muse
inference, physical Android acceptance or full GitHub WRITE readiness.

Known conservative limitation: scanning128receipt rows can omit a current
observation after a large historical accumulation and display NOT_RUN. It does
not fabricate a positive status.
