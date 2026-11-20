"""Shared value-free callback boundary; no authority, I/O or optional imports.

Explicit host callback denials can retain their original type. Process signals
always propagate. The default behavior remains the existing repair contract.
"""
import re
from contextlib import contextmanager


class RepairBoundaryError(RuntimeError):
    """A host callback failed; only the bounded public code crosses the port."""


def boundary_cause(error):
    """Keep an existing UI adapter's local error identity and error policy.

    This returns one local exception object, never a serialized public value or
    authority. Unknown callbacks still cross the port using a fixed code.
    """
    if isinstance(error, RepairBoundaryError) and isinstance(error.__cause__, Exception):
        return error.__cause__
    return error


@contextmanager
def failure_boundary(code, *, preserve=()):
    """Preserve typed denials and process signals; wrap foreign callback errors."""
    if type(code) is not str or re.fullmatch(r'[A-Z0-9_]{1,96}', code) is None:
        raise ValueError('REPAIR_BOUNDARY_CODE')
    if (type(preserve) is not tuple or len(preserve) > 8
            or any(not isinstance(kind, type) or not issubclass(kind, Exception)
                   or kind is Exception for kind in preserve)):
        raise ValueError('FAILURE_BOUNDARY_PRESERVE')
    try:
        yield
    except (ValueError, *preserve):
        raise
    except Exception as error:
        raise RepairBoundaryError(code) from error
