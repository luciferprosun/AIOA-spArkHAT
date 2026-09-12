from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from scripts.day15 import render_template as renderer
from scripts.day15 import validate_template as template_validator
from scripts.day15.validate_template import DEFAULT_TEMPLATE, canonical_json, load_template


def _fake_rendered() -> dict[str, object]:
    value = copy.deepcopy(load_template(DEFAULT_TEMPLATE))
    value.pop("Transform", None)
    resources = value["Resources"]
    assert isinstance(resources, dict)
    for resource in resources.values():
        if isinstance(resource, dict) and resource.get("Type") == "AWS::Serverless::Function":
            resource["Type"] = "AWS::Lambda::Function"
    return value


def _pin_local_renderer(monkeypatch: pytest.MonkeyPatch) -> dict[str, object]:
    rendered = _fake_rendered()
    monkeypatch.setattr(
        renderer,
        "validate_template_toolchain",
        lambda _path: (
            "PASS",
            (),
            {
                "cfn_lint": "1.52.1",
                "sam_cli": "1.165.0",
                "sam_translator": "1.111.0",
            },
        ),
    )
    monkeypatch.setattr(renderer, "render_model", lambda _template: copy.deepcopy(rendered))
    monkeypatch.setattr(renderer, "repository_binding", lambda *_args: "a" * 40)
    return rendered


def test_renderer_is_byte_deterministic_and_verifies_source_tools_and_commit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rendered = _pin_local_renderer(monkeypatch)
    output = tmp_path / "rendered-template.yaml"
    proof = tmp_path / "rendered-template.provenance.json"

    first = renderer.render_template(output=output, provenance=proof)
    first_bytes = output.read_bytes(), proof.read_bytes()
    second = renderer.render_template(output=output, provenance=proof)

    assert first == second
    assert first_bytes == (output.read_bytes(), proof.read_bytes())
    assert output.read_text(encoding="utf-8") == canonical_json(rendered) + "\n"
    verified, verified_proof = renderer.verify_rendered_template(
        template=DEFAULT_TEMPLATE,
        toolchain=renderer.DEFAULT_TOOLCHAIN,
        rendered_template=output,
        provenance=proof,
    )
    assert verified == rendered
    assert verified_proof == first


def test_renderer_rejects_fabricated_or_tampered_output_and_provenance(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _pin_local_renderer(monkeypatch)
    output = tmp_path / "rendered-template.yaml"
    proof = tmp_path / "rendered-template.provenance.json"
    renderer.render_template(output=output, provenance=proof)
    changed = json.loads(output.read_text(encoding="utf-8"))
    changed["Description"] = "fabricated"
    output.write_text(canonical_json(changed) + "\n", encoding="utf-8")

    with pytest.raises(renderer.RenderFailure, match="RENDERED_TEMPLATE_REPRODUCIBILITY_MISMATCH"):
        renderer.verify_rendered_template(
            template=DEFAULT_TEMPLATE,
            toolchain=renderer.DEFAULT_TOOLCHAIN,
            rendered_template=output,
            provenance=proof,
        )

    renderer.render_template(output=output, provenance=proof)
    changed_proof = json.loads(proof.read_text(encoding="utf-8"))
    changed_proof["repository_commit_oid"] = "b" * 40
    proof.write_text(canonical_json(changed_proof) + "\n", encoding="utf-8")
    with pytest.raises(renderer.RenderFailure, match="RENDERED_TEMPLATE_PROVENANCE_MISMATCH"):
        renderer.verify_rendered_template(
            template=DEFAULT_TEMPLATE,
            toolchain=renderer.DEFAULT_TOOLCHAIN,
            rendered_template=output,
            provenance=proof,
        )


def test_renderer_refuses_unpinned_or_unavailable_toolchain(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        renderer,
        "validate_template_toolchain",
        lambda _path: ("FAIL", ("SAM_TRANSLATOR_VERSION_MISMATCH",), {}),
    )

    with pytest.raises(renderer.RenderFailure) as failure:
        renderer.render_template(
            output=tmp_path / "rendered.yaml",
            provenance=tmp_path / "proof.json",
        )

    assert failure.value.reason == "SAM_TRANSLATOR_VERSION_MISMATCH"
    assert failure.value.status == "FAIL"


def test_renderer_rejects_dirty_validator_helper_as_an_authenticated_input(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, ...]] = []

    def fake_git(*arguments: str) -> str:
        calls.append(arguments)
        if arguments[:2] == ("rev-parse", "--show-toplevel"):
            return f"{renderer.ROOT}\n"
        if arguments[:2] == ("status", "--porcelain=v1"):
            return " M scripts/day15/validate_template.py\n"
        raise AssertionError(arguments)

    monkeypatch.setattr(renderer, "_git", fake_git)
    with pytest.raises(renderer.RenderFailure) as failure:
        renderer.repository_binding(DEFAULT_TEMPLATE, renderer.DEFAULT_TOOLCHAIN)

    assert failure.value.reason == "RENDER_INPUTS_NOT_CLEAN"
    status_call = next(call for call in calls if call[0] == "status")
    assert "scripts/day15/validate_template.py" in status_call


def test_template_validator_requires_exact_sam_lint_and_translator_versions(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(template_validator.shutil, "which", lambda _name: "/usr/bin/sam")
    monkeypatch.setattr(
        template_validator,
        "_sam_cli_version",
        lambda _executable: ("1.165.0", None),
    )
    versions = {"cfn-lint": "1.52.1", "aws-sam-translator": "1.111.0"}
    monkeypatch.setattr(
        template_validator.importlib.metadata,
        "version",
        lambda distribution: versions[distribution],
    )

    status, reasons, actual = template_validator.validate_template_toolchain()
    assert status == "PASS"
    assert reasons == ()
    assert actual == {
        "cfn_lint": "1.52.1",
        "sam_cli": "1.165.0",
        "sam_translator": "1.111.0",
    }

    versions["cfn-lint"] = "1.52.0"
    status, reasons, _ = template_validator.validate_template_toolchain()
    assert status == "FAIL"
    assert reasons == ("CFN_LINT_VERSION_MISMATCH",)

    toolchain = json.loads(renderer.DEFAULT_TOOLCHAIN.read_text(encoding="utf-8"))
    toolchain["cfn_lint"]["version"] = "1.52.0"
    changed = tmp_path / "toolchain.json"
    changed.write_text(canonical_json(toolchain) + "\n", encoding="utf-8")
    status, reasons, _ = template_validator.validate_template_toolchain(changed)
    assert status == "FAIL"
    assert "CFN_LINT_NOT_PINNED" in reasons
