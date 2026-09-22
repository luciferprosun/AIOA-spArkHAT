"""Explicit controlled-corpus dynamics binding and evidence-version fixtures."""

from __future__ import annotations

import json
from dataclasses import replace

from nv04_support import RIGHT, WRONG, LearningFixture, actor_response

from runtime.memory_patch.learning.dynamics import CoreDynamicsBindings, DynamicsPolicy
from runtime.mission.lite_contracts import MODEL
from runtime.providers.live_gate import require_transport_authorization


def dynamics_binding(mode="SHADOW", *, policy_changes=None, context_changes=None):
    def bind(profile, bindings):
        policy = DynamicsPolicy(
            profile.owner_scope,
            mode=mode,
            controlled_test_corpus=mode == "ACTIVE",
            **(policy_changes or {}),
        )
        if context_changes:
            memory = replace(bindings.memory.profile, **context_changes)
            bindings = replace(
                bindings, memory=replace(bindings.memory, profile=memory)
            )
            profile = replace(profile, memory_profile_digest=memory.digest)
        profile = replace(
            profile,
            dvm_mode=mode,
            pheromone_mode=mode,
            dynamics_profile_digest=policy.digest,
        )
        return profile, replace(bindings, dynamics=CoreDynamicsBindings(policy))

    return bind


class DynamicsFixture(LearningFixture):
    def __init__(
        self,
        root,
        *,
        mode="SHADOW",
        policy_changes=None,
        context_changes=None,
        **kwargs,
    ):
        super().__init__(
            root,
            dynamics=dynamics_binding(
                mode, policy_changes=policy_changes, context_changes=context_changes
            ),
            **kwargs,
        )
        self.dynamics = self.learning.dynamics

    def change_evidence_version(self):
        for identifier, record in self.catalog.records.items():
            self.metadata[identifier] = {
                **self.metadata[identifier],
                "document_identity": "policy",
                "provision_identifier": "rule",
                "version_identity": "v1",
                "superseded_by": ["v2"],
            }
            self._source(record)
        self.add_source(
            "policy",
            "v2",
            RIGHT,
            metadata={
                "document_identity": "policy",
                "provision_identifier": "rule",
                "version_identity": "v2",
                "supersedes": ["v1"],
                "effective_from": "2020-01-01",
                "verified_at": self.now.isoformat(),
            },
        )
        self.save_corpus()


class ContextDependentActor:
    """Deterministic actor test double: correct only when D1 is actually injected.

    Proves data flow through the actual NVIDIA adapter. It is not a live LLM or
    a claim of learned real-world accuracy/performance.
    """

    transport_scope = "TEST"

    def __init__(self):
        self.calls = []
        self.injected_delta_refs = []

    def __call__(self, payload, key, timeout, maximum, authorization=None):
        require_transport_authorization(
            authorization,
            "TEST",
            transport=self,
            payload=payload,
            timeout=timeout,
            max_bytes=maximum,
            provider_id="nvidia",
            model_id=MODEL,
        )
        request = json.loads(payload)
        context = json.loads(request["messages"][-1]["content"])
        refs = [
            r["ref"]
            for r in context.get("quoted_advisory_context", ())
            if r.get("lane") == "VERIFIED_DELTA_ADVISORY" and r.get("text") == RIGHT
        ]
        self.injected_delta_refs.extend(refs)
        self.calls.append(request)
        return actor_response(RIGHT if refs else WRONG)
