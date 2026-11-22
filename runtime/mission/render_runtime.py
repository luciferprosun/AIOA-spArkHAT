"""Explicit operator capture of a closed, root-owned renderer runtime.

No acquisition, package manager, model command, profile, home directory or host
credential is included. Execution remains with the one existing Linux broker.
"""
import hashlib
import os
import re
import stat
import subprocess
from dataclasses import replace
from pathlib import Path

RENDERER_RUNTIME_FILES = tuple('/opt/google/chrome/' + name for name in (
    'chrome', 'chrome_crashpad_handler', 'icudtl.dat', 'resources.pak',
    'chrome_100_percent.pak', 'chrome_200_percent.pak', 'v8_context_snapshot.bin',
    'locales/en-US.pak')) + ('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',)


def require(value, code):
    if not value:
        raise ValueError(code)


def parse_renderer_dependencies(output):
    require(type(output) is str and 0 < len(output) <= 32768,
            'RENDER_RUNTIME_DEPENDENCY_BOUND')
    paths = set()
    for line in output.splitlines():
        line = line.strip()
        if not line:
            continue
        if re.fullmatch(r'linux-vdso\.so\.\d+ \(0x[0-9a-fA-F]+\)', line):
            continue
        match = re.fullmatch(r'(?:[A-Za-z0-9_.+-]+ => )?(/[^\s()]+) \(0x[0-9a-fA-F]+\)', line)
        require(match is not None, 'RENDER_RUNTIME_DEPENDENCY_UNKNOWN')
        path = match.group(1)
        require(path.startswith(('/lib/', '/lib64/'))
                and all(part not in ('', '.', '..') for part in path.split('/')[1:])
                and re.fullmatch(r'/[A-Za-z0-9_./+-]+', path), 'RENDER_RUNTIME_DEPENDENCY_PATH')
        paths.add(path)
        require(len(paths) <= 128, 'RENDER_RUNTIME_DEPENDENCY_BOUND')
    require(paths, 'RENDER_RUNTIME_DEPENDENCY_EMPTY')
    return tuple(sorted(paths))


def _identity(info):
    return (info.st_dev, info.st_ino, info.st_uid, info.st_gid, info.st_mode,
            info.st_nlink, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def _copy_root_owned(source, destination):
    resolved = source.resolve(strict=True)
    require(str(resolved).startswith(('/usr/lib/', '/opt/google/chrome/', '/usr/share/fonts/')),
            'RENDER_RUNTIME_SOURCE_PATH')
    fd = os.open(resolved, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        before = os.fstat(fd)
        require(stat.S_ISREG(before.st_mode) and before.st_uid == 0
                and not before.st_mode & 0o022 and before.st_nlink == 1
                and 0 < before.st_size <= 350 * 1024 * 1024, 'RENDER_RUNTIME_SOURCE_OWNER')
        digest = hashlib.sha256()
        count = 0
        with destination.open('xb') as stream:
            os.fchmod(stream.fileno(), 0o500 if before.st_mode & 0o111 else 0o400)
            while True:
                data = os.read(fd, 65536)
                if not data:
                    break
                count += len(data)
                require(count <= before.st_size, 'RENDER_RUNTIME_SOURCE_DRIFT')
                digest.update(data)
                stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        require(_identity(before) == _identity(os.fstat(fd)) == _identity(resolved.lstat())
                and count == before.st_size, 'RENDER_RUNTIME_SOURCE_DRIFT')
        return {'snapshot': str(destination), 'bytes': count, 'sha256': digest.hexdigest()}
    finally:
        os.close(fd)


def snapshot_renderer_runtime(root):
    from runtime.mission.project_recipe import snapshot_python_runtime

    root = Path(root).absolute()
    files = set(RENDERER_RUNTIME_FILES)
    for executable in ('/opt/google/chrome/chrome', '/opt/google/chrome/chrome_crashpad_handler'):
        info = Path(executable).lstat()
        require(stat.S_ISREG(info.st_mode) and info.st_uid == 0
                and not info.st_mode & 0o022, 'RENDER_RUNTIME_SOURCE_OWNER')
        result = subprocess.run(['/usr/bin/ldd', executable], capture_output=True, text=True,
                                timeout=5, check=False, env={'PATH': '/usr/bin:/bin', 'LANG': 'C'})
        require(result.returncode == 0, 'RENDER_RUNTIME_DEPENDENCY_UNKNOWN')
        files.update(parse_renderer_dependencies(result.stdout))
    # Reuse the existing fixed Python capture. No secondary runtime/executor.
    manifest = snapshot_python_runtime(root)
    total = 0
    for index, target in enumerate(sorted(files - set(manifest))):
        entry = _copy_root_owned(Path(target), root / ('renderer-' + str(index)))
        total += entry['bytes']
        require(total <= 512 * 1024 * 1024, 'RENDER_RUNTIME_TOTAL_BOUND')
        manifest[target] = entry
    directory = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)
    return manifest


def prepare_html_render_sandbox(root, *, workspace, recipe):
    from runtime.mission.render_recipe import HtmlRenderRecipe
    from runtime.mission.sandbox_contracts import SandboxRegistry
    from runtime.mission.sandbox_linux import prepare_linux_sandbox

    require(type(recipe) is HtmlRenderRecipe, 'RENDER_OPERATOR_RECIPE_REQUIRED')
    recipe.__post_init__()
    root = Path(root).absolute()
    require(not os.path.lexists(root), 'RENDER_PREPARATION_EXISTS')
    runtime = snapshot_renderer_runtime(root.with_name(root.name + '-runtime'))
    config = prepare_linux_sandbox(
        root, runtime, workspace=workspace,
        recipes={'recipe:html-' + recipe.digest[:24]: recipe.recipe_spec()},
        resource_profile='HEADLESS_RENDER_V3', renderer_ipc='RENDER_UNIX_MOJO_V1')
    return replace(config, registry=SandboxRegistry(
        workspace, tuple(replace(item, timeout_ms=20000, max_output_bytes=16384)
                         for item in config.registry.recipes)))
