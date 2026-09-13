"""Explicit closed boundary for a future separately approved live backend."""

from ..contract import ModuleConfig, NonZeroError


def require_certified_aws_backend(config: ModuleConfig):
    """Never read credentials or instantiate cloud SDK clients in native v1."""
    if not config.aws_enabled:
        raise NonZeroError("NONZERO_AWS_EXPLICIT_ENABLEMENT_REQUIRED")
    raise NonZeroError("NONZERO_AWS_BACKEND_NOT_CERTIFIED")
