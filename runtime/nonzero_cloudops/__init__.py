"""Native AIOA spArkHAT CloudOps capability with dependency-free discovery."""

from .contract import ModuleConfig, NonZeroError, module_descriptor
from .service import NonZeroCloudOpsService

__all__ = [
    "ModuleConfig",
    "NonZeroCloudOpsService",
    "NonZeroError",
    "module_descriptor",
]
