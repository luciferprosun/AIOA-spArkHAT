"""Thin LITE composition of the original exact-provider CPL service."""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from critical_loop.policy import Limits
from critical_loop.service import CriticalPromptLoopService

from runtime.memory_patch.contracts.serialization import canonical_sha256
from runtime.memory_patch.errors import CommitOutcomeUnknown, MemoryPatchError
from runtime.memory_patch.learning.contracts import LearningPolicy
from runtime.memory_patch.learning.service import NativeLearning
from runtime.mission.contracts import MissionError


@dataclass(frozen=True, slots=True)
class LiteCPLPolicy:
    learning: LearningPolicy
    models: tuple[str, str, str, str]
    critic_families: tuple[str, str, str]
    mode: str = "SHADOW"
    allow_local_plan_start: bool = False
    input_units: int = 16384
    output_tokens: int = 512
    run_budget_usd: str = "0"
    digest: str = field(init=False)

    def __post_init__(self):
        if (
            type(self.learning) is not LearningPolicy
            or self.mode not in {"SHADOW", "ACTIVE"}
            or type(self.allow_local_plan_start) is not bool
            or type(self.models) is not tuple
            or len(self.models) != 4
            or type(self.critic_families) is not tuple
            or len(self.critic_families) != 3
            or any(
                type(x) is not str or not x or len(x.encode()) > 128
                for x in (*self.models, *self.critic_families)
            )
        ):
            raise MissionError("INVALID_CPL_POLICY")
        Limits.from_dict(
            {
                "input_tokens": self.input_units,
                "draft_tokens": self.output_tokens,
                "critic_tokens": self.output_tokens,
                "revision_tokens": self.output_tokens,
            }
        )
        object.__setattr__(
            self, "digest", canonical_sha256(self, exclude_fields=("digest",))
        )

    def limits(self):
        return {
            "input_tokens": self.input_units,
            "draft_tokens": self.output_tokens,
            "critic_tokens": self.output_tokens,
            "revision_tokens": self.output_tokens,
            "run_deadline_seconds": 30,
            "request_timeout_seconds": 5,
        }


@dataclass(frozen=True, slots=True, repr=False)
class CoreLiteCPLBindings:
    policy: LiteCPLPolicy
    service: object
    verifiers: tuple
    owns_service: bool = False


class LiteCPL:
    def __init__(self, profile, context, memory, bindings):
        if (
            type(bindings) is not CoreLiteCPLBindings
            or type(bindings.policy) is not LiteCPLPolicy
            or memory is None
            or type(bindings.owns_service) is not bool
        ):
            raise MissionError("INVALID_CPL_BINDINGS")
        policy = bindings.policy
        if (
            profile.cpl_profile_digest != policy.digest
            or profile.cpl_mode != policy.mode
            or profile.owner_scope != policy.learning.owner_scope
            or profile.provider_id != policy.learning.actor.provider
            or profile.model_id != policy.learning.actor.model_id
        ):
            raise MissionError("CPL_BINDING_MISMATCH")
        if (
            bindings.service is not None
            and type(bindings.service) is not CriticalPromptLoopService
        ):
            raise MissionError("ORIGINAL_CPL_SERVICE_REQUIRED")
        if (
            bindings.service is not None
            and bindings.service.scope == "TEST"
            and context.classification != "CONTRACT_TEST"
        ):
            raise MissionError("EXPLICIT_CPL_TEST_CONTEXT_REQUIRED")
        self.bindings, self.policy, self.memory = bindings, policy, memory
        self.service = bindings.service
        self.learning = NativeLearning(
            memory, policy.learning, bindings.verifiers, active=policy.mode == "ACTIVE"
        )
        if memory.learning is not None:
            raise MissionError("SECOND_LEARNING_WRITER_DENIED")
        memory.learning = self.learning
        memory.service.learning = self.learning
        self.last = None

    def describe(self):
        return {
            "mode": self.policy.mode,
            "provider_id": "openrouter",
            "contract": "cpl-1plus3plus1-v1",
            "execution_authority": False,
            "readiness": "NO_CRITIC" if self.service is None else "CONFIGURED_UNPROBED",
            "last": self.last,
        }

    def run(self, response, item, journal, now, stopped):
        base = {
            "execution_authority": False,
            "generation_requests": 0,
            "knowledge_write": "ZERO_WRITE",
            "provider_id": "openrouter",
        }
        if self.service is None or not self.policy.allow_local_plan_start or stopped():
            self.last = {
                **base,
                "status": "NO_CRITIC",
                "reason": "CPL_UNAVAILABLE_OR_DISABLED",
            }
            return self.last
        reservations, plan, started = (), None, False
        try:
            current = self.memory.last
            if current is None or current.status != "READY":
                raise MissionError("MEMORY_DEGRADED")
            # The bounded current evidence projection is quoted data. Allowed
            # verifier refs come only from this host policy, never model output.
            material = {
                "task_signature": self.policy.learning.task_signature,
                "task": self.policy.learning.task_instruction,
                "actor_proposal": response.parsed_payload["summary"],
                "allowed_verifier_refs": self.policy.learning.verifier_refs,
                "output": "Propose one minimal atomic claim; no authority or policy fields.",
            }
            plan = self.service.plan(
                {
                    "prompt": json.dumps(material, sort_keys=True),
                    "evidence": current.prompt_json,
                    "models": list(self.policy.models),
                    "limits": self.policy.limits(),
                    "run_budget_usd": self.policy.run_budget_usd,
                }
            )
            models = (*self.policy.models, self.policy.models[0])
            estimates = (self.policy.input_units + self.policy.output_tokens,) * 5
            reservations = journal.reserve_cpl_group(
                item["trace_id"], models, estimates, now
            )
            if stopped():
                raise MissionError("STOPPED_BEFORE_CPL")
            self.service.start(
                plan["run_id"],
                plan["plan_hash"],
                plan["nonce"],
                approval_source="LOCAL_CLI",
            )
            started = True
            result = self.service.wait(plan["run_id"], 35)
            calls = result["generation_requests"]
            results = result["provider_results"]
            for index, identifier in enumerate(reservations):
                status = (
                    "COMMITTED"
                    if index < len(results)
                    else "UNKNOWN"
                    if index < calls
                    else "RELEASED"
                )
                journal.settle(
                    identifier, status, reason="CPL_" + result["execution_status"]
                )
            reservations = ()
            base.update(
                generation_requests=calls,
                cpl_trace_ref=plan["run_id"],
                transport=result["transport"],
                reviews=len(result["reviews"]),
                uncertainty_count=sum(
                    len(r.get("uncertainty", ())) for r in result["reviews"]
                ),
            )
            if result["execution_status"] != "COMPLETED":
                self.last = {
                    **base,
                    "status": "NO_CRITIC",
                    "reason": result["error"] or "INCOMPLETE_CPL",
                }
            elif stopped():
                self.last = {
                    **base,
                    "status": "NO_CRITIC",
                    "reason": "STOPPED_BEFORE_LEARNING",
                }
            else:
                verification = self.service.verify(
                    plan["run_id"], result["evidence_chain"]
                )
                if verification.get("ok") is not True:
                    raise MissionError("CPL_TRACE_INTEGRITY_FAILED")
                learned = self.learning.evaluate(
                    response.parsed_payload["summary"],
                    result["final_answer"],
                    trace_id=item["trace_id"],
                    cpl_ref=plan["run_id"],
                    critic_families=self.policy.critic_families,
                )
                self.last = {**base, **learned}
        except Exception as error:
            # Never return raw dependency/provider text. Any started but unsettled
            # group remains charged and requires manual read-only reconciliation.
            for identifier in reservations:
                journal.settle(
                    identifier,
                    "UNKNOWN" if started else "RELEASED",
                    reason="CPL_INTERRUPTED",
                )
            if isinstance(error, CommitOutcomeUnknown):
                journal.state["reconciliation_required"] = True
            if started and reservations:
                try:
                    observed = self.service.get(plan["run_id"])["generation_requests"]
                    if type(observed) is int and 0 <= observed <= 5:
                        base["generation_requests"] = observed
                except Exception:
                    base["generation_requests_known"] = False
            self.last = {
                **base,
                "status": "NO_CRITIC",
                "reason": error.code
                if isinstance(error, MissionError)
                else error.code.value
                if isinstance(error, MemoryPatchError)
                else "CPL_OR_VERIFIER_UNAVAILABLE",
            }
        return self.last

    def close(self):
        if self.bindings.owns_service and self.service is not None:
            self.service.close()
