"""Explicit private-executor failure classes used for fail-closed mapping."""


class RemediationError(RuntimeError):
    """Base private remediation failure."""


class RemediationDisabledError(RemediationError):
    """Live execution configuration is absent or disabled."""


class RemediationEmergencyDisabledError(RemediationDisabledError):
    """The independent executor-local emergency veto is active or unavailable."""


class RemediationScopeError(RemediationError):
    """Target, tag, state, or precondition is outside the approved sandbox."""


class RemediationDependencyError(RemediationError):
    """AWS dependency rejected the request before ambiguous execution."""


class RemediationExecutionError(RemediationError):
    """Provider explicitly reported that the approved mutation was unsuccessful."""


class RemediationAmbiguousError(RemediationError):
    """Acknowledgement may have been lost and must never be blindly replayed."""
