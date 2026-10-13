#!/usr/bin/env python3
"""Offline build-host verification of an unsigned diagnostic .deb; never installs."""
from __future__ import annotations
import argparse
import importlib.util
import json
import re
from pathlib import Path
import subprocess

spec = importlib.util.spec_from_file_location("verified_deb_builder", Path(__file__).with_name("build_deb_candidate.py"))
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)
evidence = builder.evidence


def verify(root, artifact, sbom_path, provenance_path, *, expected_commit, expected_tree,
           expected_sha256, scope="diagnostic"):
    evidence.check_scope(scope)
    context = builder.prepare_context(root, expected_commit, expected_tree)
    expected, control = builder.candidate_payload(root, context)
    artifact = Path(artifact).absolute()
    evidence.need(artifact.name == "aioa-sparkhat_" + builder.VERSION + "_amd64.deb", "ARTIFACT_NAME_MISMATCH")
    raw = evidence.safe_bytes(artifact, evidence.MAX_DEB_BYTES)
    contents = evidence.read_deb(raw, expected_sha256=expected_sha256)
    evidence.verify_contents(contents, expected, control, context["source"]["epoch"])
    wanted_sbom = evidence.canonical_json(evidence.spdx_sbom(context, expected_sha256))
    actual_sbom = evidence.safe_bytes(sbom_path, 2 * 1024 * 1024)
    evidence.need(actual_sbom == wanted_sbom, "SBOM_MISMATCH")
    evidence.validate_spdx(json.loads(actual_sbom))
    wanted_provenance = evidence.canonical_json(evidence.provenance(context, expected_sha256, evidence.sha(wanted_sbom), len(raw)))
    evidence.need(evidence.safe_bytes(provenance_path, 2 * 1024 * 1024) == wanted_provenance, "PROVENANCE_MISMATCH")
    evidence.need(context == builder.prepare_context(root, expected_commit, expected_tree), "VERIFY_SOURCE_OR_TOOLCHAIN_DRIFT")
    return {"schema": "aioa.deb-verification.v1", "status": "PASS_LOCAL_LIMITED",
            "source_commit": expected_commit, "source_tree": expected_tree,
            "artifact_sha256": expected_sha256, "artifact_bytes": len(raw),
            "sbom_sha256": evidence.sha(actual_sbom), "provenance_sha256": evidence.sha(wanted_provenance),
            "source_files": len(context["source_inventory"]), "payload_files": len(expected),
            "payload_directories": len(contents["directories"]), "unsigned": True,
            "license_review": "REVIEW_REQUIRED_OS_PROVIDED_NOT_BUNDLED",
            "signer": "ABSENT", "P1": "NOT_ACCEPTED", "P2": "NOT_ACCEPTED", "P3": "NOT_ACCEPTED",
            "system_installs": 0, "provider_live_calls": 0, "release_gate": "BLOCKED_OR_PENDING"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--artifact", type=Path, required=True)
    parser.add_argument("--sbom", type=Path, required=True)
    parser.add_argument("--provenance", type=Path, required=True)
    parser.add_argument("--expected-commit", required=True)
    parser.add_argument("--expected-tree", required=True)
    parser.add_argument("--expected-sha256", required=True)
    parser.add_argument("--scope", default="diagnostic", choices=("diagnostic", "release"))
    args = parser.parse_args()
    try:
        result = verify(args.source, args.artifact, args.sbom, args.provenance,
                        expected_commit=args.expected_commit, expected_tree=args.expected_tree,
                        expected_sha256=args.expected_sha256, scope=args.scope)
    except (OSError, ValueError, UnicodeError, subprocess.SubprocessError, KeyError, TypeError) as error:
        # Never echo source content, subprocess stderr, credentials or host paths.
        code = str(error) if type(error) is ValueError and re.fullmatch(r"[A-Z][A-Z0-9_]{0,100}", str(error)) else "VERIFICATION_FAILED"
        print(json.dumps({"status": "FAIL_CLOSED", "reason": code}))
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
