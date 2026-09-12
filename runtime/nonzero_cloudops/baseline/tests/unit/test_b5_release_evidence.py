from __future__ import annotations

import hashlib
import json

import scripts.build_b5_release_evidence as release


def _compact(value: object) -> bytes:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def test_b5_release_outputs_are_deterministic_current_and_hash_bound() -> None:
    first = release.build_outputs()
    second = release.build_outputs()

    assert first == second
    assert release.validate_outputs(first) == ()
    assert set(first) == {
        release.ARTIFACT_MANIFEST_PATH,
        release.ATTESTATION_PATH,
        release.PACKAGE_MANIFEST_PATH,
        release.SHA256SUMS_PATH,
    }
    assert all(path.read_bytes() == content for path, content in first.items())


def test_b5_package_manifest_is_the_exact_runtime_closure() -> None:
    manifest = release.build_package_manifest()
    packages = manifest["packages"]
    names = [package["name"] for package in packages]

    assert manifest["package_count"] == len(packages) == 57
    assert names == sorted(names)
    assert len(names) == len(set(names))
    assert {
        (package["name"], package["version"], package["provenance"])
        for package in packages
        if package["name"] in {"aioa-nonzero-cloudops-agent", "pip", "strands-agents"}
    } == {
        (
            "aioa-nonzero-cloudops-agent",
            "0.2.0rc1",
            "REPRODUCIBLE_PROJECT_WHEEL",
        ),
        ("pip", "25.0.1", "DIGEST_PINNED_BASE_IMAGE"),
        ("strands-agents", "1.53.0", "HASH_PINNED_PORTABLE_LOCK"),
    }
    material = {name: value for name, value in manifest.items() if name != "manifest_sha256"}
    assert manifest["manifest_sha256"] == hashlib.sha256(_compact(material)).hexdigest()


def test_b5_artifact_and_attestation_bind_source_image_docs_and_zero_cloud() -> None:
    outputs = release.build_outputs()
    artifact = json.loads(outputs[release.ARTIFACT_MANIFEST_PATH])
    attestation = json.loads(outputs[release.ATTESTATION_PATH])

    assert artifact["source_commit"] == attestation["source_commit"] == release.SOURCE_COMMIT
    assert artifact["image"]["id"] == attestation["container_id"] == release.IMAGE_ID
    assert (
        artifact["image"]["local_manifest_digest"]
        == attestation["container_digest"]
        == release.IMAGE_DIGEST
    )
    assert artifact["image"]["registry_digest"] is None
    assert artifact["image"]["status"] == "LOCAL_ONLY_NOT_PUSHED"
    assert artifact["artifacts"]["PORTABLE_RUNTIME_CONTRACT"]["sha256"]
    assert artifact["artifacts"]["CONTAINER_JUDGE_RUNBOOK"]["sha256"]
    assert artifact["artifacts"]["SUBMISSION_DEMO_RUNBOOK"]["sha256"]
    assert set(artifact["external_actions"].values()) == {0}
    assert attestation["status"] == "BUILD_COMPLETE"
    assert all(check["status"] == "PASS" for check in attestation["checks"])
    assert attestation["aws_calls"] == attestation["aws_mutations"] == 0
    assert attestation["deployments"] == attestation["image_pushes"] == 0
    assert attestation["publications"] == attestation["remote_git_pushes"] == 0


def test_b5_release_validator_rejects_changed_generated_bytes() -> None:
    outputs = release.build_outputs()
    outputs[release.PACKAGE_MANIFEST_PATH] = b"{}\n"

    reasons = release.validate_outputs(outputs)

    assert "B5_RELEASE_OUTPUT_DRIFT" in reasons
    assert "B5_RELEASE_OUTPUT_INVALID" in reasons
