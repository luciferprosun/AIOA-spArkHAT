# Cosmic Linux — truthful READ fallback runbook

Release status: NOT_YET_QUALIFIED. Do not record an unqualified candidate as LIVE.

## Identity and prerequisites

Use the existing private Native host and state root. Never create a new Core,
copy a database, change a TLS pin, reinstall Android or reset pairing.
Only a clean source with successful regression, review and required CI may
replace the precisely identified4317 process. Use genuine local PolicyKit.
Source/capsule changes require signed reconnect, not a new device identity.

Launch from that qualified source using the existing parameters:

```bash
python3 -B -m runtime.webapp --mobile-native --mobile-chat \
  --state-dir "$AIOA_NATIVE_STATE" --mobile-origin "$AIOA_PRIVATE_ORIGIN" \
  --mobile-tls-certificate "$AIOA_NATIVE_STATE/tls/host.crt" \
  --mobile-tls-key "$AIOA_NATIVE_STATE/tls/host.key" --host 127.0.0.1 --port 4317
```

Environment variables identify existing paths,
never authority or an approval flag. Do not guess their values or print secrets.
If the existing host is already qualified, do not launch another listener.

Open the existing secure Chrome console from the same checkout:

```bash
python3 -B -m runtime.webapp --mobile-operator console --state-dir "$AIOA_NATIVE_STATE"
```

No token belongs in a URL, screenshot or terminal log.

## Three-minute demonstration, only after observed acceptance

1. **0:00–0:25:** show AIOA Mission Control at1600×900. Read Core profile.
   Explain current source and true Native capabilities. A remembered phone is
   not proof that it is online; show a fresh signed observation only if verified.
2. **0:25–1:05:** open GitHub; deliberately click Read repository and main.
   Show real repository ID, branch, commit, observation time and receipt digest.
   Local Git status/log are separate bounded reads, not remote writes.
3. **1:05–1:45:** open Chat. Show the historical accepted Muse receipt as
   historical. For a new current-source response, submit a fresh request, review
   its exact prompt/payload/cost in the native Linux channel, and approve one
   attempt only. Do not spend automatically for a recording. An old UNKNOWN
   stays unresolved; Start a separate conversation never retries it.
4. **1:45–2:20:** only if a new actual response exists, validate its typed
   proposal from the Core request ID. Accepted reply format is exactly:
   `{"operation":"issue.create","target_repo":"luciferprosun/AIOA-spArkHAT","title":"…","body":"…"}`.
   Say explicitly that this is an advisory proposal. No issue was created while
   REMOTE_WRITE_BLOCKED is shown. Never demonstrate a synthetic proposal as LIVE.
5. **2:20–2:45:** show Critical: BLOCKED_NATIVE_CPL_NOT_BOUND and its sequential
   five-call contract. No loop or spend is implied by the preview.
6. **2:45–3:00:** show receipt/source and STOP boundary. STOP cannot undo a
   completed external effect. This candidate has no remote mutation executor.

If no fresh Muse approval/response is available, use the shorter honest READ
demonstration. Do not claim the complete governed GitHub agent acceptance gate.

## Remaining human/architecture gates

- Independent accounting evidence is needed for the historical Meta UNKNOWN;
  do not edit the record to success or release its budget by assumption.
- A narrow remote-zero START/ServiceGuard contract needs separate review before
  any issue.create implementation is enabled. Do not reuse the local networkOFF
  route or fabricate a money reservation.
- Exact one-use GitHub effect approval is distinct from Meta spending.
- Final main merge and external submission remain owner actions.

## Rollback

Retain known-goodb7f4002 host source and613737f Android delivery. Stop only the
owned qualified4317 process after verifying PID/start/cwd/UID/source; relaunch
the old qualified source with actual PolicyKit and the unchanged current state
and TLS files. Never restore an old journal, reuse a consumed warrant or retry
an uncertain request. Protected services and Android remain untouched.
