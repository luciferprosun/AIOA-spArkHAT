"""Supervised bounded campaign. Never grants LIVE, cost or memory authority."""
from __future__ import annotations
from dataclasses import dataclass
import time
from .alerts import alert_config_status, send_emergency_once
from .mission import ResearchMission
from .policy import AdmissionError
from .storage import Store, digest, stamp

MAX_CAMPAIGN_SECONDS = 48 * 3600

@dataclass(frozen=True)
class SupervisorLimits:
    max_wall_seconds: int = MAX_CAMPAIGN_SECONDS
    max_segments: int = 1000
    items_per_segment: int = 25
    def validate(self):
        if not (1 <= self.max_wall_seconds <= MAX_CAMPAIGN_SECONDS
                and 1 <= self.max_segments <= 1000
                and 1 <= self.items_per_segment <= 1000):
            raise AdmissionError("supervisor bounds invalid")

def supervise(store: Store, *, limits: SupervisorLimits = SupervisorLimits(),
              live_network=False, authorized_network=False,
              model=None, require_emergency_alerts=True, on_segment=None) -> dict:
    limits.validate()
    mission = store.get("mission")
    if not isinstance(mission, dict):
        raise AdmissionError("mission not initialized")
    if live_network and not authorized_network:
        raise AdmissionError("LIVE network permission required")
    if live_network and require_emergency_alerts and not alert_config_status()["ready"]:
        raise AdmissionError("LIVE emergency email gate not configured or consent not verified")
    if model is not None and not live_network:
        raise AdmissionError("model calls require LIVE mode")
    store.verify()
    started = time.monotonic()
    instance = digest({"mission": mission["created_utc"], "utc": stamp()})[:20]
    store.event("SUPERVISOR_START", {"instance": instance, "live": bool(live_network),
                                   "alert_required": bool(require_emergency_alerts)})
    segments = 0
    terminal = "SUPERVISOR_UNVERIFIED"
    try:
        for _ in range(limits.max_segments):
            if (store.root / "STOP").exists():
                terminal = "STOPPED_BY_OPERATOR"
                break
            if time.monotonic() - started >= limits.max_wall_seconds:
                terminal = "MAX_WINDOW_REACHED_NOT_CERTIFIED"
                break
            previous = store.get("mission")
            if previous["status"] not in {"PLANNED", "PAUSED"}:
                terminal = previous["status"]
                break
            if store.db.execute('SELECT COUNT(*) FROM queue WHERE status="PENDING"').fetchone()[0] == 0:
                terminal = "NO_PENDING_WORK_NOT_48H"
                break
            response = ResearchMission(store).run(
                live_network=live_network,
                authorized_network=authorized_network,
                model=model, resume=previous["status"] == "PAUSED",
                max_items=limits.items_per_segment,
            )
            segments += 1
            store.event("SUPERVISOR_CHECKPOINT", {
                "instance": instance, "batch": segments,
                "status": response["mission"]["status"],
                "documents": response["counts"]["docs"],
                "utc": stamp()
            })
            store.verify()
            if on_segment is not None:
                on_segment(response)
            if response["mission"]["status"] != "PAUSED":
                terminal = response["mission"]["status"]
                break
        else:
            terminal = "SEGMENT_LIMIT_NOT_48H"
    except BaseException as error:
        # No exceptions, source content or credentials are sent via alert.
        incident_id = "n48" + digest({"instance": instance, "batch": segments})[:20]
        store.event("SUPERVISOR_FATAL", {
            "instance": instance, "error_kind": type(error).__name__,
            "incident": incident_id
        })
        if live_network and require_emergency_alerts:
            try:
                send_emergency_once(store.root, incident_id, "SUPERVISOR_UNEXPECTED_EXIT")
            except AdmissionError:
                store.event("ALERT_UNCONFIRMED", {"incident": incident_id})
        raise
    finally:
        elapsed = round(time.monotonic() - started, 3)
        store.event("SUPERVISOR_END", {
            "instance": instance, "segments": segments,
            "wall_seconds": elapsed, "status": terminal,
            "validated_48h": False
        })
    # Failures are not silently converted into a PASS. Alert is mandatory in LIVE.
    if live_network and require_emergency_alerts and terminal in {
        "MODEL_UNKNOWN_MANUAL_RECONCILIATION", "INTERRUPTED",
        "INTEGRITY_BROKEN", "STORAGE_UNSAFE"
    }:
        incident_id = "n48" + digest({"instance": instance, "terminal": terminal})[:20]
        code = ("COST_LIMIT_UNKNOWN" if terminal.startswith("MODEL_UNKNOWN")
                else "MISSION_FATAL")
        try:
            send_emergency_once(store.root, incident_id, code)
            store.event("ALERT_SMTP_SUBMITTED", {"incident": incident_id})
        except AdmissionError:
            store.event("ALERT_UNCONFIRMED", {"incident": incident_id})
            terminal += "_ALERT_UNCONFIRMED"
    return {"supervisor": {
        "instance": instance, "terminal": terminal, "segments": segments,
        "elapsed_wall_seconds": round(time.monotonic() - started, 3),
        "run_48h_certified": False, "mode": "LIVE" if live_network else "FIXTURE"},
        "knowledge": store.report()}
