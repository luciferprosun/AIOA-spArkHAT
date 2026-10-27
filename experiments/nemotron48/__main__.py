"""CLI entry point: no external actions without explicit independent gates."""
from __future__ import annotations
import argparse
from decimal import Decimal
import json
import os
from pathlib import Path
import sys
from .mission import ResearchMission
from .model import ExactModel,ModelPolicy
from .policy import AdmissionError,canonical_url
from .storage import Store
from .supervisor import supervise, SupervisorLimits
from .audit import inspect_evidence
from .alerts import alert_config_status

HOME=Path(__file__).parent

def build_parser():
    p=argparse.ArgumentParser(prog="python -m experiments.nemotron48",
        description="Isolated 48h research. Default synthetic fixtures. No Core execution authority.")
    p.add_argument("command",choices=["init","run","supervise","audit","alert-status","status","verify","export","stop"])
    p.add_argument("--state-dir",required=True,
        help="private absolute /var/tmp or /tmp subdir; external USB/LSC blocked")
    p.add_argument("--owner-scope",default="")
    p.add_argument("--manifest",default=str(HOME/"fixtures"/"sources.json"))
    p.add_argument("--hours",type=float,default=48)
    p.add_argument("--max-docs",type=int,default=200)
    p.add_argument("--max-total-bytes",type=int,default=8_000_000)
    p.add_argument("--max-depth",type=int,default=1)
    p.add_argument("--max-items",type=int,default=30)
    p.add_argument("--resume",action="store_true")
    p.add_argument("--live-network",action="store_true")
    p.add_argument("--authorize-network",action="store_true")
    p.add_argument("--enable-live-model",action="store_true")
    p.add_argument("--authorize-paid",action="store_true")
    p.add_argument("--provider-origin",default="")
    p.add_argument("--provider-path",default="/v1/chat/completions")
    p.add_argument("--model-id",default="")
    p.add_argument("--quote-checked-utc",default="")
    p.add_argument("--input-usd-per-million",default="")
    p.add_argument("--output-usd-per-million",default="")
    p.add_argument("--budget-usd",default="")
    p.add_argument("--max-model-calls",type=int,default=100)
    p.add_argument("--max-wall-seconds",type=int,default=48*3600)
    p.add_argument("--max-segments",type=int,default=1000)
    return p

def main(argv=None):
    args=build_parser().parse_args(argv)
    store=None
    try:
        store=Store(args.state_dir,create=args.command=="init")
        if args.command=="init":
            urls=json.loads(Path(args.manifest).read_text("utf-8"))
            if not isinstance(urls,list) or not 1<=len(urls)<=30:
                raise AdmissionError("manifest must contain 1..30 source URLs")
            urls=list(dict.fromkeys(canonical_url(x) for x in urls))
            out=store.initialize(owner=args.owner_scope,urls=urls,hours=args.hours,
                max_docs=args.max_docs,max_bytes=args.max_total_bytes,max_depth=args.max_depth)
            print(json.dumps({"created":True,"mission":out},indent=2,ensure_ascii=False))
        elif args.command in {"run","supervise"}:
            if args.authorize_paid and not args.enable_live_model:
                raise AdmissionError("invalid paid-consent flags")
            if args.enable_live_model and not (args.authorize_paid and
                args.live_network and args.authorize_network):
                raise AdmissionError("LIVE model requires independent network and spending gates")
            adapter=None
            if args.enable_live_model:
                try:
                    pol=ModelPolicy(origin=args.provider_origin,path=args.provider_path,
                       exact_model_id=args.model_id,price_checked_utc=args.quote_checked_utc,
                       usd_per_million_input=Decimal(args.input_usd_per_million),
                       usd_per_million_output=Decimal(args.output_usd_per_million),
                       total_budget_usd=Decimal(args.budget_usd),call_cap=args.max_model_calls)
                except ValueError as e:
                    raise AdmissionError("invalid model pricing/budget") from e
                adapter=ExactModel(pol,store,authorized=True)
            if args.command=="supervise":
                result=supervise(store,limits=SupervisorLimits(
                    max_wall_seconds=args.max_wall_seconds,max_segments=args.max_segments,
                    items_per_segment=args.max_items),live_network=args.live_network,
                    authorized_network=args.authorize_network,model=adapter)
            else:
                result=ResearchMission(store).run(
                    live_network=args.live_network,authorized_network=args.authorize_network,
                    model=adapter,resume=args.resume,max_items=args.max_items)
            print(json.dumps(result,indent=2,ensure_ascii=False))
        elif args.command=="audit":
            print(json.dumps(inspect_evidence(store),indent=2,ensure_ascii=False))
        elif args.command=="alert-status":
            print(json.dumps(alert_config_status(),ensure_ascii=False))
        elif args.command=="status":
            print(json.dumps(store.report(),indent=2,ensure_ascii=False))
        elif args.command=="verify":
            print(json.dumps(store.verify(),indent=2))
        elif args.command=="export":
            path=store.export()
            print(json.dumps({"file":str(path),"promotion":"DISABLED","status":"UNVERIFIED_SHADOW"}))
        elif args.command=="stop":
            path=store.root/"STOP"
            if path.exists() or path.is_symlink():
                raise AdmissionError("STOP already set")
            fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|getattr(os,"O_NOFOLLOW",0),0o600)
            with os.fdopen(fd,"w") as file:
                file.write("operator requested STOP\n")
            print(json.dumps({"stop_requested":True}))
        return 0
    except (AdmissionError,OSError,ValueError,json.JSONDecodeError) as e:
        print("BLOCKED "+type(e).__name__+": "+str(e)[:140],file=sys.stderr)
        return 2
    finally:
        if store is not None:
            store.close()

if __name__=="__main__":
    raise SystemExit(main())
