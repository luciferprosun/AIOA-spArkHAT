"""LITE operations on the existing AIOA entry point, with explicit Core scope."""

from __future__ import annotations

import json
from pathlib import Path
import signal
import sqlite3

from runtime.core_admission import OwnerScope
from runtime.memory_patch.contracts.serialization import canonical_sha256
from runtime.mission.cli import DiagnosticParser, read_manifest_file
from runtime.mission.contracts import MissionContext, MissionError
from runtime.mission.lite_contracts import parse_lite_profile
from runtime.mission.lite_runtime import FileObservationProbe, LiteBindings
from runtime.providers.nvidia import NvidiaProvider


def run_lite_cli(argv, *, runtime_factory):
    runtime, handlers, code = None, {}, 0
    try:
        parser = DiagnosticParser(prog="aioa-sparkhat lite")
        parser.add_argument("operation", choices=("doctor", "status", "watch"))
        parser.add_argument("--manifest", required=True)
        parser.add_argument("--tenant", required=True)
        parser.add_argument("--owner", required=True)
        parser.add_argument("--space", required=True)
        parser.add_argument("--slot", required=True)
        parser.add_argument("--source-id", required=True)
        parser.add_argument("--source-file")
        parser.add_argument("--state-root", required=True,
                            help="Core deployment state root; reuse this root across restarts/revisions")
        parser.add_argument("--json", action="store_true")
        args = parser.parse_args(argv)
        context = MissionContext(OwnerScope(args.tenant, args.owner, args.space, args.slot), frozenset({args.source_id}))
        profile = parse_lite_profile(read_manifest_file(args.manifest), context)
        provider = NvidiaProvider(profile.budget)
        state_root = Path(args.state_root).resolve()
        if args.operation == "watch":
            if not args.source_file or not profile.enabled:
                raise MissionError("EXPLICIT_ENABLED_SOURCE_REQUIRED")
            bindings = LiteBindings(state_root, FileObservationProbe(args.source_id, args.source_file), provider)
            runtime = runtime_factory(lite_profile=profile, mission_context=context, lite_bindings=bindings)
            for signum in (signal.SIGTERM, signal.SIGINT):
                handlers[signum] = signal.signal(signum, lambda *_: runtime.lite_request_stop())
            print(json.dumps(runtime.lite_status(), sort_keys=True), flush=True)
            runtime.lite_run()
            result = {"state": "STOPPED", "reason": "READONLY_STOPPED", "domain_mutations": 0}
        else:
            runtime = runtime_factory(lite_profile=profile, mission_context=context, inspection_only=True)
            result = runtime.lite_status()
            result.update(key_source="ENV", key_present=provider.key_present())
            if args.operation == "status":
                identity = canonical_sha256({"owner": profile.owner_scope, "watch": profile.watch_id})
                path = state_root / (identity + ".sqlite3")
                if path.exists() and not path.is_symlink():
                    db = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=5)
                    try:
                        row = db.execute("SELECT data FROM watch WHERE singleton=1").fetchone()
                        state = json.loads(row[0])
                        result["persisted_watch"] = {k: v for k, v in state.items() if k != "queue"}
                        result["persisted_watch"]["queue_depth"] = len(state["queue"])
                        result["persisted_watch"]["manifest_matches"] = state["manifest_digest"] == profile.digest
                    finally:
                        db.close()
                else:
                    result["persisted_watch"] = None
    except MissionError as error:
        result, code = {"state": "ERROR", "reason": error.code}, error.exit_code
    except Exception:
        result, code = {"state": "ERROR", "reason": "LITE_OPERATION_FAILED"}, 5
    finally:
        for signum, previous in handlers.items():
            signal.signal(signum, previous)
        if runtime is not None:
            runtime.close()
    print(json.dumps(result, sort_keys=True, ensure_ascii=False, allow_nan=False))
    return code
