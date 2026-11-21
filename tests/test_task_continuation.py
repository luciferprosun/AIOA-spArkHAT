"""Offline tests for campaign progress and advisory selection."""

from copy import deepcopy
import importlib
import importlib.util
import json
import unittest


BASE_SHA = "30c24a36923aaf834475003723d994fbca40b3ea"
OTHER_SHA = "0123456789abcdef0123456789abcdef01234567"


def task(task_id, status="READY", *, dependencies=(), evidence=(), scope="LOCAL_OFFLINE"):
    return {
        "task_id": task_id,
        "status": status,
        "dependencies": list(dependencies),
        "evidence_refs": list(evidence),
        "scope": scope,
    }


def manifest(*tasks, base_sha=BASE_SHA):
    return {"schema": "aioa.task-continuation.v1", "base_sha": base_sha, "tasks": list(tasks)}


def campaign():
    return manifest(
        task("NZ13", "DONE", evidence=("evidence/NZ13_CHECKPOINT.json",)),
        task("NZ14#3", "BLOCKED_OWNER"),
        task("NZ15#69", "BLOCKED_SECURITY"),
        task("NZ16", dependencies=("NZ13",)),
        task("NZ17", dependencies=("NZ16",)),
        task("NZ18", "BLOCKED_EXTERNAL", scope="EXTERNAL_GATED"),
        task("NZ19", "NOT_STARTED"),
    )


class TaskContinuationTests(unittest.TestCase):
    def setUp(self):
        name = "runtime.tools.task_continuation"
        self.assertIsNotNone(importlib.util.find_spec(name), "task continuation module is missing")
        self.planner = importlib.import_module(name)

    def test_selects_nz16_with_unrelated_owner_and_security_blocks(self):
        recommendation = self.planner.select_next_local_task(campaign())
        self.assertEqual(recommendation["status"], "NEXT")
        self.assertEqual(recommendation["task_id"], "NZ16")
        self.assertEqual(recommendation["effect_authority"], "NONE")

    def test_evidenced_nz16_done_advances_to_nz17(self):
        workflow = campaign()
        workflow["tasks"][3] = task(
            "NZ16", "DONE", dependencies=("NZ13",), evidence=("evidence/NZ16_TEST_RESULTS.json",)
        )
        self.assertEqual(self.planner.select_next_local_task(workflow)["task_id"], "NZ17")

    def test_done_without_evidence_does_not_unlock_its_dependents(self):
        workflow = campaign()
        workflow["tasks"][3] = task("NZ16", "DONE", dependencies=("NZ13",))
        recommendation = self.planner.select_next_local_task(workflow)
        self.assertEqual(recommendation["status"], "NO_ELIGIBLE_SAFE_TASK")
        self.assertIsNone(recommendation["task_id"])
        summary = json.loads(self.planner.build_resume_summary(workflow, recommendation))
        states = {row["task_id"]: row["status"] for row in summary["tasks"]}
        self.assertEqual(states["NZ16"], "UNVERIFIED_DONE")
        self.assertEqual(states["NZ17"], "WAITING_DEPENDENCIES")

    def test_blocked_ancestor_is_not_hidden_by_done_descendant(self):
        workflow = manifest(
            task("local", dependencies=("claimed",)),
            task("claimed", "DONE", dependencies=("security",), evidence=("checkpoint.json",)),
            task("security", "BLOCKED_SECURITY", evidence=("review.json",)),
            task("independent"),
        )
        self.assertEqual(self.planner.select_next_local_task(workflow)["task_id"], "independent")

    def test_blocked_statuses_do_not_grant_progress_even_with_evidence(self):
        for status in ("BLOCKED_OWNER", "BLOCKED_SECURITY", "BLOCKED_EXTERNAL", "NOT_STARTED"):
            with self.subTest(status=status):
                workflow = manifest(
                    task("blocked", status, evidence=("diagnostic.json",)),
                    task("dependent", dependencies=("blocked",)),
                )
                selection = self.planner.select_next_local_task(workflow)
                self.assertEqual(selection["status"], "NO_ELIGIBLE_SAFE_TASK")
                self.assertEqual(selection["effect_authority"], "NONE")

    def test_unknown_and_unrecognized_statuses_are_refused(self):
        for status in ("UNKNOWN", "BLOCKED", "APPROVED", ["READY"]):
            with self.subTest(status=status):
                workflow = manifest(task("safe"), task("invalid", status))
                with self.assertRaises(ValueError):
                    self.planner.select_next_local_task(workflow)

    def test_replay_of_same_json_is_deterministic_and_preserves_input(self):
        workflow = campaign()
        original = deepcopy(workflow)
        replayed = json.loads(json.dumps(workflow, sort_keys=True))
        first = self.planner.select_next_local_task(workflow)
        second = self.planner.select_next_local_task(replayed)
        self.assertEqual(first, second)
        self.assertEqual(
            self.planner.build_resume_summary(workflow, first),
            self.planner.build_resume_summary(replayed, second),
        )
        self.assertEqual(workflow, original)

    def test_first_eligible_uses_manifest_order(self):
        workflow = manifest(task("later-id"), task("earlier-id"))
        self.assertEqual(self.planner.select_next_local_task(workflow)["task_id"], "later-id")

    def test_duplicate_ids_are_refused_even_after_ready_task(self):
        workflow = manifest(task("ready"), task("duplicate"), task("duplicate", "BLOCKED_OWNER"))
        with self.assertRaises(ValueError):
            self.planner.select_next_local_task(workflow)

    def test_cycles_are_refused_even_in_disconnected_tasks(self):
        for invalid in (
            (task("cycle", dependencies=("cycle",)),),
            (task("a", dependencies=("b",)), task("b", dependencies=("a",))),
        ):
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValueError):
                    self.planner.select_next_local_task(manifest(task("ready"), *invalid))

    def test_missing_dependency_is_refused(self):
        with self.assertRaises(ValueError):
            self.planner.select_next_local_task(manifest(task("ready", dependencies=("absent",))))

    def test_manifest_requires_exact_schema_and_json_field_types(self):
        invalid = (
            None,
            {**manifest(), "schema": "other"},
            {"schema": "aioa.task-continuation.v1", "tasks": []},
            {**manifest(), "tasks": {}},
            manifest("ready"),
            manifest({key: value for key, value in task("ready").items() if key != "scope"}),
            manifest(task(" ")),
            manifest({**task("ready"), "scope": "OTHER"}),
            manifest({**task("ready"), "dependencies": "other"}),
            manifest(task("ready", evidence=(" ",))),
            manifest(task("ready", evidence=(None,))),
        )
        for workflow in invalid:
            with self.subTest(workflow=workflow):
                with self.assertRaises(ValueError):
                    self.planner.select_next_local_task(workflow)

    def test_empty_string_is_neither_a_task_id_nor_a_done_evidence_reference(self):
        with self.assertRaises(ValueError):
            self.planner.select_next_local_task(manifest(task("")))
        with self.assertRaises(ValueError):
            self.planner.select_next_local_task(manifest(
                task("claimed", "DONE", evidence=("",)),
                task("dependent", dependencies=("claimed",)),
            ))

    def test_task_count_bound_and_empty_manifest(self):
        empty = self.planner.select_next_local_task(manifest())
        self.assertEqual(empty["status"], "NO_ELIGIBLE_SAFE_TASK")
        tasks = [task(f"job-{number}", "NOT_STARTED") for number in range(31)]
        self.assertEqual(
            self.planner.select_next_local_task(manifest(*tasks, task("last")))["task_id"], "last"
        )
        with self.assertRaises(ValueError):
            self.planner.select_next_local_task(manifest(*tasks, task("last"), task("excess")))

    def test_invalid_and_other_valid_bases_are_refused(self):
        for sha in (OTHER_SHA, BASE_SHA.upper(), "not-a-sha", None):
            with self.subTest(sha=sha):
                with self.assertRaises(ValueError):
                    self.planner.select_next_local_task(manifest(task("ready"), base_sha=sha))

    def test_caller_can_supply_independently_pinned_base(self):
        workflow = manifest(task("ready"), base_sha=OTHER_SHA)
        choice = self.planner.select_next_local_task(workflow, expected_base_sha=OTHER_SHA)
        self.assertEqual(choice["task_id"], "ready")
        summary = self.planner.build_resume_summary(workflow, choice, expected_base_sha=OTHER_SHA)
        self.assertEqual(json.loads(summary)["base_sha"], OTHER_SHA)
        with self.assertRaises(ValueError):
            self.planner.build_resume_summary(workflow, choice)

    def test_ready_external_task_is_never_selected_locally(self):
        external = task("external", scope="EXTERNAL_GATED")
        workflow = manifest(external, task("local"))
        self.assertEqual(self.planner.select_next_local_task(workflow)["task_id"], "local")
        only_external = self.planner.select_next_local_task(manifest(external))
        self.assertEqual(only_external["status"], "NO_ELIGIBLE_SAFE_TASK")
        self.assertEqual(only_external["effect_authority"], "NONE")

    def test_authority_shaped_fields_are_refused_at_both_levels(self):
        for field, value in (
            ("approval", {"GO_PR": True}),
            ("command", ["synthetic-effect-placeholder"]),
            ("expected_base_sha", OTHER_SHA),
        ):
            with self.subTest(field=field):
                for workflow in (
                    {**manifest(task("job")), field: value},
                    manifest({**task("job"), field: value}),
                ):
                    with self.assertRaises(ValueError):
                        self.planner.select_next_local_task(workflow)

    def test_summary_distinguishes_local_ready_security_block_and_completion(self):
        workflow = campaign()
        summary = json.loads(
            self.planner.build_resume_summary(workflow, self.planner.select_next_local_task(workflow))
        )
        rows = {row["task_id"]: row for row in summary["tasks"]}
        self.assertEqual(summary["base_sha"], BASE_SHA)
        self.assertEqual(summary["selection"]["task_id"], "NZ16")
        self.assertTrue(summary["selection"]["reason"])
        self.assertEqual(summary["effect_authority"], "NONE")
        self.assertEqual(rows["NZ16"]["status"], "LOCAL_READY")
        self.assertEqual(rows["NZ15#69"]["status"], "BLOCKED_SECURITY")
        self.assertEqual(rows["NZ13"]["status"], "DONE")
        self.assertEqual(rows["NZ13"]["evidence_refs"], ["evidence/NZ13_CHECKPOINT.json"])
        self.assertNotIn("deployment", summary)
        self.assertNotIn("approval", summary)

    def test_summary_refuses_a_forged_selection(self):
        workflow = campaign()
        selection = self.planner.select_next_local_task(workflow)
        for forged in (
            {**selection, "task_id": "NZ15#69"},
            {**selection, "effect_authority": "GO_NATIVE"},
            {**selection, "approval": "GO_PR"},
        ):
            with self.subTest(forged=forged):
                with self.assertRaises(ValueError):
                    self.planner.build_resume_summary(workflow, forged)


if __name__ == "__main__":
    unittest.main()
