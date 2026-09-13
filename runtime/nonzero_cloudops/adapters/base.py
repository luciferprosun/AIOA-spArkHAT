"""Backend contract shared by the domain workflow; selection remains Core-owned."""

from typing import Protocol, runtime_checkable

from ..models import (
    LocalApprovalDecisionRecord,
    LocalExecutionIntent,
    LocalExecutionReceipt,
    LocalVerificationEvidence,
    RemediationProposal,
    ResourceEvidence,
)


@runtime_checkable
class ProtectedExecutor(Protocol):
    """Exact bound execution, durable replay lookup and independent read-back.

    A future live implementation must certify uncertain-outcome reconciliation;
    it cannot inherit the portable atomic-write assumption merely by conforming.
    """

    def execute(
        self,
        *,
        proposal: RemediationProposal,
        evidence: ResourceEvidence,
        approval: LocalApprovalDecisionRecord,
        intent: LocalExecutionIntent,
    ) -> LocalExecutionReceipt: ...

    def get_receipt(self, idempotency_key: str) -> LocalExecutionReceipt | None: ...

    def verify(self, receipt: LocalExecutionReceipt) -> LocalVerificationEvidence: ...
