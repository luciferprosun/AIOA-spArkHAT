"""Native NV06 contracts in the existing controlled LearningFixture."""

from dataclasses import replace
from datetime import timedelta

from nv04_support import LearningFixture

from runtime.core_admission import Capability
from runtime.memory_patch.learning.personal_contracts import (
    ConsentMode,
    PersonalDeltaPolicy,
)


class PersonalFixture(LearningFixture):
    def __init__(
        self,
        root,
        *,
        semantics=None,
        maximum_records=128,
        maximum_learning_bytes=262144,
        dynamics_mode=None,
        **kwargs,
    ):
        def bind(profile, bindings):
            policy = PersonalDeltaPolicy(
                profile.owner_scope,
                ("test-hat",),
                "test-hat",
                semantics,
                maximum_learning_bytes=maximum_learning_bytes,
            )
            learning = replace(
                bindings.cpl.policy.learning, maximum_records=maximum_records
            )
            cpl_policy = replace(bindings.cpl.policy, learning=learning)
            memory = replace(
                bindings.memory,
                dependencies=replace(
                    bindings.memory.dependencies,
                    packet_key=b"nv06-controlled-integrity-material-only",
                ),
            )
            profile, bindings = (
                replace(
                    profile,
                    personal_profile_digest=policy.digest,
                    cpl_profile_digest=cpl_policy.digest,
                ),
                replace(
                    bindings,
                    memory=memory,
                    cpl=replace(
                        bindings.cpl, policy=cpl_policy, personal_policy=policy
                    ),
                ),
            )
            if dynamics_mode is not None:
                from nv05_support import dynamics_binding

                profile, bindings = dynamics_binding(dynamics_mode)(profile, bindings)
            return profile, bindings

        super().__init__(root, dynamics=bind, **kwargs)
        self.personal = self.learning.personal

    def consent(self, mode=ConsentMode.AUTO_VERIFIED_SCOPED, **kwargs):
        return self.personal.set_consent(
            self.core.local_operator(Capability.OWNER_APPROVAL),
            mode,
            expected_revision=self.personal.describe()["revision"],
            allowed_hats=() if mode is ConsentMode.OFF else ("test-hat",),
            expires_at=self.now + timedelta(hours=1),
            **kwargs,
        )

    def learn(self, original=None, corrected=None, *, trace="episode-1"):
        from nv04_support import RIGHT, WRONG

        return self.learning.evaluate(
            WRONG if original is None else original,
            RIGHT if corrected is None else corrected,
            trace_id=trace,
            cpl_ref="controlled-core-proposal",
            critic_families=(),
        )
