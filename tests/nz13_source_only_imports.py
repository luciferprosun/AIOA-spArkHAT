"""Source-only imports for a bound test checkout; cached bytecode is never authority."""
import sys
from importlib import invalidate_caches
from importlib.abc import MetaPathFinder
from importlib.machinery import PathFinder, SourceFileLoader
from pathlib import Path


class _SourceOnlyLoader(SourceFileLoader):
    def get_code(self, fullname):
        return self.source_to_code(self.get_data(self.path), self.path)


class _CheckoutSourceFinder(MetaPathFinder):
    def __init__(self, root):
        self.root = Path(root).absolute()

    def find_spec(self, fullname, path=None, target=None):
        spec = PathFinder.find_spec(fullname, path, target)
        if spec is None or spec.origin is None:
            return None
        origin = Path(spec.origin)
        if not origin.is_absolute() or not origin.is_relative_to(self.root):
            return None
        if type(spec.loader) is not SourceFileLoader or origin.suffix != '.py':
            raise ImportError('CHECKOUT_SOURCE_FILE_REQUIRED')
        spec.loader = _SourceOnlyLoader(fullname, spec.origin)
        return spec


def install(root):
    sys.dont_write_bytecode = True
    finder = _CheckoutSourceFinder(root)
    position = next((index for index, existing in enumerate(sys.meta_path) if existing is PathFinder),
                    len(sys.meta_path))
    sys.meta_path.insert(position, finder)
    invalidate_caches()
    return finder
