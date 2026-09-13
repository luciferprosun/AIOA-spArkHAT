"""Domain wire hash, not a second global provenance store.

Derived from persistence/models.py at the immutable source SHA; MIT license
in ../LICENSE-NONZERO.txt. ASCII canonical encoding is a binding contract.
"""

import hashlib
import json

from .validation import ContractValidationError


def compute_evidence_digest(payload: object) -> str:
    try:
        value = json.dumps(
            payload,
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise ContractValidationError(
            "evidence payload must be canonical JSON data"
        ) from error
    return hashlib.sha256(value).hexdigest()
