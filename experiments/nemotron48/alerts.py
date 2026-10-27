"""Opt-in, one-shot SMTP emergency alert. Disabled unless recipient consent is recorded.

Only bounded, non-sensitive codes are transmitted. SMTP acceptance is NOT proof of inbox delivery.
The private recipient address and SMTP app password are injected at runtime, never committed.
"""
from __future__ import annotations
from datetime import datetime, timezone
from email.message import EmailMessage
from email.utils import parseaddr
import hashlib
import os
from pathlib import Path
import re
import smtplib
import ssl
from .policy import AdmissionError, safe_state_dir
from .storage import atomic_json, stamp

CRITICAL_CODES = frozenset({
    "INTEGRITY_BROKEN", "STORAGE_UNSAFE", "MISSION_FATAL",
    "COST_LIMIT_UNKNOWN", "SUPERVISOR_UNEXPECTED_EXIT", "REPLAY_UNCERTAIN"
})
REQUIRED = (
    "NEMOTRON48_ALERT_TO", "NEMOTRON48_SMTP_USERNAME",
    "NEMOTRON48_SMTP_APP_PASSWORD"
)

def _valid_email(value: str) -> bool:
    addr = parseaddr(value)[1]
    return (addr == value and len(value) <= 254 and "@" in value
            and not any(c in value for c in "\r\n\x00 ")
            and len(value.partition("@")[0]) > 0 and "." in value.partition("@")[2])

def alert_config_status(environ=None) -> dict:
    env = os.environ if environ is None else environ
    if env.get("NEMOTRON48_NATALIA_CONSENT") != "confirmed":
        return {"ready": False, "reason": "RECIPIENT_CONSENT_NOT_RECORDED"}
    if any(not env.get(k) for k in REQUIRED):
        return {"ready": False, "reason": "SMTP_SECRET_MISSING"}
    if not _valid_email(env["NEMOTRON48_ALERT_TO"]) or not _valid_email(env["NEMOTRON48_SMTP_USERNAME"]):
        return {"ready": False, "reason": "INVALID_EMAIL_CONFIGURATION"}
    return {"ready": True, "reason": "READY_LOCAL_CONFIG_ONLY"}

def send_emergency_once(state_dir: str | Path, incident_id: str, code: str,
                        *, environ=None, smtp_factory=None) -> dict:
    env = os.environ if environ is None else environ
    if code not in CRITICAL_CODES or not re.fullmatch(r"[a-zA-Z0-9_-]{8,80}", incident_id):
        raise AdmissionError("invalid critical incident descriptor")
    status = alert_config_status(env)
    if not status["ready"]:
        raise AdmissionError("emergency notification blocked: " + status["reason"])
    root = safe_state_dir(state_dir)
    filename = hashlib.sha256((incident_id + "|" + code).encode()).hexdigest()[:28]
    marker = root / ("alert-" + filename + ".json")
    if marker.exists() or marker.is_symlink():
        raise AdmissionError("duplicate/uncertain notification: no automatic resend")
    # A pre-send one-use marker intentionally blocks retries if SMTP acknowledgement is lost.
    fd = os.open(marker, os.O_WRONLY | os.O_CREAT | os.O_EXCL |
                 getattr(os, "O_NOFOLLOW", 0), 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write('{"state":"ATTEMPT_RESERVED_UNKNOWN"}\n')
            f.flush()
            os.fsync(f.fileno())
    except BaseException:
        raise
    to = env["NEMOTRON48_ALERT_TO"]
    sender = env["NEMOTRON48_SMTP_USERNAME"]
    msg = EmailMessage()
    msg["To"] = to
    msg["From"] = sender
    msg["Subject"] = "[AIOA NEMOTRON48] CRITICAL " + code
    msg.set_content(
        "Automatyczne powiadomienie o zagrożeniu eksperymentu AIOA NEMOTRON48.\n"
        "Kod zdarzenia: " + code + "\n"
        "Identyfikator: " + incident_id + "\n"
        "Nie udostępniaj danych uwierzytelniających ani prywatnych materiałów.\n"
        "Skontaktuj się z właścicielem projektu niezależnym kanałem.\n"
        "To powiadomienie nie daje żadnych uprawnień do systemu.\n"
    )
    smtp = smtp_factory if smtp_factory is not None else smtplib.SMTP_SSL
    try:
        with smtp("smtp.gmail.com", 465, context=ssl.create_default_context(), timeout=15) as server:
            server.login(sender, env["NEMOTRON48_SMTP_APP_PASSWORD"])
            refused = server.send_message(msg)
            if refused:
                raise AdmissionError("SMTP refused recipient")
        outcome = "SMTP_ACCEPTED_DELIVERY_UNCONFIRMED"
    except Exception as exc:
        # No exception text, credentials, recipient or SMTP response stored.
        atomic_json(marker, {"schema": "nemotron48-alert-v1",
                             "status": "UNKNOWN_DELIVERY_MANUAL_REVIEW",
                             "incident_sha256": hashlib.sha256(incident_id.encode()).hexdigest(),
                             "code": code, "utc": stamp(), "exception_type": type(exc).__name__})
        raise AdmissionError("SMTP result uncertain; human reconciliation required") from None
    atomic_json(marker, {"schema": "nemotron48-alert-v1",
                         "status": outcome,
                         "incident_sha256": hashlib.sha256(incident_id.encode()).hexdigest(),
                         "code": code, "utc": stamp()})
    return {"status": outcome, "incident": incident_id, "code": code,
            "recipient_redacted": True}
