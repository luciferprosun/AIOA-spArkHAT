"""Run a trusted acceptance script from this exact checkout, never an old install."""

import importlib
import runpy
import sys
from pathlib import Path


def main(argv):
    root = Path(__file__).resolve().parents[1]
    script = (root / argv[0]).resolve(strict=True)
    if not script.is_relative_to(root / "tests") or script == Path(__file__).resolve():
        raise ValueError("ACCEPTANCE_SCRIPT_SCOPE")
    sys.path[:0] = [str(root), str(root / "tests")]
    runtime = importlib.import_module("runtime")
    if Path(runtime.__file__).resolve() != root / "runtime/__init__.py":
        raise ValueError("ACCEPTANCE_RUNTIME_SOURCE_MISMATCH")
    sys.argv = [str(script), *argv[1:]]
    try:
        runpy.run_path(str(script), run_name="__main__")
    finally:
        prefixes = ("runtime.", "providers.", "nonzero_cloudops.", "mcp_bridge.")
        for name, module in tuple(sys.modules.items()):
            if name == "runtime" or name.startswith(prefixes):
                origin = getattr(module, "__file__", None)
                if origin and not Path(origin).resolve().is_relative_to(root):
                    raise ValueError("ACCEPTANCE_IMPORTED_FOREIGN_SOURCE")


if __name__ == "__main__":
    main(sys.argv[1:])
