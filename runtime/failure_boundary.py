"""Shared value-free callback boundary; no authority, I/O or optional imports.

Relocated from the existing Core repair boundary without widening its catch.
Repair keeps compatibility imports of these same objects.
"""
import re
from contextlib import contextmanager


class RepairBoundaryError(RuntimeError):
    """A host callback failed; only the bounded public code crosses the port."""


@contextmanager
def failure_boundary(code):
    """Preserve typed denials and process signals; wrap foreign callback errors."""
    if type(code) is not str or re.fullmatch(r'[A-Z0-9_]{1,96}', code) is None:
        raise ValueError('REPAIR_BOUNDARY_CODE')
    try:
        yield
    except ValueError:
        raise
    except Exception as error:
        raise RepairBoundaryError(code) from error
