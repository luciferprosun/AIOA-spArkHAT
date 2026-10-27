"""Reproducible evidence review: local traces are never external 48h certification."""
from __future__ import annotations
from datetime import datetime, timezone
from .policy import AdmissionError
from .storage import Store, atomic_json, stamp

REQUIRED_SECONDS = 48 * 3600
MAX_HEARTBEAT_GAP = 15 * 60

def inspect_evidence(store: Store) -> dict:
    integrity = store.verify()
    mission = store.get("mission")
    if mission is None:
        raise AdmissionError("mission not initialized")
    rows = list(store.db.execute("SELECT seq,time_utc,kind,body FROM events ORDER BY seq"))
    checkpoints = [row for row in rows if row["kind"] == "SUPERVISOR_CHECKPOINT"]
    accepted = [row for row in rows if row["kind"] == "DOCUMENT_OBSERVED"]
    calls = list(store.db.execute("SELECT model,state FROM ledger ORDER BY created_utc"))
    source_modes = [row[0] for row in store.db.execute("SELECT DISTINCT source_mode FROM docs")]
    checkpoint_times = [datetime.fromisoformat(x["time_utc"]) for x in checkpoints]
    observed_span = ((checkpoint_times[-1] - checkpoint_times[0]).total_seconds()
                     if len(checkpoint_times) > 1 else 0)
    gap = (max((b-a).total_seconds() for a,b in zip(checkpoint_times,checkpoint_times[1:]))
           if len(checkpoint_times)>1 else None)
    model_names = sorted(set(c["model"] for c in calls))
    is_nebius_nemotron = any("nemotron" in name.lower() for name in model_names)
    # Strictly a local candidate: source integrity, independent timestamps and model bills
    # need an external, retained witness; never assert certified solely on local metadata.
    conditions = {
        "live_only_sources": source_modes == ["LIVE_PUBLIC_DOC"] and bool(accepted),
        "model_calls": bool(calls),
        "exact_nemotron_identity_observed_in_ledger": is_nebius_nemotron,
        "no_unknown_billing": all(c["state"] == "RESPONSE_VALIDATED" for c in calls),
        "active_duration_48h": mission.get("active_seconds",0)>=REQUIRED_SECONDS,
        "checkpoint_window_48h": observed_span>=REQUIRED_SECONDS,
        "checkpoint_gap_within_15m": gap is not None and gap<=MAX_HEARTBEAT_GAP,
        "local_event_chain_consistent": integrity["integrity"]=="CONSISTENT_LOCAL_CHAIN_ONLY",
    }
    result={
        "schema":"nemotron48-independent-review-v1",
        "review_utc":stamp(),
        "mission_creation_utc":mission["created_utc"],
        "source_mode":mission.get("source_mode","NONE"),
        "terminal":mission["status"],
        "documents":store.count("docs"),
        "shadow_candidates":store.count("candidates"),
        "shadow_pheromone":store.count("pheromone"),
        "model_calls":len(calls),
        "model_ids":model_names,
        "duration":{
            "mission_reported_active_seconds":mission.get("active_seconds",0),
            "checkpoint_utc_span_seconds":observed_span,
            "max_checkpoint_gap_seconds":gap,
            "checkpoints":len(checkpoints)},
        "checks":conditions,
        "verdict":"NEEDS_EXTERNAL_VERIFICATION" if all(conditions.values())
                  else "NOT_PROVEN_48H",
        "independent_certification":False,
        "explanation":"Local fixture or local event chain does not independently prove 48h LIVE model work."
    }
    return result
