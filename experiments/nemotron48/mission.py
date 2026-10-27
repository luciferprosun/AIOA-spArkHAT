"""Bounded 48h Web Design discovery; no AIOA executor, HAT writer, or daemon."""
from __future__ import annotations
from pathlib import Path
import json
import time
from .extract import extract
from .model import ExactModel
from .policy import AdmissionError
from .storage import Store,digest,stamp
from .transport import DocumentFetcher

FIXTURES=Path(__file__).parent/"fixtures"/"pages.json"

class ResearchMission:
    def __init__(self,store:Store):
        self.s=store

    def run(self,*,live_network=False,authorized_network=False,
            model:ExactModel|None=None,resume=False,max_items=30,
            pause_seconds=3.0):
        s=self.s
        mission=s.get("mission")
        if mission is None:
            raise AdmissionError("init required")
        s.verify()
        if live_network and not authorized_network:
            raise AdmissionError("real document retrieval requires --authorize-network")
        if model is not None and not live_network:
            raise AdmissionError("paid models forbidden in fixture mode")
        if not 1<=max_items<=1000 or not 0<=pause_seconds<=60:
            raise AdmissionError("bounded items/delay invalid")
        if s.db.execute('SELECT COUNT(*) FROM queue WHERE status="IN_FLIGHT"').fetchone()[0]:
            raise AdmissionError("crash left ambiguous in-flight source: manual review required")
        if s.db.execute('SELECT COUNT(*) FROM ledger WHERE state!="RESPONSE_VALIDATED"').fetchone()[0]:
            raise AdmissionError("unreconciled model liability: never automatically retry")
        status=mission["status"]
        if status=="RUNNING":
            mission["status"]="INTERRUPTED"
            s.set("mission",mission)
            s.event("UNCLEAN_PREVIOUS_SESSION",{"manual_resume_required":True})
            status="INTERRUPTED"
        if status=="PLANNED" and resume:
            raise AdmissionError("cannot resume before first run")
        if status in {"PAUSED","INTERRUPTED"} and not resume:
            raise AdmissionError("explicit --resume required")
        if status not in {"PLANNED","PAUSED","INTERRUPTED"}:
            raise AdmissionError("terminal run state "+status)
        source_mode="LIVE_PUBLIC_DOC" if live_network else "FIXTURE"
        if status!="PLANNED" and mission.get("source_mode")!=source_mode:
            raise AdmissionError("source mode cannot change during an existing run")
        if mission["active_seconds"]>=mission["hours"]*3600:
            raise AdmissionError("runtime ceiling consumed")
        start=time.monotonic()
        initial=mission["active_seconds"]
        session_id=digest({"utc":stamp(),"creation":mission["created_utc"]})[:20]
        mission.update({"status":"RUNNING","source_mode":source_mode,
                        "last_session":session_id,
                        "first_start_utc":mission.get("first_start_utc") or stamp()})
        s.set("mission",mission)
        s.event("SESSION_STARTED",{"session":session_id,"mode":source_mode,
                                   "resumed":resume,"paid_model":model is not None})
        fetcher=DocumentFetcher() if live_network else None
        fixtures={} if live_network else json.loads(FIXTURES.read_text("utf-8"))
        outcome="PAUSED"
        processed=0
        try:
            while processed<max_items:
                if (s.root/"STOP").exists():
                    outcome="STOPPED"
                    break
                if initial+(time.monotonic()-start)>=mission["hours"]*3600:
                    outcome="ENDED_TIME_WINDOW_UNCERTIFIED"
                    break
                if s.count("docs")>=mission["max_docs"]:
                    outcome="LIMIT_REACHED"
                    break
                if s.bytes_seen()>=mission["max_total_bytes"]:
                    outcome="BYTE_LIMIT_REACHED"
                    break
                row=s.next()
                if row is None:
                    outcome="DONE_EARLY_NOT_48H"
                    break
                url,depth=row["url"],row["depth"]
                if not live_network and url not in fixtures:
                    s.mark(url,"FIXTURE_MISSING","not in local synthetic fixture corpus")
                    s.event("FIXTURE_SKIPPED",{"url_hash":digest(url)})
                    processed+=1
                    continue
                s.mark(url,"IN_FLIGHT")
                try:
                    html=fetcher.read(url) if fetcher is not None else fixtures[url]
                    bytes_count=len(html.encode("utf-8"))
                    if bytes_count+s.bytes_seen()>mission["max_total_bytes"]:
                        s.mark(url,"FAILED","budget exhausted")
                        outcome="BYTE_LIMIT_REACHED"
                        break
                    obj=extract(url,html)
                    if len(obj["text"])<30:
                        raise AdmissionError("source text too short")
                    summary,tags=(model.summarize(obj["title"],obj["text"],obj["sha256"])
                                  if model is not None else (None,None))
                    candidate_id=s.candidate(url,obj,source_mode,bytes_count,summary=summary,tags=tags)
                    s.mark(url,"OBSERVED")
                    s.event("DOCUMENT_OBSERVED",{"url_hash":digest(url),"content_hash":obj["sha256"],
                        "candidate_id":candidate_id,"deduplicated":candidate_id is None,
                        "mode":source_mode,"truth_status":"UNVERIFIED_SHADOW"})
                    if depth<mission["max_depth"]:
                        for next_url in obj["links"][:15]:
                            s.enqueue(next_url,depth+1,url)
                except Exception as e:
                    paid_uncertainty=model is not None and s.db.execute(
                        'SELECT COUNT(*) FROM ledger WHERE state="UNKNOWN_BILLING_HELD"').fetchone()[0]>0
                    if paid_uncertainty:
                        s.mark(url,"FAILED",type(e).__name__)
                        s.event("MODEL_UNKNOWN_STOP",{"url_hash":digest(url),
                                                     "error":type(e).__name__})
                        outcome="MODEL_UNKNOWN_MANUAL_RECONCILIATION"
                        break
                    s.mark(url,"REJECTED",type(e).__name__)
                    s.event("DOCUMENT_REJECTED",{"url_hash":digest(url),
                                                 "error":type(e).__name__})
                processed+=1
                mission["active_seconds"]=round(initial+(time.monotonic()-start),3)
                mission["heartbeat_utc"]=stamp()
                s.set("mission",mission)
                if live_network and pause_seconds:
                    time.sleep(pause_seconds)
        except KeyboardInterrupt:
            outcome="STOPPED"
        except BaseException:
            outcome="INTERRUPTED"
            raise
        finally:
            mission["active_seconds"]=round(initial+(time.monotonic()-start),3)
            mission["heartbeat_utc"]=stamp()
            mission["status"]=outcome
            s.set("mission",mission)
            s.event("SESSION_ENDED",{"session":session_id,"status":outcome,
                                     "processed":processed,
                                     "active_seconds":mission["active_seconds"]})
        return s.report()
