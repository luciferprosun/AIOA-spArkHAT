"""Small untrusted-advice seam, not a provider manager or Strands application."""

from typing import Protocol

from ..models import ResourceEvidence


class ModelProviderError(RuntimeError):
    """Fixed typed planning boundary failure."""


class ModelProviderTimeoutError(ModelProviderError):
    pass


class ModelProviderRetryableError(ModelProviderError):
    pass


class ModelProviderNonRetryableError(ModelProviderError):
    pass


class ModelProvider(Protocol):
    def create_plan(self, evidence: ResourceEvidence) -> str:
        """Return advisory JSON with no authority to execute."""


class PortableAdvisor:
    """Deterministic local candidate; policy still independently validates it.

    A future real-model adapter must use Core's existing ProviderManager;
    native v1 deliberately registers no external transport or provider factory.
    """

    def __init__(self):
        self.plan_calls = 0

    def create_plan(self, evidence: ResourceEvidence) -> str:
        from ..policy import canonical_model_candidate

        self.plan_calls += 1
        return canonical_model_candidate(evidence).model_dump_json(exclude_none=True)
