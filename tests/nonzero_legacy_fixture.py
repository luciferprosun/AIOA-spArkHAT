"""Historical intent input fixture; no alternative production key generator."""

from contextlib import contextmanager
from unittest.mock import patch


@contextmanager
def historical_intent_format():
    from nonzero_cloudops.models import LocalExecutionIntent
    from nonzero_cloudops.models.digest import compute_evidence_digest

    original = LocalExecutionIntent.create.__func__

    def legacy(cls, proposal, approval, *, registered_at):
        intent = original(cls, proposal, approval, registered_at=registered_at)
        values = intent.model_dump()
        values["idempotency_key"] = "local-exec:" + proposal.proposal_hash
        provisional = cls.model_construct(**values)
        values["intent_hash"] = compute_evidence_digest(provisional.binding_payload())
        return cls(**values)

    with patch.object(LocalExecutionIntent, "create", classmethod(legacy)):
        yield
