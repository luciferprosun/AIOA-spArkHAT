"""Installable facade for the existing AOIA-Core runtime.

The legacy runtime uses sibling absolute imports. Bootstrap only THIS installed
package directory; never search for or import another checkout. This preserves
the existing CLI, provider manager, runtime, and test contracts during the port.
"""
from pathlib import Path
import sys

_runtime_directory = str(Path(__file__).resolve().parent)
if _runtime_directory not in sys.path:
    sys.path.insert(0, _runtime_directory)
