from __future__ import annotations

import unittest
from dataclasses import replace
from datetime import timedelta

from test_memory_patch_persistence_ports import NOW, make_admission

from runtime.core_admission import (
    AdmissionError,
    Capability,
    CoreActor,
    CoreAdmission,
    LocalOwnerAssignment,
    OwnerScope,
)


class CoreAuthorityTests(unittest.TestCase):
    def test_no_default_binding(self):
        boundary = CoreAdmission(clock=lambda: NOW)
        self.assertFalse(boundary.configured)
        with self.assertRaises(AdmissionError):
            boundary.local_operator(Capability.READ)

    def test_assignment_requires_explicit_approval_and_local_mode(self):
        fields = dict(
            scope=OwnerScope("tenant", "owner", "space", "slot"),
            allowed_capabilities=frozenset({Capability.READ}),
            hat_ids=frozenset({"hat"}),
            model_binding_ids=frozenset({"model"}),
        )
        for extras in (
            {},
            {"operator_approved": False},
            {"operator_approved": True, "hosted_multi_user": True},
        ):
            with self.assertRaises(AdmissionError):
                LocalOwnerAssignment(**fields, **extras)

    def test_json_flags_and_dicts_cannot_construct_core_authority(self):
        with self.assertRaises(AdmissionError):
            CoreAdmission(
                {"operator": True, "tenant_id": "tenant", "owner_id": "owner"}
            )
        boundary = make_admission()
        with self.assertRaises(AdmissionError):
            boundary.local_operator("owner_approval")
        with self.assertRaises(AdmissionError):
            boundary.require({"operator": True, "capability": "read"}, Capability.READ)

    def test_sealed_scope_capability_and_model_binding_cannot_be_replaced(self):
        boundary = make_admission()
        principal = boundary.local_operator(Capability.READ)
        alterations = [
            {"scope": replace(principal.scope, owner_id="other-owner")},
            {"scope": replace(principal.scope, tenant_id="other-tenant")},
            {"scope": replace(principal.scope, slot_id="other-slot")},
            {"capability": Capability.OWNER_APPROVAL},
            {"actor": CoreActor.COMMIT_SERVICE},
            {"hat_ids": frozenset({"other-hat"})},
            {"model_binding_ids": frozenset({"other-model"})},
            {"assignment_revision": 2},
            {"expires_at": NOW + timedelta(days=10)},
        ]
        for alteration in alterations:
            forged = replace(principal, **alteration)
            with (
                self.subTest(field=next(iter(alteration))),
                self.assertRaises(AdmissionError),
            ):
                boundary.require(forged, forged.capability)

    def test_principal_is_not_transferable_to_another_core_or_restart(self):
        first, restarted = make_admission(), make_admission()
        principal = first.local_operator(Capability.READ)
        with self.assertRaises(AdmissionError):
            restarted.require(principal, Capability.READ)

    def test_assignment_capabilities_are_not_inferred(self):
        boundary = make_admission(capabilities={Capability.READ})
        with self.assertRaises(AdmissionError):
            boundary.local_operator(Capability.COMMIT)

    def test_critic_has_candidate_purpose_only(self):
        boundary = make_admission()
        critic = boundary.critic_candidate()
        boundary.require(critic, Capability.CANDIDATE)
        self.assertIs(CoreActor.CRITIC, critic.actor)
        for capability in (
            Capability.OWNER_APPROVAL,
            Capability.COMMIT,
            Capability.ACTIVATE,
            Capability.EVIDENCE_CAPTURE,
        ):
            with self.assertRaises(AdmissionError):
                boundary.require(critic, capability)

    def test_owner_approval_and_commit_are_distinct_principals(self):
        boundary = make_admission()
        approval = boundary.local_operator(Capability.OWNER_APPROVAL)
        commit = boundary.local_operator(Capability.COMMIT)
        self.assertIs(CoreActor.OWNER_HUMAN, approval.actor)
        self.assertIs(CoreActor.COMMIT_SERVICE, commit.actor)
        with self.assertRaises(AdmissionError):
            boundary.require(approval, Capability.COMMIT)
        with self.assertRaises(AdmissionError):
            boundary.require(commit, Capability.OWNER_APPROVAL)

    def test_expired_and_closed_admission_denied(self):
        current = [NOW]
        boundary = make_admission(clock=lambda: current[0])
        principal = boundary.local_operator(Capability.READ)
        current[0] += timedelta(minutes=5)
        with self.assertRaises(AdmissionError):
            boundary.require(principal, Capability.READ)
        boundary.close()
        with self.assertRaises(AdmissionError):
            boundary.local_operator(Capability.READ)

    def test_private_principal_repr_does_not_echo_scope_or_session(self):
        boundary = make_admission()
        principal = boundary.local_operator(Capability.READ)
        for value in (*principal.scope.binding(), principal.actor_session_id):
            self.assertNotIn(value, repr(principal))
