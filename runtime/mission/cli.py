"""Diagnostic subcommands on the existing aioa-sparkhat entry point."""

from __future__ import annotations

import argparse
import json
import os
import stat

from runtime.mission.contracts import (
    MAX_MANIFEST_BYTES,
    PROFILE,
    MissionContext,
    MissionError,
    contract_fixture_context,
    parse_manifest,
)
from runtime.mission.diagnostics import result_envelope


class DiagnosticParser(argparse.ArgumentParser):
    def error(self, message):
        raise MissionError("INVALID_CLI_ARGUMENTS")


def read_manifest_file(path):
    # Only an explicit operator file is read. No source path comes from JSON.
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, "rb") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_MANIFEST_BYTES:
            raise MissionError("INVALID_MANIFEST_FILE")
        raw = stream.read(MAX_MANIFEST_BYTES + 1)
    if len(raw) > MAX_MANIFEST_BYTES:
        raise MissionError("INVALID_MANIFEST_FILE")
    try:
        return raw.decode("utf-8", errors="strict")
    except UnicodeError:
        raise MissionError("INVALID_MANIFEST_FILE") from None


def run_diagnostic_cli(argv, *, runtime_factory):
    runtime = None
    try:
        parser = DiagnosticParser(prog="aioa-sparkhat")
        subcommands = parser.add_subparsers(
            dest="command", required=True, parser_class=DiagnosticParser
        )
        doctor = subcommands.add_parser(
            "doctor", help="Inspect nvidia-lite without starting services"
        )
        doctor.add_argument("--profile", choices=[PROFILE], default=PROFILE)
        doctor.add_argument("--manifest")
        doctor.add_argument("--json", action="store_true")
        doctor.add_argument(
            "--contract-fixture",
            action="store_true",
            help="Synthetic ownership only; no authority",
        )
        mission = subcommands.add_parser("mission")
        operations = mission.add_subparsers(
            dest="operation", required=True, parser_class=DiagnosticParser
        )
        validate = operations.add_parser("validate")
        validate.add_argument("manifest")
        validate.add_argument("--json", action="store_true")
        validate.add_argument(
            "--contract-fixture",
            action="store_true",
            help="Synthetic ownership only; no authority",
        )
        args = parser.parse_args(argv)
        context = (
            contract_fixture_context() if args.contract_fixture else MissionContext()
        )
        manifest = (
            parse_manifest(read_manifest_file(args.manifest), context)
            if args.manifest
            else None
        )
        runtime = runtime_factory(inspection_only=True, mission_context=context)
        if args.command == "doctor":
            result = runtime.mission_doctor(manifest=manifest)
            code = 3 if result["status"] == "UNAVAILABLE" else 0
        else:
            result = result_envelope(
                "VALIDATED",
                "MANIFEST_VALID_NOT_EXECUTABLE",
                revision=manifest.manifest_revision,
                classification=context.classification,
                next_action="REVIEW_PORT_READINESS",
            )
            result["manifest_digest"] = manifest.digest
            code = 0
    except MissionError as error:
        result = result_envelope(
            error.status,
            error.code,
            next_action="OPERATOR_REVIEW_REQUIRED",
            retry_class="DO_NOT_RETRY_UNCHANGED",
        )
        code = error.exit_code
    except OSError:
        result = result_envelope(
            "ERROR",
            "MANIFEST_FILE_UNAVAILABLE",
            next_action="CHECK_EXPLICIT_INPUT_FILE",
            retry_class="MANUAL_CONFIGURATION",
        )
        code = 5
    except Exception:  # noqa: BLE001 - public CLI never leaks private dependency errors
        result = result_envelope(
            "ERROR",
            "DIAGNOSTIC_INTERNAL_ERROR",
            next_action="INSPECT_PRIVATE_LOGS",
            retry_class="DO_NOT_RETRY_UNCHANGED",
        )
        code = 5
    finally:
        if runtime is not None:
            runtime.close()
    print(
        json.dumps(
            result,
            sort_keys=True,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
        )
    )
    return code
