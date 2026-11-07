"""Pinned repository recipe for the existing Linux sandbox, never host execution.

Materialization runs without importing candidate code. Observation runs are
untrusted data producers: expected answers and test verdicts exist only in Core.
"""

import ast
import hashlib
import json
import math
import operator
import os
import stat
import sys
import unicodedata
import warnings
from contextlib import suppress
from pathlib import Path, PurePosixPath


def require(condition, code):
    if not condition:
        raise ValueError(code)


def canonical(value):
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode()


def digest(data):
    return hashlib.sha256(data).hexdigest()


def path_parts(value):
    require(
        type(value) is str and value == unicodedata.normalize("NFC", value),
        "REPOSITORY_PATH",
    )
    path = PurePosixPath(value)
    require(
        not path.is_absolute()
        and path.as_posix() == value
        and len(path.parts) <= 32
        and all(part not in ("", ".", "..", ".git") for part in path.parts),
        "REPOSITORY_PATH",
    )
    return path.parts


def parent(root, parts, *, create=False):
    current = os.dup(root)
    try:
        for part in parts[:-1]:
            if create:
                with suppress(FileExistsError):
                    os.mkdir(part, 0o700, dir_fd=current)
            child = os.open(
                part,
                os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                dir_fd=current,
            )
            os.close(current)
            current = child
        return current
    except OSError:
        os.close(current)
        raise


def read_regular(directory, name):
    fd = os.open(
        name,
        os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC,
        dir_fd=directory,
    )
    try:
        before = os.fstat(fd)
        require(
            stat.S_ISREG(before.st_mode)
            and before.st_nlink == 1
            and before.st_size <= 1048576,
            "REPOSITORY_FILE_TYPE",
        )
        data = bytearray()
        while len(data) <= before.st_size:
            chunk = os.read(fd, min(65536, before.st_size + 1 - len(data)))
            if not chunk:
                break
            data.extend(chunk)
        after = os.fstat(fd)
        named = os.stat(name, dir_fd=directory, follow_symlinks=False)

        def identity(info):
            return (
                info.st_dev,
                info.st_ino,
                info.st_mode,
                info.st_uid,
                info.st_gid,
                info.st_nlink,
                info.st_size,
                info.st_mtime_ns,
                info.st_ctime_ns,
            )

        require(
            len(data) == before.st_size
            and identity(before) == identity(after)
            and (named.st_dev, named.st_ino) == (before.st_dev, before.st_ino),
            "REPOSITORY_FILE_CHANGED",
        )
        return bytes(data), stat.S_IMODE(before.st_mode)
    finally:
        os.close(fd)


def write_new(directory, name, data, mode):
    fd = os.open(
        name,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
        0o600,
        dir_fd=directory,
    )
    try:
        view = memoryview(data)
        while view:
            written = os.write(fd, view)
            require(written > 0, "REPOSITORY_SHORT_WRITE")
            view = view[written:]
        os.fchmod(fd, mode)
        os.fsync(fd)
    finally:
        os.close(fd)


def inspect_tree(root):
    files = []
    folded = set()

    def walk(directory, prefix):
        for name in sorted(os.listdir(directory)):
            path = prefix + name
            path_parts(path)
            metadata = os.stat(name, dir_fd=directory, follow_symlinks=False)
            if stat.S_ISDIR(metadata.st_mode):
                child = os.open(
                    name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory
                )
                try:
                    walk(child, path + "/")
                finally:
                    os.close(child)
            else:
                require(
                    path.casefold() not in folded and len(files) < 256,
                    "REPOSITORY_TREE_BOUND",
                )
                folded.add(path.casefold())
                data, mode = read_regular(directory, name)
                require(
                    mode in (0o600, 0o644) and b"\0" not in data, "REPOSITORY_FILE_MODE"
                )
                files.append({"path": path, "mode": mode, "text": data.decode("utf-8")})

    walk(root, "")
    require(
        sum(len(f["text"].encode()) for f in files) <= 1048576, "REPOSITORY_TREE_BOUND"
    )
    return {
        "schema": "aioa.validation-workspace.v1",
        "files": sorted(files, key=lambda f: f["path"]),
    }


def tree_digest(archive):
    return digest(
        canonical(
            [
                [
                    f["path"],
                    digest(f["text"].encode()),
                    len(f["text"].encode()),
                    f["mode"],
                ]
                for f in archive["files"]
            ]
        )
    )


def materialize():
    seed = json.loads(Path("/inputs/base.json").read_bytes())
    changes = json.loads(Path("/inputs/changes.json").read_bytes())
    receipt = json.loads(Path("/inputs/materialization.json").read_bytes())
    require(type(changes) is list and 1 <= len(changes) <= 3, "REPOSITORY_CHANGE_BOUND")
    root = Path("/work/project")
    root.mkdir(mode=0o700)
    directory = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for item in seed["files"]:
            parts = path_parts(item["path"])
            fd = parent(directory, parts, create=True)
            try:
                require(item["mode"] in (0o600, 0o644), "REPOSITORY_FILE_MODE")
                write_new(fd, parts[-1], item["text"].encode(), item["mode"])
            finally:
                os.close(fd)
        before = inspect_tree(directory)
        require(
            tree_digest(before) == receipt["base_tree_sha256"], "REPOSITORY_BASE_DRIFT"
        )
        for index, change in enumerate(changes):
            parts = path_parts(change["path"])
            fd = parent(directory, parts, create=change["operation"] == "ADD")
            try:
                if change["operation"] != "ADD":
                    current, mode = read_regular(fd, parts[-1])
                    require(
                        digest(current) == change["before_sha256"],
                        "REPOSITORY_PREIMAGE",
                    )
                else:
                    require(change["before_sha256"] is None, "REPOSITORY_PREIMAGE")
                    mode = 0o644
                if change["operation"] == "DELETE":
                    require(change["text"] is None, "REPOSITORY_DELETE")
                    os.unlink(parts[-1], dir_fd=fd)
                else:
                    data = change["text"].encode()
                    require(
                        digest(data) == change["after_sha256"], "REPOSITORY_POSTIMAGE"
                    )
                    if change["operation"] == "ADD":
                        write_new(fd, parts[-1], data, mode)
                    else:
                        require(change["operation"] == "MODIFY", "REPOSITORY_OPERATION")
                        name = ".aioa-approved-" + str(index)
                        write_new(fd, name, data, mode)
                        last, _ = read_regular(fd, parts[-1])
                        require(last == current, "REPOSITORY_PREIMAGE_CHANGED")
                        os.rename(name, parts[-1], src_dir_fd=fd, dst_dir_fd=fd)
                        os.fsync(fd)
            finally:
                os.close(fd)
        after = inspect_tree(directory)
        require(
            tree_digest(after) == receipt["final_tree_sha256"], "REPOSITORY_POSTIMAGE"
        )
        Path("/artifacts/workspace.json").write_bytes(canonical(after))
        Path("/artifacts/materialization.json").write_bytes(canonical(receipt))
    finally:
        os.close(directory)


class ProgramPolicyError(ValueError):
    """A stable, value-free denial in the bounded AST/JSON execution profile."""


def policy(condition, code="ProfileUnsupported"):
    if not condition:
        raise ProgramPolicyError(code)


def data_value(value, depth=0, ancestors=(), budget=None):
    """Only bounded JSON data can cross a candidate expression boundary."""
    if budget is None:
        budget = [0, 0]
    budget[0] += 1
    policy(budget[0] <= 4096, "ProfileValueBound")
    policy(depth <= 16, "ProfileValueBound")
    if value is None or type(value) is bool:
        return value
    if type(value) is int:
        policy(value.bit_length() <= 128, "ProfileValueBound")
        return value
    if type(value) is float:
        policy(math.isfinite(value), "ProfileValueBound")
        return value
    if type(value) is str:
        size = len(value.encode("utf-8"))
        budget[1] += size
        policy(size <= 8192 and budget[1] <= 65536, "ProfileValueBound")
        return value
    policy(type(value) in (list, tuple, dict), "ProfileValueType")
    policy(len(value) <= 1024 and id(value) not in ancestors, "ProfileValueBound")
    parents = (*ancestors, id(value))
    if type(value) is dict:
        for key, item in value.items():
            policy(type(key) is str, "ProfileValueType")
            data_value(key, depth + 1, parents, budget)
            data_value(item, depth + 1, parents, budget)
    else:
        for item in value:
            data_value(item, depth + 1, parents, budget)
    return value


class _Reference:
    """An interpreter-owned token, never a Python object supplied by the source."""

    __slots__ = ("kind", "module", "name", "receiver")

    def __init__(self, kind, name, module=None, receiver=None):
        self.kind, self.name, self.module, self.receiver = kind, name, module, receiver


class _Returned(Exception):
    def __init__(self, value):
        self.value = value


class _BreakLoop(Exception):
    pass


class _ContinueLoop(Exception):
    pass


_UNBOUND = object()


_BINARY = {
    ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
    ast.Div: operator.truediv, ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod, ast.Pow: operator.pow,
}
_INPLACE = {
    ast.Add: operator.iadd, ast.Sub: operator.isub, ast.Mult: operator.imul,
    ast.Div: operator.itruediv, ast.FloorDiv: operator.ifloordiv,
    ast.Mod: operator.imod, ast.Pow: operator.ipow,
}
_COMPARE = {
    ast.Eq: operator.eq, ast.NotEq: operator.ne, ast.Lt: operator.lt,
    ast.LtE: operator.le, ast.Gt: operator.gt, ast.GtE: operator.ge,
    ast.Is: operator.is_, ast.IsNot: operator.is_not,
    ast.In: lambda left, right: left in right,
    ast.NotIn: lambda left, right: left not in right,
}
_METHODS = {
    str: {
        "lower": str.lower, "upper": str.upper, "strip": str.strip,
        "lstrip": str.lstrip, "rstrip": str.rstrip, "split": str.split,
        "rsplit": str.rsplit, "join": str.join, "replace": str.replace,
        "title": str.title, "capitalize": str.capitalize, "casefold": str.casefold,
        "startswith": str.startswith, "endswith": str.endswith,
        "count": str.count, "find": str.find, "index": str.index,
        "isalnum": str.isalnum, "isalpha": str.isalpha,
        "isdigit": str.isdigit, "isspace": str.isspace,
    },
    list: {
        "append": list.append, "extend": list.extend, "insert": list.insert,
        "pop": list.pop, "remove": list.remove, "clear": list.clear,
        "reverse": list.reverse, "sort": list.sort, "count": list.count,
        "index": list.index, "copy": list.copy,
    },
    dict: {
        "get": dict.get, "keys": dict.keys, "values": dict.values,
        "items": dict.items, "pop": dict.pop, "setdefault": dict.setdefault,
        "update": dict.update, "copy": dict.copy, "clear": dict.clear,
    },
    tuple: {"count": tuple.count, "index": tuple.index},
}
_BUILTINS = {
    "abs": abs, "bool": bool, "dict": dict, "float": float, "int": int,
    "len": len, "list": list, "max": max, "min": min, "round": round,
    "str": str, "sum": sum, "tuple": tuple, "sorted": sorted,
}
_SAFE_MODULES = {
    "math": {
        "sqrt": math.sqrt, "floor": math.floor, "ceil": math.ceil,
        "sin": math.sin, "cos": math.cos, "tan": math.tan,
        "log": math.log, "log10": math.log10, "exp": math.exp,
        "isfinite": math.isfinite, "pi": math.pi, "e": math.e,
    },
    "json": {"loads": json.loads, "dumps": json.dumps},
}
_SPECIAL_BUILTINS = {"range", "enumerate", "zip", "reversed"}
_FORBIDDEN_NAMES = {
    "eval", "exec", "compile", "__import__", "getattr", "setattr", "delattr",
    "globals", "locals", "vars", "dir", "open", "input", "print", "exit",
    "quit", "breakpoint", "help", "memoryview", "type", "object", "super",
}
_ALLOWED_NODES = (
    ast.FunctionDef, ast.arguments, ast.arg, ast.Return, ast.Assign,
    ast.AugAssign, ast.If, ast.For, ast.While, ast.Break, ast.Continue, ast.Pass,
    ast.Expr, ast.Constant, ast.Name, ast.Load, ast.Store, ast.List, ast.Tuple,
    ast.Dict, ast.Subscript, ast.Slice, ast.Attribute, ast.Call, ast.keyword,
    ast.BinOp, ast.UnaryOp, ast.BoolOp, ast.Compare, ast.IfExp,
    ast.ListComp, ast.DictComp, ast.comprehension, ast.JoinedStr, ast.FormattedValue,
    ast.And, ast.Or, ast.Not, ast.UAdd, ast.USub, *_BINARY, *_COMPARE,
)


class PythonJsonProgram:
    """Closed AST data interpreter; used for execution only inside the broker.

    Construction validates source and call shapes without executing function
    bodies. Compilation is a syntax check only; no candidate bytecode is ever
    executed or exposed. There is no eval/exec/import of candidate Python,
    Python callback, filesystem API or reporter-object reference in this language.
    """

    def __init__(self, archive, roots, calls):
        policy(type(archive) is dict and type(archive.get("files")) is list)
        policy(type(roots) is list and 1 <= len(roots) <= 4)
        self.files, self.roots = {}, roots
        self.modules, self.loading, self.steps, self.depth = {}, set(), 0, 0
        self.source_bytes = 0
        for root in roots:
            policy(type(root) is str)
            if root:
                path_parts(root)
        for item in archive["files"]:
            policy(type(item) is dict and type(item.get("text")) is str)
            path = item.get("path")
            path_parts(path)
            policy(path not in self.files, "ProfileSourceAmbiguous")
            self.files[path] = item["text"]
        policy(not any(name.split(".")[0] in sys.stdlib_module_names
                       for name in self.module_names()), "ProfileStandardLibraryShadow")
        policy(type(calls) is list and 1 <= len(calls) <= 16)
        for call in calls:
            policy(type(call) is dict and set(call) == {
                "case_id", "module", "function", "arguments",
            })
            policy(type(call["case_id"]) is str)
            policy(type(call["function"]) is str and call["module"] not in _SAFE_MODULES)
            policy(type(call["arguments"]) is list and len(call["arguments"]) <= 16)
            data_value(call["arguments"])
            self.load(call["module"])
            ref = self.modules[call["module"]].get(call["function"])
            policy(type(ref) is _Reference and ref.kind == "function")

    def tick(self):
        self.steps += 1
        policy(self.steps <= 200000, "ProfileStepBound")

    def locate(self, name):
        policy(type(name) is str and name and all(
            part.isascii() and part.isidentifier() and not part.startswith("_")
            for part in name.split(".")
        ))
        relative = name.replace(".", "/")
        found = []
        for root in self.roots:
            prefix = root + "/" if root else ""
            for path in (prefix + relative + "/__init__.py", prefix + relative + ".py"):
                if path in self.files:
                    found.append(path)
        policy(len(found) == 1, "ProfileSourceAmbiguous")
        return found[0]

    def load(self, name):
        if name in _SAFE_MODULES:
            return
        policy(name not in self.loading, "ProfileImportCycle")
        if name in self.modules:
            return
        path = self.locate(name)
        parent = name.rpartition(".")[0]
        if parent:
            self.load(parent)
        self.loading.add(name)
        text = self.files[path]
        self.source_bytes += len(text.encode("utf-8"))
        policy(self.source_bytes <= 262144, "ProfileSourceBound")
        try:
            # Compiler diagnostics must not print candidate source into logs.
            # Treat the version-dependent warning categories as stable denials.
            with warnings.catch_warnings():
                warnings.simplefilter("error", SyntaxWarning)
                warnings.simplefilter("error", DeprecationWarning)
                tree = ast.parse(text, filename="<candidate-data>")
                # Validate syntax only; discard bytecode without execution.
                compile(tree, "<candidate-data>", "exec", dont_inherit=True)
        except (SyntaxError, ValueError, RecursionError, SyntaxWarning, DeprecationWarning):
            raise ProgramPolicyError("ProfileSourceSyntax") from None
        nodes = list(ast.walk(tree))
        policy(len(nodes) <= 32768, "ProfileSourceBound")
        namespace = {}
        for node in tree.body:
            if isinstance(node, ast.FunctionDef):
                self.check_function(node)
                policy(node.name not in namespace, "ProfileSourceAmbiguous")
                namespace[node.name] = _Reference("function", node.name, name)
            elif isinstance(node, ast.Assign):
                targets = node.targets
                policy(node.value is not None and all(type(x) is ast.Name for x in targets))
                value = self.literal(node.value)
                for target in targets:
                    policy(not target.id.startswith("__"))
                    policy(target.id not in namespace, "ProfileSourceAmbiguous")
                    namespace[target.id] = value
            elif isinstance(node, ast.Expr):
                policy(type(node.value) is ast.Constant and type(node.value.value) is str)
            else:
                policy(isinstance(node, (ast.Import, ast.ImportFrom)))
        self.modules[name] = namespace
        namespace["@functions"] = {
            node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)
        }
        for node in tree.body:
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                self.import_names(node, namespace)
        self.loading.remove(name)
        if parent:
            key = name.rsplit(".", 1)[1]
            policy(key not in self.modules[parent], "ProfileSourceAmbiguous")
            self.modules[parent][key] = _Reference("module", name)

    def import_names(self, node, namespace):
        if isinstance(node, ast.Import):
            for alias in node.names:
                policy(alias.name in _SAFE_MODULES or alias.name in self.module_names())
                self.load(alias.name)
                key = alias.asname or alias.name.split(".")[0]
                target = alias.name if alias.asname else key
                policy(key not in namespace, "ProfileSourceAmbiguous")
                namespace[key] = _Reference("module", target)
            return
        policy(node.level == 0 and node.module is not None)
        policy(node.module in _SAFE_MODULES or node.module in self.module_names())
        self.load(node.module)
        for alias in node.names:
            policy(alias.name != "*")
            key = alias.asname or alias.name
            policy(key not in namespace, "ProfileSourceAmbiguous")
            namespace[key] = self.module_attribute(node.module, alias.name)

    def module_names(self):
        names = set()
        for path in self.files:
            for root in self.roots:
                prefix = root + "/" if root else ""
                if path.startswith(prefix) and path.endswith(".py"):
                    relative = path[len(prefix):-3]
                    relative = relative.removesuffix("/__init__")
                    names.add(relative.replace("/", "."))
        return names

    @staticmethod
    def literal(node):
        try:
            return data_value(ast.literal_eval(node))
        except (ValueError, TypeError, RecursionError):
            raise ProgramPolicyError("ProfileLiteral") from None

    def check_function(self, node):
        policy(not node.decorator_list and not getattr(node, "type_params", ()))
        policy(not node.name.startswith("__") and node.returns is None)
        args = node.args
        policy(args.vararg is None and args.kwarg is None)
        parameters = args.posonlyargs + args.args + args.kwonlyargs
        policy(len(parameters) <= 16)
        policy(all(arg.annotation is None and not arg.arg.startswith("__")
                   for arg in parameters))
        for default in [*args.defaults, *(x for x in args.kw_defaults if x is not None)]:
            value = self.literal(default)
            pending = [value]
            while pending:
                item = pending.pop()
                policy(type(item) not in (list, dict))
                if type(item) is tuple:
                    pending.extend(item)
        for child in ast.walk(node):
            policy(isinstance(child, _ALLOWED_NODES))
            if isinstance(child, ast.FunctionDef):
                policy(child is node)
            if isinstance(child, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
                targets = child.targets if isinstance(child, ast.Assign) else [child.target]
                policy(all(isinstance(x, (ast.Name, ast.Tuple, ast.List, ast.Subscript)) for x in targets))
                policy(not any(isinstance(x, ast.Attribute) and isinstance(x.ctx, ast.Store)
                               for x in ast.walk(child)))
            if isinstance(child, ast.Attribute):
                policy(not child.attr.startswith("_"))
            if isinstance(child, ast.Name):
                policy(child.id not in _FORBIDDEN_NAMES and not child.id.startswith("__"))
            if isinstance(child, ast.Compare):
                operands = [child.left, *child.comparators]
                for index, op in enumerate(child.ops):
                    if isinstance(op, (ast.Is, ast.IsNot)):
                        policy(any(type(item) is ast.Constant
                                   and (item.value is None or type(item.value) is bool)
                                   for item in operands[index:index + 2]))
            if isinstance(child, ast.keyword):
                policy(child.arg is not None)
            if isinstance(child, ast.Call):
                policy(len(child.args) + len(child.keywords) <= 16)
            if isinstance(child, ast.Constant):
                data_value(child.value)
            if isinstance(child, ast.comprehension):
                policy(not child.is_async)
            if isinstance(child, ast.FormattedValue):
                policy(child.format_spec is None and child.conversion == -1)

    def module_attribute(self, module, name):
        policy(type(name) is str and not name.startswith("_"))
        if module in _SAFE_MODULES:
            policy(name in _SAFE_MODULES[module])
            value = _SAFE_MODULES[module][name]
            return _Reference("builtin", module + "." + name) if callable(value) else value
        policy(module in self.modules and name in self.modules[module])
        return self.modules[module][name]

    def name(self, key, namespace, local):
        if key in local:
            policy(local[key] is not _UNBOUND, "UnboundLocalError")
            return local[key]
        if key in namespace:
            return namespace[key]
        policy(key in _BUILTINS or key in _SPECIAL_BUILTINS)
        return _Reference("builtin", key)

    def evaluate(self, node, namespace, local):
        self.tick()
        dispatch = {
            ast.Constant: self.expr_constant, ast.Name: self.expr_name,
            ast.List: self.expr_sequence, ast.Tuple: self.expr_sequence,
            ast.Dict: self.expr_dict, ast.Subscript: self.expr_subscript,
            ast.Attribute: self.expr_attribute, ast.Call: self.expr_call,
            ast.BinOp: self.expr_binary, ast.UnaryOp: self.expr_unary,
            ast.BoolOp: self.expr_bool, ast.Compare: self.expr_compare,
            ast.IfExp: self.expr_if, ast.ListComp: self.expr_comprehension,
            ast.DictComp: self.expr_comprehension, ast.JoinedStr: self.expr_joined,
        }
        policy(type(node) in dispatch)
        return dispatch[type(node)](node, namespace, local)

    def expr_constant(self, node, _namespace, _local):
        return data_value(node.value)

    def expr_name(self, node, namespace, local):
        return self.name(node.id, namespace, local)

    def expr_sequence(self, node, namespace, local):
        value = [self.evaluate(x, namespace, local) for x in node.elts]
        return data_value(tuple(value) if type(node) is ast.Tuple else value)

    def expr_dict(self, node, namespace, local):
        policy(all(key is not None for key in node.keys))
        value = {self.evaluate(k, namespace, local): self.evaluate(v, namespace, local)
                 for k, v in zip(node.keys, node.values, strict=True)}
        return data_value(value)

    def subscript(self, node, namespace, local):
        if type(node) is ast.Slice:
            return slice(*(None if x is None else self.evaluate(x, namespace, local)
                           for x in (node.lower, node.upper, node.step)))
        return self.evaluate(node, namespace, local)

    def expr_subscript(self, node, namespace, local):
        value = data_value(self.evaluate(node.value, namespace, local))
        policy(type(value) in (str, list, tuple, dict))
        return data_value(value[self.subscript(node.slice, namespace, local)])

    def expr_attribute(self, node, namespace, local):
        value = self.evaluate(node.value, namespace, local)
        if type(value) is _Reference and value.kind == "module":
            return self.module_attribute(value.name, node.attr)
        data_value(value)
        policy(node.attr in _METHODS.get(type(value), {}))
        return _Reference("method", node.attr, receiver=value)

    def expr_call(self, node, namespace, local):
        ref = self.evaluate(node.func, namespace, local)
        policy(type(ref) is _Reference and ref.kind in ("function", "method", "builtin"))
        args = [self.argument(self.evaluate(x, namespace, local)) for x in node.args]
        kwargs = {}
        for item in node.keywords:
            policy(item.arg is not None and item.arg not in kwargs)
            kwargs[item.arg] = data_value(self.evaluate(item.value, namespace, local))
        if ref.kind == "function":
            for value in args:
                data_value(value)
            return self.call(ref.module, ref.name, args, kwargs)
        if ref.kind == "method":
            for value in args:
                data_value(value)
            return self.method(ref, args, kwargs)
        return self.builtin(ref.name, args, kwargs)

    @staticmethod
    def argument(value):
        if type(value) is _Reference:
            policy(value.kind in ("iterable", "iterator", "view"))
            return value
        return data_value(value)

    def expr_binary(self, node, namespace, local):
        left = data_value(self.evaluate(node.left, namespace, local))
        right = data_value(self.evaluate(node.right, namespace, local))
        return self.binary(type(node.op), left, right)

    @staticmethod
    def binary(kind, left, right, *, inplace=False):
        policy(kind in _BINARY)
        if kind is ast.Add and type(left) in (str, list, tuple) and type(right) is type(left):
            limit = 8192 if type(left) is str else 1024
            policy(len(left) + len(right) <= limit, "ProfileValueBound")
        if kind is ast.Mult:
            sequence, count = (left, right) if type(left) in (str, list, tuple) else (right, left)
            if type(sequence) in (str, list, tuple) and type(count) is int:
                policy(len(sequence) * max(0, count) <= 1024, "ProfileValueBound")
        if kind is ast.Pow:
            policy(type(right) is int and 0 <= right <= 64, "ProfileValueBound")
            if type(left) is int:
                policy(left.bit_length() * right <= 256, "ProfileValueBound")
        if kind is ast.Mod:
            policy(type(left) in (int, float) and type(right) in (int, float))
        return data_value((_INPLACE if inplace else _BINARY)[kind](left, right))

    def expr_unary(self, node, namespace, local):
        value = data_value(self.evaluate(node.operand, namespace, local))
        functions = {ast.Not: operator.not_, ast.UAdd: operator.pos, ast.USub: operator.neg}
        policy(type(node.op) in functions)
        return data_value(functions[type(node.op)](value))

    def expr_bool(self, node, namespace, local):
        value = None
        for expr in node.values:
            value = data_value(self.evaluate(expr, namespace, local))
            if (type(node.op) is ast.And and not value) or (type(node.op) is ast.Or and value):
                break
        return value

    def expr_compare(self, node, namespace, local):
        left = data_value(self.evaluate(node.left, namespace, local))
        for op, expr in zip(node.ops, node.comparators, strict=True):
            right = data_value(self.evaluate(expr, namespace, local))
            policy(type(op) in _COMPARE)
            if not _COMPARE[type(op)](left, right):
                return False
            left = right
        return True

    def expr_if(self, node, namespace, local):
        branch = node.body if data_value(self.evaluate(node.test, namespace, local)) else node.orelse
        return self.evaluate(branch, namespace, local)

    def expr_comprehension(self, node, namespace, local):
        policy(len(node.generators) <= 2)
        result = {} if type(node) is ast.DictComp else []
        outer_iterable = self.iterable(self.evaluate(node.generators[0].iter, namespace, local))
        inner = dict(local)
        for gen in node.generators:
            for target in ast.walk(gen.target):
                if type(target) is ast.Name:
                    inner[target.id] = _UNBOUND

        def visit(index):
            self.tick()
            if index == len(node.generators):
                policy(len(result) < 1024, "ProfileValueBound")
                if type(result) is dict:
                    key = self.evaluate(node.key, namespace, inner)
                    policy(type(key) is str)
                    result[key] = self.evaluate(node.value, namespace, inner)
                else:
                    result.append(self.evaluate(node.elt, namespace, inner))
                return
            gen = node.generators[index]
            values = outer_iterable if index == 0 else self.iterable(self.evaluate(gen.iter, namespace, inner))
            for item in values:
                self.assign(gen.target, item, namespace, inner)
                if all(data_value(self.evaluate(x, namespace, inner)) for x in gen.ifs):
                    visit(index + 1)

        visit(0)
        return data_value(result)

    def expr_joined(self, node, namespace, local):
        values = []
        for part in node.values:
            value = self.evaluate(part.value, namespace, local) if type(part) is ast.FormattedValue else part.value
            values.append(str(data_value(value)))
            policy(sum(len(x) for x in values) <= 8192, "ProfileValueBound")
        return data_value("".join(values))

    def iterable(self, value):
        if type(value) is _Reference:
            policy(value.kind in ("iterable", "iterator", "view"))
            raw = iter(value.receiver)
        else:
            data_value(value)
            policy(type(value) in (list, tuple, dict, str) and len(value) <= 1024, "ProfileIterationBound")
            raw = iter(value)
        # Create the actual data iterator now: a snapshot would conceal Python's
        # mutation-during-iteration errors and list iterator alias semantics.
        def bounded():
            count = 0
            while True:
                self.tick()
                try:
                    item = next(raw)
                except StopIteration:
                    return
                except RuntimeError:
                    raise ProgramPolicyError("RuntimeError") from None
                count += 1
                policy(count <= 1024, "ProfileIterationBound")
                yield data_value(item)

        return bounded()

    def assign(self, target, value, namespace, local):
        self.tick()
        if type(target) is ast.Name:
            local[target.id] = value
            return
        data_value(value)
        if type(target) in (ast.Tuple, ast.List):
            policy(type(value) in (tuple, list) and len(value) == len(target.elts))
            for item, part in zip(target.elts, value, strict=True):
                self.assign(item, part, namespace, local)
            return
        policy(type(target) is ast.Subscript)
        container = data_value(self.evaluate(target.value, namespace, local))
        policy(type(container) in (list, dict))
        key = self.subscript(target.slice, namespace, local)
        if type(container) is dict:
            policy(type(key) is str and (key in container or len(container) < 1024))
        container[key] = value
        data_value(container)

    def statements(self, nodes, namespace, local):
        for node in nodes:
            self.tick()
            if type(node) is ast.Return:
                raise _Returned(None if node.value is None else self.evaluate(node.value, namespace, local))
            if type(node) in (ast.Assign, ast.AnnAssign):
                policy(node.value is not None)
                value = self.evaluate(node.value, namespace, local)
                for target in node.targets if type(node) is ast.Assign else [node.target]:
                    self.assign(target, value, namespace, local)
            elif type(node) is ast.AugAssign:
                self.augment(node, namespace, local)
            elif type(node) is ast.Expr:
                self.evaluate(node.value, namespace, local)
            elif type(node) is ast.If:
                branch = node.body if data_value(self.evaluate(node.test, namespace, local)) else node.orelse
                self.statements(branch, namespace, local)
            elif type(node) in (ast.For, ast.While):
                self.loop(node, namespace, local)
            elif type(node) is ast.Break:
                raise _BreakLoop()
            elif type(node) is ast.Continue:
                raise _ContinueLoop()
            else:
                policy(type(node) is ast.Pass)

    def augment(self, node, namespace, local):
        target = node.target
        if type(target) is ast.Name:
            left = data_value(self.name(target.id, namespace, local))
            right = data_value(self.evaluate(node.value, namespace, local))
            local[target.id] = self.binary(type(node.op), left, right, inplace=True)
            return
        policy(type(target) is ast.Subscript)
        container = data_value(self.evaluate(target.value, namespace, local))
        policy(type(container) in (list, dict))
        key = self.subscript(target.slice, namespace, local)
        left = data_value(container[key])
        right = data_value(self.evaluate(node.value, namespace, local))
        container[key] = self.binary(type(node.op), left, right, inplace=True)
        data_value(container)

    def loop(self, node, namespace, local):
        values = iter(self.iterable(self.evaluate(node.iter, namespace, local))) if type(node) is ast.For else None
        completed = True
        while True:
            self.tick()
            if values is None:
                if not data_value(self.evaluate(node.test, namespace, local)):
                    break
            else:
                try:
                    item = next(values)
                except StopIteration:
                    break
                self.assign(node.target, item, namespace, local)
            try:
                self.statements(node.body, namespace, local)
            except _ContinueLoop:
                continue
            except _BreakLoop:
                completed = False
                break
        if completed:
            self.statements(node.orelse, namespace, local)

    def call(self, module, name, args, kwargs=None):
        self.tick()
        self.depth += 1
        policy(self.depth <= 24, "ProfileCallBound")
        try:
            namespace = self.modules[module]
            node = namespace["@functions"][name]
            positional = node.args.posonlyargs + node.args.args
            policy(len(args) <= len(positional))
            local = {key: _UNBOUND for key in self.local_names(node)}
            local.update(zip((a.arg for a in positional), args, strict=False))
            bound = {a.arg for a in positional[:len(args)]}
            for key, value in (kwargs or {}).items():
                policy(key not in bound and key in {a.arg for a in node.args.args + node.args.kwonlyargs})
                local[key] = value
                bound.add(key)
            for arg, default in zip(positional[-len(node.args.defaults):], node.args.defaults, strict=False):
                if local.get(arg.arg, _UNBOUND) is _UNBOUND:
                    local[arg.arg] = self.literal(default)
            for arg, default in zip(node.args.kwonlyargs, node.args.kw_defaults, strict=True):
                if local.get(arg.arg, _UNBOUND) is _UNBOUND and default is not None:
                    local[arg.arg] = self.literal(default)
            policy(all(local.get(a.arg, _UNBOUND) is not _UNBOUND
                       for a in positional + node.args.kwonlyargs))
            try:
                self.statements(node.body, namespace, local)
            except _Returned as result:
                return data_value(result.value)
            return None
        finally:
            self.depth -= 1

    @staticmethod
    def local_names(function):
        """Python assignments bind the entire function, not just executed lines."""
        pending, names = list(function.body), set()
        while pending:
            node = pending.pop()
            if isinstance(node, (ast.ListComp, ast.DictComp)):
                continue
            if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
                names.add(node.id)
            pending.extend(ast.iter_child_nodes(node))
        return names

    def method(self, ref, args, kwargs):
        value = data_value(ref.receiver)
        if type(value) is str and ref.name == "join" and len(args) == 1:
            items = args[0]
            policy(type(items) in (str, list, tuple, dict))
            if all(type(x) is str for x in items):
                size = sum(len(x.encode("utf-8")) for x in items)
                size += max(0, len(items) - 1) * len(value.encode("utf-8"))
                policy(size <= 8192, "ProfileValueBound")
        if type(value) is str and ref.name == "replace" and len(args) >= 2:
            old, new = args[:2]
            if type(old) is str and type(new) is str:
                count = value.count(old)
                if len(args) == 3 and type(args[2]) is int and args[2] >= 0:
                    count = min(count, args[2])
                size = len(value.encode("utf-8"))
                size += count * (len(new.encode("utf-8")) - len(old.encode("utf-8")))
                policy(size <= 8192, "ProfileValueBound")
        if type(value) in (list, dict) and ref.name in ("append", "extend", "insert", "setdefault", "update"):
            added = len(args[0]) if ref.name in ("extend", "update") and args else 1
            policy(len(value) + added <= 1024, "ProfileValueBound")
        result = _METHODS[type(value)][ref.name](value, *args, **kwargs)
        if type(value) is dict and ref.name in ("keys", "values", "items"):
            return _Reference("view", ref.name, receiver=result)
        data_value(value)
        return data_value(result)

    def builtin(self, name, args, kwargs):
        if "." in name:
            for value in args:
                data_value(value)
            module, attr = name.split(".", 1)
            if name == "json.dumps" and "indent" in kwargs:
                indent = kwargs["indent"]
                policy(indent is None or (type(indent) is int and 0 <= indent <= 8))
            result = _SAFE_MODULES[module][attr](*args, **kwargs)
        elif name in _SPECIAL_BUILTINS:
            policy(not kwargs)
            if name == "range":
                for value in args:
                    data_value(value)
                sequence = range(*args)
                policy(len(sequence) <= 1024, "ProfileIterationBound")
                return _Reference("iterable", name, receiver=sequence)
            if name == "enumerate":
                policy(1 <= len(args) <= 2)
                start = args[1] if len(args) == 2 else 0
                policy(type(start) in (int, bool))
                sequence = enumerate(self.iterable(args[0]), start)
            elif name == "zip":
                sequence = zip(*(self.iterable(value) for value in args), strict=False)
            else:
                policy(len(args) == 1)
                value = args[0]
                if type(value) is _Reference:
                    policy(value.kind in ("iterable", "view"))
                    value = value.receiver
                else:
                    data_value(value)
                sequence = reversed(value)
            return _Reference("iterator", name, receiver=sequence)
        else:
            policy(name in _BUILTINS)
            if name == "len" and len(args) == 1 and type(args[0]) is _Reference:
                policy(args[0].kind in ("iterable", "view") and not kwargs)
                return data_value(len(args[0].receiver))
            for index, value in enumerate(args):
                if type(value) is _Reference:
                    policy(index == 0 and name in ("list", "tuple", "dict", "sum", "sorted", "min", "max"))
                    policy(name not in ("min", "max") or len(args) == 1)
                    args[index] = list(self.iterable(value))
                else:
                    data_value(value)
            result = _BUILTINS[name](*args, **kwargs)
        return data_value(result)


def observe_calls(archive, roots, calls):
    """Evaluate AST data only in the existing broker, with no candidate imports."""
    try:
        program = PythonJsonProgram(archive, roots, calls)
    except (ValueError, TypeError, RecursionError):
        return [{"case_id": call["case_id"], "kind": "raised", "type": "ProfileUnsupported"}
                for call in calls]
    results = []
    for call in calls:
        try:
            value = program.call(call["module"], call["function"], call["arguments"])
        except (ValueError, TypeError, ArithmeticError, LookupError, RecursionError) as error:
            kind = str(error) if type(error) is ProgramPolicyError else type(error).__name__
            results.append({"case_id": call["case_id"], "kind": "raised", "type": kind})
        else:
            # Freeze each observation before a later call can mutate a shared
            # JSON container returned by an earlier function.
            results.append({"case_id": call["case_id"], "kind": "returned",
                            "value": json.loads(canonical(value))})
    return results


def observe():
    archive = json.loads(Path("/inputs/workspace.json").read_bytes())
    context = json.loads(Path("/inputs/context.json").read_bytes())
    calls = json.loads(Path("/inputs/calls.json").read_bytes())
    roots = json.loads(Path("/inputs/imports.json").read_bytes())
    results = observe_calls(archive, roots, calls)
    report = {
        "schema": "aioa.python-observation.v2",
        "profile_digest": context["profile_digest"],
        "patchset_sha256": context["patchset_sha256"],
        "stage": context["stage"],
        "results": results,
    }
    print(canonical(report).decode(), flush=True)
    Path("/artifacts/calls-complete.txt").write_bytes(b"PYTHON_CALLS_FINISHED\n")


if __name__ == "__main__":
    mode = json.loads(Path("/inputs/mode.json").read_bytes())
    if mode == {"mode": "materialize"}:
        materialize()
    elif mode == {"mode": "observe"}:
        observe()
    else:
        raise ValueError("REPOSITORY_MODE")
