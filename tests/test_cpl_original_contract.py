# Selective test port from AOIA-Core 5ec74f85256c260dadbc795143eb132b4119aab6.
# MIT License; Copyright (c) 2026 Lukasz Zuchowski. See LICENSE.
# Pure helper compatibility tests; end-to-end evidence is in test_cpl_service/web.
from __future__ import annotations

import ast
import json
import threading
import unittest
from dataclasses import replace
from pathlib import Path

from critical_loop.review import (
    MAX_OBSERVER_OUTPUT_TOKENS,
    MAX_RAW_OUTPUT_CHARS,
    NON_AUTHORITY_MARKER,
    OBSERVER_RESPONSE_JSON_SCHEMA,
    CriticalReviewRunner,
    ExecutionStatus,
    ObserverConfig,
    ReviewSnapshot,
    ReviewValidationError,
    SequentialReviewCanceled,
    build_final_revision_messages,
    canonical_sha256,
)
from providers.messages import ChatResult




def _snapshot(**changes) -> ReviewSnapshot:
    values = {
        "session_id": "session-1",
        "original_prompt": "Explain the bounded result.",
        "primary_response": "This is the primary response.",
        "primary_provider_id": "openrouter",
        "primary_model_id": "openai/gpt-4.1-nano",
        "knowledge_profile_id": "linux_unix",
        "evidence_text": "bounded evidence text",
    }
    values.update(changes)
    return ReviewSnapshot.create(**values)


def _config(
    number: int,
    *,
    enabled: bool = True,
    role: str = "Logic & Claims",
    provider: str = "connection-a",
    model: str = "vendor/model-a",
) -> ObserverConfig:
    return ObserverConfig(
        slot_id=f"observer-{number}",
        enabled=enabled,
        role_id=role,
        provider_connection_id=provider,
        model_id=model,
    )


def _structured(summary: str = "Concise review") -> str:
    return json.dumps(
        {
            "summary": summary,
            "findings": [
                {
                    "category": "logic",
                    "severity": "warning",
                    "title": "Check claim",
                    "detail": "The claim needs independent verification.",
                }
            ],
            "uncertainty": ["Source coverage is limited."],
            "evidence_conflicts": ["No direct conflict found."],
        }
    )


class _FakeClient:
    def __init__(self, outcomes: list[str | Exception] | None = None) -> None:
        self.outcomes = outcomes or [_structured()]
        self.calls: list[dict[str, object]] = []

    def send_chat(self, model, messages, max_tokens=None):
        self.calls.append({"model": model, "messages": tuple(messages), "max_tokens": max_tokens})
        outcome = self.outcomes[min(len(self.calls) - 1, len(self.outcomes) - 1)]
        if isinstance(outcome, Exception):
            raise outcome
        return ChatResult(content=outcome, model=model)


class _StructuredFakeClient(_FakeClient):
    def __init__(self, outcomes: list[str | Exception] | None = None) -> None:
        super().__init__(outcomes)
        self.structured_calls: list[dict[str, object]] = []

    def send_structured_chat(self, model, messages, *, json_schema, max_tokens=None):
        self.structured_calls.append(
            {
                "model": model,
                "messages": tuple(messages),
                "json_schema": json_schema,
                "max_tokens": max_tokens,
            }
        )
        return super().send_chat(model, messages, max_tokens=max_tokens)


class _SubstitutingFakeClient(_FakeClient):
    def send_chat(self, model, messages, max_tokens=None):
        result = super().send_chat(model, messages, max_tokens=max_tokens)
        return ChatResult(content=result.content, model="vendor/unrequested-model")


class _FakeResolver:
    def __init__(self, clients: dict[str, _FakeClient] | None = None) -> None:
        self.clients = clients or {}
        self.resolved: list[str] = []

    def resolve(self, provider_connection_id: str):
        self.resolved.append(provider_connection_id)
        return self.clients.get(provider_connection_id)


class SnapshotAndHashingTests(unittest.TestCase):
    def test_identical_inputs_produce_identical_hashes(self) -> None:
        first = _snapshot()
        second = _snapshot()
        self.assertEqual(first.evidence_digest, second.evidence_digest)
        self.assertEqual(first.snapshot_hash, second.snapshot_hash)

    def test_prompt_change_changes_snapshot_hash(self) -> None:
        self.assertNotEqual(_snapshot().snapshot_hash, _snapshot(original_prompt="Different prompt").snapshot_hash)

    def test_response_change_changes_snapshot_hash(self) -> None:
        self.assertNotEqual(_snapshot().snapshot_hash, _snapshot(primary_response="Different response").snapshot_hash)

    def test_model_change_changes_snapshot_hash(self) -> None:
        self.assertNotEqual(_snapshot().snapshot_hash, _snapshot(primary_model_id="vendor/other").snapshot_hash)

    def test_evidence_change_changes_digest_and_snapshot_hash(self) -> None:
        first = _snapshot()
        second = _snapshot(evidence_text="different bounded evidence")
        self.assertNotEqual(first.evidence_digest, second.evidence_digest)
        self.assertNotEqual(first.snapshot_hash, second.snapshot_hash)

    def test_canonical_hash_is_independent_of_dictionary_insertion_order(self) -> None:
        self.assertEqual(canonical_sha256({"a": 1, "b": 2}), canonical_sha256({"b": 2, "a": 1}))

    def test_api_key_like_material_is_rejected_before_serialization(self) -> None:
        with self.assertRaises(ReviewValidationError):
            _snapshot(original_prompt="Use sk-or-test-redacted")

    def test_forged_snapshot_hash_causes_zero_calls(self) -> None:
        snapshot = replace(_snapshot(), snapshot_hash="0" * 64)
        client = _FakeClient()
        resolver = _FakeResolver({"connection-a": client})
        with self.assertRaises(ReviewValidationError):
            CriticalReviewRunner().run(snapshot, (_config(1),), resolver)
        self.assertEqual(client.calls, [])
        self.assertEqual(resolver.resolved, [])

    def test_empty_prompt_or_response_fails_closed(self) -> None:
        with self.assertRaises(ReviewValidationError):
            _snapshot(original_prompt="")
        with self.assertRaises(ReviewValidationError):
            _snapshot(primary_response="")

    def test_no_evidence_snapshot_is_deterministic(self) -> None:
        first = _snapshot(knowledge_profile_id=None, evidence_text="")
        second = _snapshot(knowledge_profile_id=None, evidence_text="")
        self.assertEqual(first.evidence_digest, second.evidence_digest)
        self.assertEqual(first.snapshot_hash, second.snapshot_hash)


class ConfigurationValidationTests(unittest.TestCase):
    def test_more_than_three_configs_fails_before_calls(self) -> None:
        resolver = _FakeResolver({"connection-a": _FakeClient()})
        fourth = replace(_config(3), slot_id="observer-3")
        with self.assertRaises(ReviewValidationError):
            CriticalReviewRunner().run(_snapshot(), (_config(1), _config(2), _config(3), fourth), resolver)
        self.assertEqual(resolver.resolved, [])

    def test_duplicate_slots_fail_before_calls(self) -> None:
        resolver = _FakeResolver({"connection-a": _FakeClient()})
        with self.assertRaises(ReviewValidationError):
            CriticalReviewRunner().run(_snapshot(), (_config(1), _config(1)), resolver)
        self.assertEqual(resolver.resolved, [])

    def test_unsupported_or_out_of_order_slots_fail_before_calls(self) -> None:
        resolver = _FakeResolver({"connection-a": _FakeClient()})
        with self.assertRaises(ReviewValidationError):
            CriticalReviewRunner().run(_snapshot(), (replace(_config(1), slot_id="observer-4"),), resolver)
        with self.assertRaises(ReviewValidationError):
            CriticalReviewRunner().run(_snapshot(), (_config(2), _config(1)), resolver)
        self.assertEqual(resolver.resolved, [])

    def test_disabled_slot_does_not_resolve_or_call(self) -> None:
        resolver = _FakeResolver({"connection-a": _FakeClient()})
        result = CriticalReviewRunner().run(_snapshot(), (_config(1, enabled=False),), resolver)[0]
        self.assertEqual(result.execution_status, ExecutionStatus.DISABLED)
        self.assertEqual(resolver.resolved, [])

    def test_missing_provider_or_model_is_invalid_without_call(self) -> None:
        resolver = _FakeResolver({"connection-a": _FakeClient()})
        results = CriticalReviewRunner().run(
            _snapshot(),
            (_config(1, provider=""), _config(2, model="")),
            resolver,
        )
        self.assertEqual([item.execution_status for item in results], [ExecutionStatus.INVALID_CONFIGURATION] * 2)
        self.assertEqual(resolver.resolved, [])

    def test_malformed_provider_or_model_identifier_is_invalid_without_call(self) -> None:
        resolver = _FakeResolver({"connection-a": _FakeClient()})
        results = CriticalReviewRunner().run(
            _snapshot(),
            (_config(1, provider="bad connection"), _config(2, model="not-a-model")),
            resolver,
        )
        self.assertEqual([item.execution_status for item in results], [ExecutionStatus.INVALID_CONFIGURATION] * 2)
        self.assertEqual(resolver.resolved, [])

    def test_configuration_hash_is_deterministic_and_model_bound(self) -> None:
        first = _config(1)
        second = _config(1)
        changed = _config(1, model="vendor/other")
        self.assertEqual(first.configuration_hash, second.configuration_hash)
        self.assertNotEqual(first.configuration_hash, changed.configuration_hash)

    def test_configuration_rejects_secret_shaped_material(self) -> None:
        with self.assertRaises(ReviewValidationError):
            _config(1, provider="sk-or-test-redacted")


class ExactCallBudgetTests(unittest.TestCase):
    def _run_enabled_count(self, enabled_count: int):
        client = _FakeClient([_structured("one"), _structured("two"), _structured("three")])
        resolver = _FakeResolver({"connection-a": client})
        configs = tuple(_config(index, enabled=index <= enabled_count) for index in range(1, 4))
        results = CriticalReviewRunner().run(_snapshot(), configs, resolver)
        return client, resolver, results

    def test_zero_one_two_three_enabled_produce_exact_call_counts(self) -> None:
        for enabled_count in range(4):
            with self.subTest(enabled_count=enabled_count):
                client, _resolver, results = self._run_enabled_count(enabled_count)
                self.assertEqual(len(client.calls), enabled_count)
                self.assertEqual(len(results), 3)

    def test_exact_provider_connection_model_and_output_limit_are_unchanged(self) -> None:
        client = _FakeClient()
        resolver = _FakeResolver({"operator-connection": client})
        CriticalReviewRunner().run(
            _snapshot(),
            (_config(1, provider="operator-connection", model="vendor/exact-model"),),
            resolver,
        )
        self.assertEqual(resolver.resolved, ["operator-connection"])
        self.assertEqual(client.calls[0]["model"], "vendor/exact-model")
        self.assertEqual(client.calls[0]["max_tokens"], MAX_OBSERVER_OUTPUT_TOKENS)

    def test_duplicate_provider_and_model_choices_receive_independent_calls(self) -> None:
        client = _FakeClient([_structured("one"), _structured("two")])
        resolver = _FakeResolver({"connection-a": client})
        CriticalReviewRunner().run(_snapshot(), (_config(1), _config(2)), resolver)
        self.assertEqual(len(client.calls), 2)

    def test_native_structured_sender_receives_strict_observer_schema_once(self) -> None:
        client = _StructuredFakeClient()
        result = CriticalReviewRunner().run(
            _snapshot(), (_config(1),), _FakeResolver({"connection-a": client})
        )[0]

        self.assertEqual(result.execution_status, ExecutionStatus.COMPLETED)
        self.assertEqual(len(client.structured_calls), 1)
        self.assertEqual(len(client.calls), 1)
        call = client.structured_calls[0]
        self.assertIs(call["json_schema"], OBSERVER_RESPONSE_JSON_SCHEMA)
        self.assertTrue(OBSERVER_RESPONSE_JSON_SCHEMA["strict"])
        schema = OBSERVER_RESPONSE_JSON_SCHEMA["schema"]
        self.assertIsInstance(schema, dict)
        self.assertFalse(schema["additionalProperties"])
        self.assertEqual(call["max_tokens"], MAX_OBSERVER_OUTPUT_TOKENS)

    def test_provider_reported_model_substitution_is_rejected(self) -> None:
        result = CriticalReviewRunner().run(
            _snapshot(),
            (_config(1),),
            _FakeResolver({"connection-a": _SubstitutingFakeClient()}),
        )[0]
        self.assertEqual(result.execution_status, ExecutionStatus.PROVIDER_ERROR)
        self.assertEqual(result.error_category, "provider_model_mismatch")

    def test_observer_results_never_enter_later_requests(self) -> None:
        client = _FakeClient([_structured("UNIQUE-FIRST-OUTPUT"), _structured("second")])
        resolver = _FakeResolver({"connection-a": client})
        CriticalReviewRunner().run(_snapshot(), (_config(1), _config(2)), resolver)
        second_request = "\n".join(message.content for message in client.calls[1]["messages"])
        self.assertNotIn("UNIQUE-FIRST-OUTPUT", second_request)

    def test_knowledge_and_deterministic_empty_evidence_are_supplied(self) -> None:
        for snapshot, expected in ((_snapshot(), "bounded evidence text"), (_snapshot(knowledge_profile_id=None, evidence_text=""), "")):
            client = _FakeClient()
            CriticalReviewRunner().run(snapshot, (_config(1),), _FakeResolver({"connection-a": client}))
            payload = json.loads(client.calls[0]["messages"][1].content)
            self.assertEqual(payload["snapshot"]["evidence_text"], expected)
            self.assertEqual(payload["snapshot"]["snapshot_hash"], snapshot.snapshot_hash)

    def test_provider_exception_attempts_once_and_continues_other_slots(self) -> None:
        first = _FakeClient([RuntimeError("provider failed")])
        second = _FakeClient([_structured("second")])
        third = _FakeClient([_structured("third")])
        resolver = _FakeResolver({"one": first, "two": second, "three": third})
        results = CriticalReviewRunner().run(
            _snapshot(),
            (_config(1, provider="one"), _config(2, provider="two"), _config(3, provider="three")),
            resolver,
        )
        self.assertEqual([len(first.calls), len(second.calls), len(third.calls)], [1, 1, 1])
        self.assertEqual(results[0].execution_status, ExecutionStatus.PROVIDER_ERROR)
        self.assertEqual(results[1].execution_status, ExecutionStatus.COMPLETED)
        self.assertEqual(results[2].execution_status, ExecutionStatus.COMPLETED)

    def test_malformed_output_causes_no_repair_or_second_call(self) -> None:
        client = _FakeClient(["not-json"])
        result = CriticalReviewRunner().run(
            _snapshot(), (_config(1),), _FakeResolver({"connection-a": client})
        )[0]
        self.assertEqual(len(client.calls), 1)
        self.assertEqual(result.execution_status, ExecutionStatus.UNSTRUCTURED_OUTPUT)

    def test_single_json_code_fence_is_accepted_without_second_call(self) -> None:
        client = _FakeClient([f"```json\n{_structured('fenced result')}\n```"])
        result = CriticalReviewRunner().run(
            _snapshot(), (_config(1),), _FakeResolver({"connection-a": client})
        )[0]
        self.assertEqual(len(client.calls), 1)
        self.assertEqual(result.execution_status, ExecutionStatus.COMPLETED)
        self.assertEqual(result.concise_summary, "fenced result")

    def test_json_fence_with_surrounding_prose_remains_unstructured(self) -> None:
        client = _FakeClient([f"Result follows:\n```json\n{_structured()}\n```"])
        result = CriticalReviewRunner().run(
            _snapshot(), (_config(1),), _FakeResolver({"connection-a": client})
        )[0]
        self.assertEqual(len(client.calls), 1)
        self.assertEqual(result.execution_status, ExecutionStatus.UNSTRUCTURED_OUTPUT)

    def test_local_parser_enforces_the_declared_schema_item_bounds(self) -> None:
        payload = json.loads(_structured())
        payload["findings"] = payload["findings"] * 5
        client = _FakeClient([json.dumps(payload)])
        result = CriticalReviewRunner().run(
            _snapshot(), (_config(1),), _FakeResolver({"connection-a": client})
        )[0]
        self.assertEqual(result.execution_status, ExecutionStatus.UNSTRUCTURED_OUTPUT)

    def test_unavailable_selected_connection_does_not_fall_back(self) -> None:
        fallback_client = _FakeClient()
        resolver = _FakeResolver({"other-connection": fallback_client})
        result = CriticalReviewRunner().run(_snapshot(), (_config(1, provider="missing"),), resolver)[0]
        self.assertEqual(result.execution_status, ExecutionStatus.PROVIDER_UNAVAILABLE)
        self.assertEqual(fallback_client.calls, [])


class SequentialReviewTests(unittest.TestCase):
    def _configs(self) -> tuple[ObserverConfig, ...]:
        return (
            _config(1, role="Logic & Claims", model="vendor/model-one"),
            _config(2, role="Safety & Authority", model="vendor/model-two"),
            _config(3, role="Evidence & Consistency", model="vendor/model-three"),
        )

    def test_observers_run_once_in_order_with_only_earlier_metadata(self) -> None:
        client = _FakeClient([_structured("one"), _structured("two"), _structured("three")])
        results = CriticalReviewRunner().run_sequential(
            _snapshot(), self._configs(), _FakeResolver({"connection-a": client})
        )

        self.assertEqual([call["model"] for call in client.calls], [
            "vendor/model-one",
            "vendor/model-two",
            "vendor/model-three",
        ])
        payloads = [json.loads(call["messages"][1].content) for call in client.calls]
        self.assertEqual(payloads[0]["prior_observer_metadata"], [])
        self.assertEqual(
            [item["summary"] for item in payloads[1]["prior_observer_metadata"]],
            ["one"],
        )
        self.assertEqual(
            [item["summary"] for item in payloads[2]["prior_observer_metadata"]],
            ["one", "two"],
        )
        self.assertEqual([result.concise_summary for result in results], ["one", "two", "three"])

    def test_incomplete_sequential_setup_fails_before_any_call(self) -> None:
        client = _FakeClient()
        configs = list(self._configs())
        configs[1] = replace(configs[1], enabled=False)
        with self.assertRaises(ReviewValidationError):
            CriticalReviewRunner().run_sequential(
                _snapshot(), tuple(configs), _FakeResolver({"connection-a": client})
            )
        self.assertEqual(client.calls, [])

    def test_operator_cancel_stops_before_the_next_observer_call(self) -> None:
        client = _FakeClient([_structured("one"), _structured("two")])
        checks = iter((True, False))
        with self.assertRaises(SequentialReviewCanceled):
            CriticalReviewRunner().run_sequential(
                _snapshot(),
                self._configs(),
                _FakeResolver({"connection-a": client}),
                should_continue=lambda: next(checks),
            )
        self.assertEqual(len(client.calls), 1)

    def test_final_revision_contains_draft_evidence_and_three_reports(self) -> None:
        snapshot = _snapshot(primary_response="internal draft", evidence_text="bounded evidence")
        client = _FakeClient([_structured("one"), _structured("two"), _structured("three")])
        results = CriticalReviewRunner().run_sequential(
            snapshot, self._configs(), _FakeResolver({"connection-a": client})
        )
        messages = build_final_revision_messages(snapshot, results)
        payload = json.loads(messages[1].content)

        self.assertEqual(payload["original_prompt"], snapshot.original_prompt)
        self.assertEqual(payload["knowledge_evidence"], "bounded evidence")
        self.assertEqual(payload["initial_draft"], "internal draft")
        self.assertEqual([item["summary"] for item in payload["observer_reports"]], ["one", "two", "three"])
        self.assertNotIn("raw_untrusted_output", messages[1].content)

    def test_final_revision_fails_closed_when_an_observer_did_not_complete(self) -> None:
        snapshot = _snapshot()
        client = _FakeClient([_structured("one"), _structured("two"), _structured("three")])
        results = list(
            CriticalReviewRunner().run_sequential(
                snapshot, self._configs(), _FakeResolver({"connection-a": client})
            )
        )
        results[1] = replace(results[1], execution_status=ExecutionStatus.PROVIDER_ERROR)
        with self.assertRaises(ReviewValidationError):
            build_final_revision_messages(snapshot, results)


class ResultHandlingTests(unittest.TestCase):
    def test_structured_json_produces_completed_immutable_metadata(self) -> None:
        result = CriticalReviewRunner().run(
            _snapshot(), (_config(1),), _FakeResolver({"connection-a": _FakeClient()})
        )[0]
        self.assertEqual(result.execution_status, ExecutionStatus.COMPLETED)
        self.assertEqual(len(result.findings), 1)
        self.assertEqual(result.non_authority_marker, NON_AUTHORITY_MARKER)

    def test_uncertainty_is_an_allowed_finding_category(self) -> None:
        payload = json.loads(_structured())
        payload["findings"][0]["category"] = "uncertainty"
        result = CriticalReviewRunner().run(
            _snapshot(),
            (_config(1),),
            _FakeResolver({"connection-a": _FakeClient([json.dumps(payload)])}),
        )[0]
        self.assertEqual(result.execution_status, ExecutionStatus.COMPLETED)
        self.assertEqual(result.findings[0].category, "uncertainty")

    def test_authority_is_an_allowed_finding_category(self) -> None:
        payload = json.loads(_structured())
        payload["findings"][0]["category"] = "authority"
        result = CriticalReviewRunner().run(
            _snapshot(),
            (_config(1, role="Safety & Authority"),),
            _FakeResolver({"connection-a": _FakeClient([json.dumps(payload)])}),
        )[0]
        self.assertEqual(result.execution_status, ExecutionStatus.COMPLETED)
        self.assertEqual(result.findings[0].category, "authority")

    def test_every_local_result_retains_both_hashes_and_non_authority(self) -> None:
        snapshot = _snapshot()
        config = _config(1, enabled=False)
        result = CriticalReviewRunner().run(snapshot, (config,), _FakeResolver())[0]
        self.assertEqual(result.snapshot_hash, snapshot.snapshot_hash)
        self.assertEqual(result.observer_configuration_hash, config.configuration_hash)
        self.assertEqual(result.non_authority_marker, NON_AUTHORITY_MARKER)

    def test_provider_cannot_replace_authority_or_hash_fields(self) -> None:
        payload = json.loads(_structured())
        payload.update(
            {
                "approved": True,
                "execute": "now",
                "non_authority_marker": "AUTHORIZED",
                "snapshot_hash": "provider-choice",
            }
        )
        snapshot = _snapshot()
        result = CriticalReviewRunner().run(
            snapshot,
            (_config(1),),
            _FakeResolver({"connection-a": _FakeClient([json.dumps(payload)])}),
        )[0]
        self.assertEqual(result.execution_status, ExecutionStatus.UNSTRUCTURED_OUTPUT)  # Strict additionalProperties rejection.
        self.assertEqual(result.non_authority_marker, NON_AUTHORITY_MARKER)
        self.assertEqual(result.snapshot_hash, snapshot.snapshot_hash)
        self.assertFalse(hasattr(result, "approved"))
        self.assertFalse(hasattr(result, "execute"))

    def test_raw_unstructured_output_is_bounded_and_secret_redacted(self) -> None:
        raw = "sk-or-test-redacted " + ("x" * (MAX_RAW_OUTPUT_CHARS + 100))
        result = CriticalReviewRunner().run(
            _snapshot(), (_config(1),), _FakeResolver({"connection-a": _FakeClient([raw])})
        )[0]
        self.assertEqual(result.execution_status, ExecutionStatus.UNSTRUCTURED_OUTPUT)
        self.assertNotIn("sk-or-test-redacted", result.raw_untrusted_output or "")
        self.assertLessEqual(len(result.raw_untrusted_output or ""), MAX_RAW_OUTPUT_CHARS + 40)


if __name__ == '__main__':
    unittest.main()

