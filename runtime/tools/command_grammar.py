"""Advisory RHCSA command-shape validation.

This module is local, deterministic, read-only, and non-executing. It does not
prove command safety or factual correctness, does not replace ShellCheck or
tree-sitter-bash, and is not wired into executor policy.
"""

from __future__ import annotations

import json
import re
import shlex
from pathlib import Path
from typing import Any


_PATTERN_PATH = (
    Path(__file__).resolve().parents[1]
    / "knowledge"
    / "grammar"
    / "command_patterns.json"
)

_REQUIRED_KEYS = {
    "status",
    "family",
    "base",
    "confidence",
    "danger",
    "reasons",
    "matched_pattern_id",
}
_STATUS_REJECT = "reject"
_STATUS_SUSPICIOUS = "suspicious"
_STATUS_FAMILY = "family"
_DANGEROUS_FIND_TOKENS = {"-delete", "-exec", "-execdir", "-ok", "-okdir"}
_DANGEROUS_WORDS = {
    "add",
    "change",
    "create",
    "delete",
    "del",
    "destroy",
    "down",
    "format",
    "install",
    "mklabel",
    "mkpart",
    "modify",
    "remove",
    "replace",
    "reset",
    "restart",
    "rm",
    "set",
    "start",
    "stop",
    "undefine",
    "up",
}
_NETWORK_CHANGE_WORDS = {
    "add",
    "change",
    "delete",
    "del",
    "down",
    "flush",
    "modify",
    "replace",
    "set",
    "up",
}


def _result(
    *,
    status: str,
    family: str | None = None,
    base: str | None = None,
    confidence: str = "grammar_reject",
    danger: str = "unknown",
    reasons: list[str] | None = None,
    matched_pattern_id: str | None = None,
) -> dict[str, Any]:
    result = {
        "status": status,
        "family": family,
        "base": base,
        "confidence": confidence,
        "danger": danger,
        "reasons": reasons or [],
        "matched_pattern_id": matched_pattern_id,
    }
    missing = _REQUIRED_KEYS - set(result)
    if missing:
        raise RuntimeError(f"internal command grammar result missing keys: {missing}")
    return result


def _load_patterns() -> list[dict[str, Any]]:
    with _PATTERN_PATH.open("r", encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data, list):
        raise ValueError("command grammar patterns must be a list")
    return data


def _pattern_by_base() -> dict[str, dict[str, Any]]:
    return {
        str(pattern.get("base")): pattern
        for pattern in _load_patterns()
        if isinstance(pattern, dict) and pattern.get("base")
    }


def _is_path_only(command: str) -> bool:
    return command.startswith(("/", "./", "../", "~")) and " " not in command.strip()


def _is_flag_only(command: str) -> bool:
    stripped = command.strip()
    return stripped.startswith("-") and " " not in stripped


def _is_variable_only(command: str) -> bool:
    return bool(re.fullmatch(r"\$[A-Za-z_][A-Za-z0-9_]*", command.strip()))


def _is_glob_only(command: str) -> bool:
    stripped = command.strip()
    return any(ch in stripped for ch in "*?[") and " " not in stripped


def _has_shell_composition(tokens: list[str], command: str) -> bool:
    operators = {"|", "||", "&&", ";", ">", ">>", "<", "2>", "2>>", "&"}
    if any(token in operators for token in tokens):
        return True
    return any(op in command for op in ("|", "&&", ";", ">", "<"))


def _split(command: str) -> tuple[list[str], str | None]:
    try:
        return shlex.split(command), None
    except ValueError as exc:
        return [], str(exc)


def _chmod_shape(tokens: list[str]) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    args = [token for token in tokens[1:] if not token.startswith("-")]
    if len(args) < 2:
        return False, ["missing_mode_or_path"]
    mode = args[0]
    if re.fullmatch(r"[0-7]{3,4}", mode) or re.fullmatch(r"[ugoa]*[+-=][rwxXstugo,]+", mode):
        reasons.append("valid_chmod_mode")
    else:
        return False, ["invalid_chmod_mode"]
    return True, reasons + ["has_target"]


def _flags_allowed(tokens: list[str], allowed_flags: set[str]) -> bool:
    for token in tokens[1:]:
        if token.startswith("-") and "=" in token:
            flag = token.split("=", 1)[0]
        else:
            flag = token
        if flag.startswith("-") and flag not in allowed_flags:
            return False
    return True


def _non_flag_args(tokens: list[str], flags_with_values: set[str] | None = None) -> list[str]:
    flags_with_values = flags_with_values or set()
    args: list[str] = []
    skip_next = False
    for token in tokens[1:]:
        if skip_next:
            skip_next = False
            continue
        if token in flags_with_values:
            skip_next = True
            continue
        if token.startswith("-"):
            continue
        args.append(token)
    return args


def _family_result(
    pattern: dict[str, Any],
    base: str,
    danger: str,
    reasons: list[str],
) -> dict[str, Any]:
    return _result(
        status=_STATUS_FAMILY,
        family=str(pattern.get("family")),
        base=base,
        confidence=str(pattern.get("confidence_on_match", "grammar_family")),
        danger=danger,
        reasons=reasons,
        matched_pattern_id=str(pattern.get("id")),
    )


def _suspicious_result(
    pattern: dict[str, Any],
    base: str,
    danger: str,
    reasons: list[str],
) -> dict[str, Any]:
    return _result(
        status=_STATUS_SUSPICIOUS,
        family=str(pattern.get("family")),
        base=base,
        confidence="grammar_suspicious",
        danger=danger,
        reasons=reasons,
        matched_pattern_id=str(pattern.get("id")),
    )


def _read_only_shape(
    tokens: list[str],
    pattern: dict[str, Any],
    allowed_flags: set[str],
    danger: str,
    reasons: list[str],
) -> dict[str, Any] | None:
    base = tokens[0]
    policy = str(pattern.get("positional_policy", ""))
    flags_with_values = {"-n", "-c", "-L", "-u", "-p", "-b", "-l", "-o", "--since", "--until", "-type", "-name", "-iname", "-maxdepth", "-mindepth", "-user", "-group", "-perm", "-size", "-mtime", "-s", "-qf"}

    if policy == "systemctl_mixed_actions":
        if len(tokens) == 1:
            return _suspicious_result(pattern, base, danger, reasons + ["missing_systemctl_subcommand"])
        read_only_subcommands = {
            "cat",
            "is-active",
            "is-enabled",
            "is-failed",
            "list-unit-files",
            "list-units",
            "show",
            "status",
        }
        state_change_subcommands = {
            "disable",
            "enable",
            "isolate",
            "mask",
            "poweroff",
            "reboot",
            "reload",
            "restart",
            "start",
            "stop",
            "unmask",
        }
        index = 1
        while index < len(tokens) and tokens[index].startswith("-"):
            index += 1
        if index >= len(tokens):
            return _suspicious_result(pattern, base, danger, reasons + ["missing_systemctl_subcommand"])
        subcommand = tokens[index]
        if subcommand not in read_only_subcommands | state_change_subcommands:
            return _suspicious_result(pattern, base, danger, reasons + ["unknown_systemctl_subcommand"])
        if not _flags_allowed(tokens, allowed_flags):
            return _suspicious_result(pattern, base, danger, reasons + ["unknown_flag"])
        if subcommand in read_only_subcommands:
            return _family_result(pattern, base, "read_only", reasons + ["systemctl_readout_shape"])
            return _family_result(pattern, base, "state_change", reasons + ["systemctl_state_change_shape"])

    if policy == "dnf_mixed_package_actions":
        if len(tokens) == 1:
            return _suspicious_result(pattern, base, danger, reasons + ["missing_dnf_subcommand"])
        subcommand = tokens[1]
        read_only_subcommands = {"check-update", "info", "list", "provides", "repolist", "repoquery", "search", "updateinfo"}
        state_change_subcommands = {
            "clean",
            "distro-sync",
            "downgrade",
            "erase",
            "groupinstall",
            "install",
            "makecache",
            "module",
            "remove",
            "update",
            "upgrade",
            "upgrade-minimal",
        }
        if subcommand == "history":
            if len(tokens) == 2 or (len(tokens) >= 3 and tokens[2] in {"info", "list"}):
                return _family_result(pattern, base, "read_only", reasons + ["dnf_history_readout_shape"])
            return _family_result(pattern, base, "state_change", reasons + ["dnf_history_state_change_shape"])
        if subcommand in read_only_subcommands:
            if not _flags_allowed(tokens, allowed_flags):
                return _suspicious_result(pattern, base, "read_only", reasons + ["unknown_flag"])
            return _family_result(pattern, base, "read_only", reasons + ["dnf_query_shape"])
        if subcommand in state_change_subcommands:
            return _family_result(pattern, base, "state_change", reasons + ["dnf_state_change_shape"])
        return _suspicious_result(pattern, base, danger, reasons + ["unknown_dnf_subcommand"])

    if policy == "repoquery_read_only":
        if len(tokens) < 3:
            return _suspicious_result(pattern, base, danger, reasons + ["missing_repoquery_flag_or_target"])
        if not _flags_allowed(tokens, allowed_flags):
            return _suspicious_result(pattern, base, danger, reasons + ["unknown_flag"])
        if not _non_flag_args(tokens):
            return _suspicious_result(pattern, base, danger, reasons + ["missing_repoquery_target"])
        return _family_result(pattern, base, danger, reasons + ["repoquery_readout_shape"])

    if policy == "tar_list_read_only":
        create_or_extract_flags = ("-c", "-x", "-r", "-u", "--create", "--extract", "--append", "--update", "--delete")
        if any(token.startswith(create_or_extract_flags) for token in tokens[1:]):
            return _suspicious_result(pattern, base, "state_change", reasons + ["tar_non_read_only_operation"])
        has_listing_flag = any(token in {"-tf", "-tvf", "--list"} for token in tokens[1:])
        has_file_reference = bool(_non_flag_args(tokens))
        for index, token in enumerate(tokens[1:], start=1):
            if token in {"-f", "--file"} and index + 1 < len(tokens):
                has_file_reference = True
        if has_listing_flag and has_file_reference:
            return _family_result(pattern, base, danger, reasons + ["tar_listing_shape"])
        return _suspicious_result(pattern, base, danger, reasons + ["not_tar_listing_shape"])

    if policy == "ip_inspection":
        if len(tokens) == 1:
            return _suspicious_result(pattern, base, danger, reasons + ["missing_ip_object"])
        if any(token in _NETWORK_CHANGE_WORDS for token in tokens[1:]):
            return _suspicious_result(pattern, base, "state_change", reasons + ["network_change_word"])
        if tokens[1] not in {"addr", "address", "link", "route"}:
            return _suspicious_result(pattern, base, danger, reasons + ["unsupported_ip_object"])
        if len(tokens) > 2 and tokens[2] != "show":
            return _suspicious_result(pattern, base, "state_change", reasons + ["unsupported_ip_action"])
        return _family_result(pattern, base, danger, reasons + ["ip_inspection_shape"])

    if policy == "nmcli_inspection":
        if tokens in (["nmcli", "connection", "show"], ["nmcli", "device", "status"]):
            return _family_result(pattern, base, danger, reasons + ["nmcli_inspection_shape"])
        if any(token in _NETWORK_CHANGE_WORDS for token in tokens[1:]):
            return _suspicious_result(pattern, base, "state_change", reasons + ["network_change_word"])
        return _suspicious_result(pattern, base, danger, reasons + ["unsupported_nmcli_shape"])

    if policy == "ping_limited_probe":
        if "-f" in tokens[1:]:
            return _suspicious_result(pattern, base, "state_change", reasons + ["flood_ping_flag"])
        if len(tokens) >= 4 and tokens[1] == "-c" and tokens[2].isdigit():
            return _family_result(pattern, base, danger, reasons + ["limited_ping_probe"])
        return _suspicious_result(pattern, base, danger, reasons + ["missing_limited_count"])

    if policy == "passwd_status_only":
        if len(tokens) in {2, 3} and tokens[1] == "-S":
            return _family_result(pattern, base, danger, reasons + ["passwd_status_shape"])
        return _suspicious_result(pattern, base, "state_change", reasons + ["not_status_only"])

    if policy == "chage_list_only":
        if len(tokens) >= 3 and tokens[1] == "-l":
            return _family_result(pattern, base, danger, reasons + ["chage_list_shape"])
        return _suspicious_result(pattern, base, "state_change", reasons + ["not_list_only"])

    if policy == "getent_inspection":
        databases = {"passwd", "group", "shadow", "hosts", "services", "protocols", "networks"}
        if len(tokens) >= 2 and tokens[1] in databases:
            return _family_result(pattern, base, danger, reasons + ["getent_lookup_shape"])
        return _suspicious_result(pattern, base, danger, reasons + ["unsupported_getent_database"])

    if policy == "optional_flags_then_required_target":
        if not _flags_allowed(tokens, allowed_flags):
            return _suspicious_result(pattern, base, danger, reasons + ["unknown_flag"])
        if _non_flag_args(tokens):
            return _family_result(pattern, base, danger, reasons + ["has_target"])
        return _suspicious_result(pattern, base, danger, reasons + ["missing_target"])

    if policy == "optional_flags_with_values_then_optional_target":
        if not _flags_allowed(tokens, allowed_flags):
            return _suspicious_result(pattern, base, danger, reasons + ["unknown_flag"])
        return _family_result(pattern, base, danger, reasons + ["readout_shape"])

    if policy == "base_or_optional_flags_and_optional_targets":
        if not _flags_allowed(tokens, allowed_flags):
            return _suspicious_result(pattern, base, danger, reasons + ["unknown_flag"])
        if any(word in tokens[1:] for word in _DANGEROUS_WORDS):
            return _suspicious_result(pattern, base, danger, reasons + ["dangerous_word"])
        return _family_result(pattern, base, danger, reasons + ["listing_shape"])

    if policy == "base_or_optional_flags_only":
        if not _flags_allowed(tokens, allowed_flags):
            return _suspicious_result(pattern, base, danger, reasons + ["unknown_flag"])
        if _non_flag_args(tokens):
            return _suspicious_result(pattern, base, danger, reasons + ["unexpected_argument"])
        return _family_result(pattern, base, danger, reasons + ["readout_shape"])

    if policy == "optional_flags_then_required_pattern":
        if not _flags_allowed(tokens, allowed_flags):
            return _suspicious_result(pattern, base, danger, reasons + ["unknown_flag"])
        if _non_flag_args(tokens):
            return _family_result(pattern, base, danger, reasons + ["has_pattern"])
        return _suspicious_result(pattern, base, danger, reasons + ["missing_pattern"])

    if policy == "find_read_only_predicates":
        if any(token in _DANGEROUS_FIND_TOKENS for token in tokens[1:]):
            return _suspicious_result(pattern, base, "unknown", reasons + ["dangerous_find_predicate"])
        if not _flags_allowed(tokens, allowed_flags):
            return _suspicious_result(pattern, base, danger, reasons + ["unknown_flag"])
        if _non_flag_args(tokens, flags_with_values):
            return _family_result(pattern, base, danger, reasons + ["read_only_find_shape"])
        return _suspicious_result(pattern, base, danger, reasons + ["missing_find_path"])

    if policy == "flags_with_optional_values_only":
        if len(tokens) == 1:
            return _family_result(pattern, base, danger, reasons + ["base_only_readout"])
        if tokens[1] in _DANGEROUS_WORDS:
            return _suspicious_result(pattern, base, danger, reasons + ["action_word_without_flag"])
        if not _flags_allowed(tokens, allowed_flags):
            return _suspicious_result(pattern, base, danger, reasons + ["unknown_flag"])
        return _family_result(pattern, base, danger, reasons + ["log_readout_shape"])

    if policy == "rpm_query_only":
        if len(tokens) == 1:
            return _suspicious_result(pattern, base, danger, reasons + ["missing_query_flag"])
        if tokens[1] in {"-V", "-Va"}:
            if not _flags_allowed(tokens, allowed_flags):
                return _suspicious_result(pattern, base, danger, reasons + ["unknown_flag"])
            return _family_result(pattern, base, danger, reasons + ["rpm_verify_shape"])
        if tokens[1] in _DANGEROUS_WORDS or not tokens[1].startswith("-q"):
            return _suspicious_result(pattern, base, danger, reasons + ["not_query_shape"])
        if not _flags_allowed(tokens, allowed_flags):
            return _suspicious_result(pattern, base, danger, reasons + ["unknown_flag"])
        return _family_result(pattern, base, danger, reasons + ["rpm_query_shape"])

    return None


def validate_command_shape(command: str) -> dict[str, Any]:
    """Return an advisory, non-executing command-shape classification."""

    if not isinstance(command, str):
        return _result(
            status=_STATUS_REJECT,
            reasons=["command_must_be_string"],
        )

    # Conservative advisory boundary: shlex does not parse shell evaluation.
    # Even quoted occurrences remain suspicious; never infer READ from them.
    if any(marker in command for marker in ('$(', '`', '\n', '\r', '<(', '>(')):
        return _result(status=_STATUS_SUSPICIOUS,confidence='grammar_suspicious',danger='unknown',
            reasons=['shell_evaluation_or_multiline'])

    stripped = command.strip()
    if not stripped:
        return _result(status=_STATUS_REJECT, reasons=["empty_command"])
    if _is_path_only(stripped):
        return _result(status=_STATUS_REJECT, reasons=["path_only"])
    if _is_flag_only(stripped):
        return _result(status=_STATUS_REJECT, reasons=["flag_only"])
    if _is_variable_only(stripped):
        return _result(status=_STATUS_REJECT, reasons=["variable_only"])
    if _is_glob_only(stripped):
        return _result(status=_STATUS_REJECT, reasons=["glob_only"])

    tokens, error = _split(stripped)
    if error:
        return _result(
            status=_STATUS_REJECT,
            confidence="grammar_reject",
            reasons=["tokenization_error", error],
        )
    if not tokens:
        return _result(status=_STATUS_REJECT, reasons=["empty_after_tokenization"])

    composed = _has_shell_composition(tokens, stripped)
    base = tokens[0]
    patterns = _pattern_by_base()
    pattern = patterns.get(base)
    if pattern is None:
        return _result(
            status=_STATUS_SUSPICIOUS,
            base=base,
            confidence="grammar_suspicious",
            danger="unknown",
            reasons=["unknown_base"] + (["shell_composition_present"] if composed else []),
        )

    reasons = ["known_base"]
    allowed_flags = set(pattern.get("allowed_flags", []))
    subcommands = set(pattern.get("subcommands", []))
    danger = str(pattern.get("danger_default", "unknown"))

    if composed:
        return _result(
            status=_STATUS_SUSPICIOUS,
            family=str(pattern.get("family")),
            base=base,
            confidence="grammar_suspicious",
            danger=danger,
            reasons=reasons + ["shell_composition_present"],
            matched_pattern_id=str(pattern.get("id")),
        )

    if base == "chmod":
        ok, shape_reasons = _chmod_shape(tokens)
        if ok and _flags_allowed(tokens, allowed_flags):
            return _result(
                status=_STATUS_FAMILY,
                family=str(pattern.get("family")),
                base=base,
                confidence=str(pattern.get("confidence_on_match", "grammar_family")),
                danger=danger,
                reasons=reasons + shape_reasons,
                matched_pattern_id=str(pattern.get("id")),
            )
        return _result(
            status=_STATUS_SUSPICIOUS,
            family=str(pattern.get("family")),
            base=base,
            confidence="grammar_suspicious",
            danger=danger,
            reasons=reasons + shape_reasons,
            matched_pattern_id=str(pattern.get("id")),
        )

    if base == "firewall-cmd":
        if len(tokens) == 1:
            return _result(
                status=_STATUS_SUSPICIOUS,
                family=str(pattern.get("family")),
                base=base,
                confidence="grammar_partial",
                danger=danger,
                reasons=reasons + ["missing_firewall_option"],
                matched_pattern_id=str(pattern.get("id")),
            )
        if _flags_allowed(tokens, allowed_flags):
            return _result(
                status=_STATUS_FAMILY,
                family=str(pattern.get("family")),
                base=base,
                confidence=str(pattern.get("confidence_on_match", "grammar_family")),
                danger=danger,
                reasons=reasons + ["allowed_firewall_flags"],
                matched_pattern_id=str(pattern.get("id")),
            )
        return _result(
            status=_STATUS_SUSPICIOUS,
            family=str(pattern.get("family")),
            base=base,
            confidence="grammar_suspicious",
            danger=danger,
            reasons=reasons + ["unknown_firewall_flag_or_argument"],
            matched_pattern_id=str(pattern.get("id")),
        )

    read_only_result = _read_only_shape(tokens, pattern, allowed_flags, danger, reasons)
    if read_only_result is not None:
        return read_only_result

    if len(tokens) == 1:
        return _result(
            status="partial",
            family=str(pattern.get("family")),
            base=base,
            confidence="grammar_partial",
            danger=danger,
            reasons=reasons + ["base_only"],
            matched_pattern_id=str(pattern.get("id")),
        )

    subcommand = tokens[1]
    if subcommands and subcommand not in subcommands:
        return _result(
            status=_STATUS_SUSPICIOUS,
            family=str(pattern.get("family")),
            base=base,
            confidence="grammar_suspicious",
            danger=danger,
            reasons=reasons + ["unknown_subcommand"],
            matched_pattern_id=str(pattern.get("id")),
        )
    if not _flags_allowed(tokens, allowed_flags):
        return _result(
            status=_STATUS_SUSPICIOUS,
            family=str(pattern.get("family")),
            base=base,
            confidence="grammar_suspicious",
            danger=danger,
            reasons=reasons + ["unknown_flag"],
            matched_pattern_id=str(pattern.get("id")),
        )

    return _result(
        status=_STATUS_FAMILY,
        family=str(pattern.get("family")),
        base=base,
        confidence=str(pattern.get("confidence_on_match", "grammar_family")),
        danger=danger,
        reasons=reasons + ["known_subcommand"],
        matched_pattern_id=str(pattern.get("id")),
    )
