"""Read campaign progress and recommend one local task without effect authority.

The manifest and evidence references are caller-provided data. The planner
keeps list order and never opens an evidence reference.
"""

from __future__ import annotations

from graphlib import CycleError, TopologicalSorter
import json
import re
from typing import Any


MANIFEST_SCHEMA = "aioa.task-continuation.v1"
_DEFAULT_BASE_SHA = "30c24a36923aaf834475003723d994fbca40b3ea"
_MANIFEST_FIELDS = {"schema", "base_sha", "tasks"}
_TASK_FIELDS = {"task_id", "status", "dependencies", "evidence_refs", "scope"}
_STATUSES = {
    "DONE", "READY", "BLOCKED_OWNER", "BLOCKED_SECURITY", "BLOCKED_EXTERNAL", "NOT_STARTED",
}
_SCOPES = {"LOCAL_OFFLINE", "EXTERNAL_GATED"}
_MAX_TASKS = 32


def _has_fields(value: Any, fields: set[str]) -> bool:
    return type(value) is dict and all(type(key) is str for key in value) and value.keys() == fields


def _is_text(value: Any) -> bool:
    return type(value) is str and bool(value) and value.isprintable() and value == value.strip()


def _index_tasks(manifest: Any, expected_base_sha: str) -> dict[str, dict[str, Any]]:
    if not _has_fields(manifest, _MANIFEST_FIELDS):
        raise ValueError("invalid campaign manifest fields")
    if type(manifest["schema"]) is not str or manifest["schema"] != MANIFEST_SCHEMA:
        raise ValueError("unsupported campaign manifest schema")
    if type(expected_base_sha) is not str or re.fullmatch(r"[0-9a-f]{40}", expected_base_sha) is None:
        raise ValueError("expected base SHA must be a lowercase Git commit SHA")
    if type(manifest["base_sha"]) is not str or manifest["base_sha"] != expected_base_sha:
        raise ValueError("campaign base SHA does not match the trusted base")

    tasks = manifest["tasks"]
    if type(tasks) is not list or len(tasks) > _MAX_TASKS:
        raise ValueError("campaign tasks must be a list with at most 32 entries")

    by_id = {}
    for task in tasks:
        if not _has_fields(task, _TASK_FIELDS):
            raise ValueError("invalid campaign task fields")
        task_id = task["task_id"]
        if not _is_text(task_id) or task_id in by_id:
            raise ValueError("task IDs must be nonempty and unique")
        if type(task["status"]) is not str or task["status"] not in _STATUSES:
            raise ValueError("unsupported campaign task status")
        if type(task["scope"]) is not str or task["scope"] not in _SCOPES:
            raise ValueError("unsupported campaign task scope")
        dependencies = task["dependencies"]
        if type(dependencies) is not list or not all(_is_text(item) for item in dependencies):
            raise ValueError("dependencies must be a list of task IDs")
        if len(dependencies) != len(set(dependencies)):
            raise ValueError("duplicate task dependency")
        evidence = task["evidence_refs"]
        if type(evidence) is not list or not all(_is_text(item) for item in evidence):
            raise ValueError("evidence references must be a list of nonempty strings")
        by_id[task_id] = task
    return by_id


def _progress(tasks: dict[str, dict[str, Any]]) -> dict[str, str]:
    graph = {task_id: task["dependencies"] for task_id, task in tasks.items()}
    if any(dependency not in tasks for dependencies in graph.values() for dependency in dependencies):
        raise ValueError("unknown task dependency")
    try:
        order = tuple(TopologicalSorter(graph).static_order())
    except CycleError:
        raise ValueError("campaign task dependencies contain a cycle") from None

    progress = {}
    for task_id in order:
        task = tasks[task_id]
        status = task["status"]
        dependencies_done = all(progress[dependency] == "DONE" for dependency in graph[task_id])
        if status == "DONE" and (not task["evidence_refs"] or not dependencies_done):
            status = "UNVERIFIED_DONE"
        elif status == "READY":
            if task["scope"] == "EXTERNAL_GATED":
                status = "EXTERNAL_GATED"
            elif dependencies_done:
                status = "LOCAL_READY"
            else:
                status = "WAITING_DEPENDENCIES"
        progress[task_id] = status
    return progress


def _selection(tasks: dict[str, dict[str, Any]], progress: dict[str, str]) -> dict[str, str | None]:
    task_id = next((key for key in tasks if progress[key] == "LOCAL_READY"), None)
    if task_id is None:
        status = "NO_ELIGIBLE_SAFE_TASK"
        reason = "No ready local task has all dependencies marked DONE with evidence references."
    else:
        status = "NEXT"
        reason = "First ready local task with all dependencies marked DONE with evidence references."
    return {"status": status, "task_id": task_id, "reason": reason, "effect_authority": "NONE"}


def select_next_local_task(
    manifest: Any, *, expected_base_sha: str = _DEFAULT_BASE_SHA,
) -> dict[str, str | None]:
    """Recommend a task using the pinned NZ16 base or an independently trusted base."""
    tasks = _index_tasks(manifest, expected_base_sha)
    return _selection(tasks, _progress(tasks))


def build_resume_summary(
    manifest: Any, selection: Any, *, expected_base_sha: str = _DEFAULT_BASE_SHA,
) -> str:
    """Return JSON progress for the current manifest and its validated recommendation."""
    tasks = _index_tasks(manifest, expected_base_sha)
    progress = _progress(tasks)
    expected = _selection(tasks, progress)
    if not _has_fields(selection, set(expected)) or any(
        type(selection[key]) is not type(value) or selection[key] != value
        for key, value in expected.items()
    ):
        raise ValueError("selection does not match the campaign manifest")

    return json.dumps(
        {
            "schema": "aioa.task-continuation.resume.v1",
            "base_sha": manifest["base_sha"],
            "effect_authority": "NONE",
            "selection": expected,
            "tasks": [
                {
                    "task_id": task_id,
                    "status": progress[task_id],
                    "scope": task["scope"],
                    "evidence_refs": task["evidence_refs"],
                }
                for task_id, task in tasks.items()
            ],
        },
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    ) + "\n"
