"""Fail-closed DynamoDB durable-truth configuration."""

import os
import re
from dataclasses import dataclass

from aioa_cloudops_agent.domain.errors import ContractValidationError

_TABLE_NAME_PATTERN = re.compile(r"^[A-Za-z0-9_.-]{3,255}$")


@dataclass(frozen=True, slots=True)
class DynamoDbSettings:
    """Non-secret settings required to connect the durable repository."""

    table_name: str
    consistent_reads: bool = True

    def __post_init__(self) -> None:
        if not isinstance(self.table_name, str) or not _TABLE_NAME_PATTERN.fullmatch(
            self.table_name
        ):
            raise ContractValidationError("table_name must be a valid DynamoDB table name")
        if not isinstance(self.consistent_reads, bool):
            raise ContractValidationError("consistent_reads must be a boolean")

    @classmethod
    def from_environment(cls) -> "DynamoDbSettings":
        """Load table metadata without inventing an in-memory fallback."""

        table_name = os.getenv("STATE_TABLE_NAME")
        if table_name is None:
            raise ContractValidationError("STATE_TABLE_NAME is required for durable truth")
        return cls(table_name=table_name)
