import ast
import json
from pathlib import Path

import yaml

from aioa_cloudops_agent.agent import CURRENT_TOOL_NAMES

ROOT = Path(__file__).parents[2]
SOURCE_ROOT = ROOT / "src" / "aioa_cloudops_agent"
SAM_TEMPLATE = ROOT / "infra" / "sam" / "template.yaml"
READ_ONLY_POLICY = ROOT / "infra" / "iam" / "cloudops-read-only-policy.json"

PROHIBITED_PROVIDER_METHODS = {
    "authorize_security_group_ingress",
    "create_tags",
    "delete_tags",
    "delete_security_group",
    "modify_instance_attribute",
    "reboot_instances",
    "release_address",
    "revoke_security_group_ingress",
    "run_instances",
    "send_command",
    "start_instances",
    "stop_instances",
    "terminate_instances",
}
PROHIBITED_MODULES = {"httpx", "requests", "socket", "subprocess", "urllib"}
PROHIBITED_CODE_EXECUTION_CALLS = {"compile", "eval", "exec"}


def _python_trees() -> list[tuple[Path, ast.AST]]:
    return [
        (path, ast.parse(path.read_text(encoding="utf-8"))) for path in SOURCE_ROOT.rglob("*.py")
    ]


def _all_actions(value: object) -> list[str]:
    actions: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            if key == "Action":
                actions.extend([child] if isinstance(child, str) else child)
            else:
                actions.extend(_all_actions(child))
    elif isinstance(value, list):
        for child in value:
            actions.extend(_all_actions(child))
    return actions


def test_executable_source_contains_no_ec2_mutation_calls() -> None:
    discovered: list[tuple[str, str]] = []
    for path, tree in _python_trees():
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr.casefold() in PROHIBITED_PROVIDER_METHODS
            ):
                discovered.append((str(path.relative_to(ROOT)), node.func.attr))

    stop_calls = [item for item in discovered if item[1] == "stop_instances"]
    other_calls = [item for item in discovered if item[1] != "stop_instances"]

    assert other_calls == []
    assert stop_calls == [
        ("src/aioa_cloudops_agent/remediation/executor.py", "stop_instances"),
        ("src/aioa_cloudops_agent/remediation/executor.py", "stop_instances"),
    ]


def test_executable_source_contains_no_shell_or_arbitrary_network_client() -> None:
    discovered: list[tuple[str, str]] = []
    for path, tree in _python_trees():
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.split(".", maxsplit=1)[0] in PROHIBITED_MODULES:
                        discovered.append((str(path.relative_to(ROOT)), alias.name))
            elif (
                isinstance(node, ast.ImportFrom)
                and node.module
                and node.module.split(".", maxsplit=1)[0] in PROHIBITED_MODULES
            ):
                discovered.append((str(path.relative_to(ROOT)), node.module))

    assert discovered == []


def test_executable_source_contains_no_dynamic_code_execution() -> None:
    discovered: list[tuple[str, str]] = []
    for path, tree in _python_trees():
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id in PROHIBITED_CODE_EXECUTION_CALLS
            ):
                discovered.append((str(path.relative_to(ROOT)), node.func.id))

    assert discovered == []


def test_no_multi_agent_agentcore_or_dynamic_tool_loading_is_active() -> None:
    source = "\n".join(path.read_text(encoding="utf-8") for path in SOURCE_ROOT.rglob("*.py"))
    lowered = source.casefold()

    assert "strands.multiagent" not in lowered
    assert "agentcore" not in lowered
    assert "load_tools_from_directory=true" not in lowered.replace(" ", "")
    assert "shell" not in {
        node.id.casefold()
        for _, tree in _python_trees()
        for node in ast.walk(tree)
        if isinstance(node, ast.Name)
    }


def test_local_eip_query_does_not_expand_live_aws_or_strands_tool_surface() -> None:
    source = "\n".join(path.read_text(encoding="utf-8") for path in SOURCE_ROOT.rglob("*.py"))

    assert "DescribeAddresses" not in source
    assert "class QueryResource" in source
    assert "class MockAwsAdapter" in source
    assert "query_resource" not in CURRENT_TOOL_NAMES
    assert "plan_remediation" not in CURRENT_TOOL_NAMES


def test_infrastructure_isolates_the_only_stop_authority_from_read_only_policy() -> None:
    sam = yaml.safe_load(SAM_TEMPLATE.read_text(encoding="utf-8"))
    policy = json.loads(READ_ONLY_POLICY.read_text(encoding="utf-8"))
    template_actions = _all_actions(sam)
    read_only_actions = _all_actions(policy)
    actions = template_actions + read_only_actions

    assert "ec2:DescribeInstances" in actions
    assert "ec2:StopInstances" in actions
    assert "ec2:StopInstances" not in read_only_actions
    assert "ec2:TerminateInstances" not in actions
    assert {
        action for action in template_actions if action.startswith("bedrock:")
    } == {"bedrock:InvokeModelWithResponseStream"}
    assert not any(action.startswith("bedrock:") for action in read_only_actions)
    assert not any("*" in action for action in actions)


def test_active_source_and_iac_contain_no_account_specific_identifier() -> None:
    import re

    text = "\n".join(
        path.read_text(encoding="utf-8")
        for root in (SOURCE_ROOT, ROOT / "infra")
        for path in root.rglob("*")
        if path.is_file() and path.suffix in {".json", ".md", ".py", ".yaml", ".yml"}
    )

    assert re.search(r"(?<!\d)\d{12}(?!\d)", text) is None
