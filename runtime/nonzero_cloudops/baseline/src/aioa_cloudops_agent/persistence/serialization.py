"""Lossless Pydantic-to-DynamoDB serialization for canonical NZ records."""

from collections.abc import Mapping
from math import isfinite
from typing import Any

from pydantic import BaseModel, ValidationError

from aioa_cloudops_agent.nz.errors import StorageDependencyError

DynamoAttribute = dict[str, Any]


def to_dynamo_attribute(value: object) -> DynamoAttribute:
    """Encode the JSON-compatible subset used by immutable NZ contracts."""

    if value is None:
        return {"NULL": True}
    if isinstance(value, bool):
        return {"BOOL": value}
    if isinstance(value, str):
        return {"S": value}
    if isinstance(value, int):
        return {"N": str(value)}
    if isinstance(value, float):
        if not isfinite(value):
            raise TypeError("non-finite numbers cannot be persisted")
        return {"N": repr(value)}
    if isinstance(value, list):
        return {"L": [to_dynamo_attribute(item) for item in value]}
    if isinstance(value, Mapping):
        if not all(isinstance(key, str) for key in value):
            raise TypeError("DynamoDB map keys must be strings")
        return {
            "M": {
                key: to_dynamo_attribute(item)
                for key, item in sorted(value.items())
            }
        }
    raise TypeError(f"unsupported durable value type: {type(value).__name__}")


def from_dynamo_attribute(attribute: object) -> object:
    """Decode one low-level DynamoDB attribute without lossy coercion."""

    if not isinstance(attribute, Mapping) or len(attribute) != 1:
        raise StorageDependencyError("stored DynamoDB attribute is malformed")
    kind, value = next(iter(attribute.items()))
    if kind == "NULL" and value is True:
        return None
    if kind == "BOOL" and isinstance(value, bool):
        return value
    if kind == "S" and isinstance(value, str):
        return value
    if kind == "N" and isinstance(value, str):
        try:
            if any(marker in value for marker in (".", "e", "E")):
                number = float(value)
                if not isfinite(number):
                    raise ValueError
                return number
            return int(value)
        except ValueError as error:
            raise StorageDependencyError("stored numeric attribute is malformed") from error
    if kind == "L" and isinstance(value, list):
        return [from_dynamo_attribute(item) for item in value]
    if kind == "M" and isinstance(value, Mapping):
        if not all(isinstance(key, str) for key in value):
            raise StorageDependencyError("stored map contains a non-string key")
        return {key: from_dynamo_attribute(item) for key, item in value.items()}
    raise StorageDependencyError("stored DynamoDB attribute uses an unsupported shape")


def serialize_record(record: BaseModel) -> DynamoAttribute:
    """Serialize one strict Pydantic contract into a DynamoDB map attribute."""

    if not isinstance(record, BaseModel):
        raise TypeError("record must be a Pydantic model")
    return to_dynamo_attribute(record.model_dump(mode="json"))


def deserialize_record[RecordType: BaseModel](
    attribute: object,
    model_type: type[RecordType],
) -> RecordType:
    """Reconstruct the requested typed contract or fail as a dependency error."""

    payload = from_dynamo_attribute(attribute)
    if not isinstance(payload, Mapping):
        raise StorageDependencyError("stored record payload is not a map")
    try:
        return model_type.model_validate(payload)
    except ValidationError as error:
        raise StorageDependencyError("stored record violates the typed NZ contract") from error
