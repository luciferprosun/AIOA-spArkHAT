"""Inspectable injected domain components, with no server or auth lifecycle."""

from dataclasses import dataclass

from .adapters.advisory import PortableAdvisor
from .adapters.portable import (
    PortableExecutor,
    PortableResourceReader,
    PortableStateStore,
)
from .execution import BoundExecutionWorkflow
from .planning import InvestigationWorkflow
from .state.repository import DomainStateRepository


@dataclass(frozen=True, slots=True)
class NativeComponents:
    investigation: InvestigationWorkflow
    execution: BoundExecutionWorkflow
    repository: DomainStateRepository
    reader: PortableResourceReader
    advisor: PortableAdvisor
    executor: PortableExecutor
    inventory: PortableStateStore
