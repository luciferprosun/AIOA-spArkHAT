"""One optional native Core module. Import and discovery perform no I/O."""

from runtime.memory_patch.contract import (
    CONTRACT_VERSION,
    MODULE_ID,
    MemoryPatchConfig,
    module_descriptor,
)

__all__ = ["CONTRACT_VERSION", "MODULE_ID", "MemoryPatchConfig", "module_descriptor"]
