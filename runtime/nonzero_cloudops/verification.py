"""Typed independent read-back proof used by the bound execution workflow."""

from .models import LocalExecutionReceipt, LocalVerificationEvidence


def assert_linked_verification(
    receipt: LocalExecutionReceipt, proof: LocalVerificationEvidence
) -> None:
    if (
        proof.run_id != receipt.run_id
        or proof.proposal_id != receipt.proposal_id
        or proof.receipt_hash != receipt.receipt_hash
        or proof.target_resource_id != receipt.target_resource_id
        or proof.target_resource_type != receipt.target_resource_type
        or proof.operation_type != receipt.operation_type
    ):
        raise ValueError("NONZERO_VERIFICATION_BINDING_MISMATCH")
