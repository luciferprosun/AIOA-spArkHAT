"""DynamoDB byte storage for Strands restart-safe latest snapshots."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping
from typing import Any, Protocol

from strands.types.exceptions import StorageError

_KEY_PATTERN = re.compile(r"^[A-Za-z0-9._:/-]{1,512}$")
_MAX_SNAPSHOT_BYTES = 300_000


class DynamoDbSnapshotClient(Protocol):
    def put_item(self, **kwargs: object) -> Mapping[str, Any]: ...

    def get_item(self, **kwargs: object) -> Mapping[str, Any]: ...


def _validated_key(key: str) -> str:
    if not isinstance(key, str) or _KEY_PATTERN.fullmatch(key) is None or ".." in key.split("/"):
        raise StorageError("snapshot key is invalid")
    return key


class DynamoDbSnapshotStorage:
    """Implement only durable latest-snapshot reads/writes; deletion/listing stay denied."""

    def __init__(self, client: DynamoDbSnapshotClient, table_name: str) -> None:
        if not table_name or table_name != table_name.strip():
            raise ValueError("table_name must be explicit")
        self._client = client
        self._table_name = table_name

    @staticmethod
    def _key(key: str) -> dict[str, dict[str, str]]:
        validated = _validated_key(key)
        digest = hashlib.sha256(validated.encode("utf-8")).hexdigest()
        return {"PK": {"S": f"STRANDS_SNAPSHOT#{digest}"}, "SK": {"S": "LATEST"}}

    async def write(self, key: str, data: bytes) -> None:
        if not isinstance(data, bytes) or len(data) > _MAX_SNAPSHOT_BYTES:
            raise StorageError("snapshot payload is invalid")
        try:
            self._client.put_item(
                TableName=self._table_name,
                Item={
                    **self._key(key),
                    "entity_type": {"S": "STRANDS_SNAPSHOT"},
                    "blob": {"B": data},
                },
            )
        except StorageError:
            raise
        except Exception as error:
            raise StorageError("snapshot write is unavailable") from error

    async def read(self, key: str) -> bytes | None:
        try:
            response = self._client.get_item(
                TableName=self._table_name,
                Key=self._key(key),
                ConsistentRead=True,
            )
        except StorageError:
            raise
        except Exception as error:
            raise StorageError("snapshot read is unavailable") from error
        item = response.get("Item") if isinstance(response, Mapping) else None
        if item is None:
            return None
        try:
            if item["entity_type"] != {"S": "STRANDS_SNAPSHOT"}:
                raise KeyError("entity type")
            value = item["blob"]["B"]
            if not isinstance(value, bytes):
                raise TypeError("blob")
            return value
        except (KeyError, TypeError) as error:
            raise StorageError("snapshot item is malformed") from error

    async def delete(self, key: str) -> None:
        _validated_key(key)
        raise StorageError("snapshot deletion is not authorized")

    async def list(self, query: str = "") -> list[str]:
        if not isinstance(query, str) or ".." in query.split("/"):
            raise StorageError("snapshot prefix is invalid")
        raise StorageError("snapshot listing is not authorized")
