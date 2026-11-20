"""Real networkless Chrome UI and the existing Core coding controller.

No provider, repair success, local Git or production Native is simulated as
verified here. This gate proves real queue/start/STOP receipts and actual
403/pagehide cleanup in the same existing webapp and panel.
"""
import argparse
import hashlib
import importlib
import json
import os
import secrets
import stat
import sys
import threading
import time
from dataclasses import asdict
from pathlib import Path, PurePosixPath
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'tests')]
from runtime.browser_agent.chrome_process_read import run_bounded, sandbox_command
from runtime.providers.exact import CancellationToken, _unique_object

DEPENDENCY_PACKAGES = frozenset(('pydantic', 'pydantic_core', 'annotated_types',
                                 'typing_inspection', 'typing_extensions.py', 'uuid6'))
DEPENDENCY_DENIED = frozenset(('REVIEW_NZ12_MAIN_RANGE.md', 'REVIEW_NZ12_RAW.json',
    'D7_RENDER_STARTUP_DIAGNOSTIC_R3', 'D7_RENDER_STARTUP_DIAGNOSTIC_R3.json',
    'D7_RENDER_STARTUP_DIAGNOSTIC_R3.log', '.env', 'auth.json', 'credentials',
    'id_rsa', 'id_ed25519', '__pycache__'))


def _dependency_require(value, code):
    if not value:
        raise ValueError(code)


def _dependency_file(path, artifacts_root, maximum):
    path, artifacts_root = Path(path), Path(artifacts_root)
    for candidate in (path, artifacts_root):
        _dependency_require(candidate.is_absolute() and '..' not in candidate.parts
            and not DEPENDENCY_DENIED.intersection(candidate.parts)
            and '\\' not in str(candidate) and '\x00' not in str(candidate), 'CODING_DEPS_PATH_DENIED')
    _dependency_require(path.is_relative_to(artifacts_root), 'CODING_DEPS_PATH_DENIED')
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    parent = os.open('/', flags)
    descriptor = None
    try:
        for part in path.parts[1:-1]:
            child = os.open(part, flags, dir_fd=parent)
            os.close(parent)
            parent = child
        descriptor = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK, dir_fd=parent)
        before = os.fstat(descriptor)
        _dependency_require(stat.S_ISREG(before.st_mode) and before.st_uid == os.getuid()
            and before.st_nlink == 1 and not before.st_mode & 0o022
            and 0 <= before.st_size <= maximum, 'CODING_DEPS_FILE_DENIED')
        with os.fdopen(descriptor, 'rb', closefd=False) as stream:
            raw = stream.read(maximum + 1)
        def identity(info):
            return (info.st_dev, info.st_ino, info.st_mode, info.st_uid, info.st_gid,
                    info.st_nlink, info.st_size, info.st_mtime_ns, info.st_ctime_ns)
        _dependency_require(identity(before) == identity(os.fstat(descriptor)) ==
            identity(os.stat(path.name, dir_fd=parent, follow_symlinks=False))
            and len(raw) == before.st_size, 'CODING_DEPS_FILE_DRIFT')
        return raw
    finally:
        if descriptor is not None:
            os.close(descriptor)
        os.close(parent)


def dependency_mounts(manifest, expected_sha256, *, artifacts_root=None):
    """Read only individually pinned public package snapshot files; no host venv."""
    artifacts_root = ROOT.parent / 'artifacts' if artifacts_root is None else Path(artifacts_root)
    manifest = Path(manifest)
    _dependency_require(manifest.name == 'DEPENDENCIES.json' and type(expected_sha256) is str
        and len(expected_sha256) == 64 and set(expected_sha256) <= set('0123456789abcdef'),
        'CODING_DEPS_MANIFEST_DENIED')
    raw = _dependency_file(manifest, artifacts_root, 4194304)
    _dependency_require(hashlib.sha256(raw).hexdigest() == expected_sha256, 'CODING_DEPS_MANIFEST_HASH')
    value = json.loads(raw, object_pairs_hook=_unique_object)
    _dependency_require(type(value) is dict and set(value) == {'schema', 'python', 'files', 'distributions'}
        and value['schema'] == 'aioa.nz13.coding-chrome-python-deps.v1'
        and value['python'] == [3, 12] and type(value['files']) is dict
        and 12 <= len(value['files']) <= 4096
        and type(value['distributions']) is dict
        and set(value['distributions']) == {name.removesuffix('.py') for name in DEPENDENCY_PACKAGES}, 'CODING_DEPS_MANIFEST_SHAPE')
    metadata_members = set()
    for name, directory in value['distributions'].items():
        _dependency_require(type(directory) is str and directory.startswith(name + '-')
            and directory.endswith('.dist-info'), 'CODING_DEPS_DISTRIBUTION_ROOT')
        version = directory[len(name) + 1:-len('.dist-info')]
        _dependency_require(0 < len(version) <= 64 and '..' not in version
            and all(char.isascii() and (char.isalnum() or char in '.+_') for char in version),
            'CODING_DEPS_DISTRIBUTION_VERSION')
        metadata_members.add(directory + '/METADATA')
    _dependency_require(len(metadata_members) == 6, 'CODING_DEPS_DISTRIBUTION_ROOT')
    files, total = value['files'], 0
    required = {name + '/__init__.py' for name in DEPENDENCY_PACKAGES if name != 'typing_extensions.py'}
    required.add('typing_extensions.py')
    required.update(metadata_members)
    _dependency_require(required <= set(files), 'CODING_DEPS_PACKAGE_ROOTS')
    for name, entry in files.items():
        path = PurePosixPath(name)
        _dependency_require(type(name) is str and path.as_posix() == name and not path.is_absolute()
            and path.parts and '..' not in path.parts and not DEPENDENCY_DENIED.intersection(path.parts)
            and '\\' not in name and '\x00' not in name and len(name) <= 512
            and all(char.isascii() and (char.isalnum() or char in '_./+-') for char in name)
            and (path.parts[0] in DEPENDENCY_PACKAGES or name in metadata_members)
            and not name.endswith(('.pyc', '.key', '.pem'))
            and (path.parts[0] != 'typing_extensions.py' or len(path.parts) == 1), 'CODING_DEPS_MEMBER_DENIED')
        _dependency_require(type(entry) is dict and set(entry) == {'bytes', 'sha256'}
            and type(entry['bytes']) is int and 0 <= entry['bytes'] <= 16777216
            and type(entry['sha256']) is str and len(entry['sha256']) == 64
            and set(entry['sha256']) <= set('0123456789abcdef'), 'CODING_DEPS_MEMBER_SHAPE')
        total += entry['bytes']
    _dependency_require(total <= 33554432, 'CODING_DEPS_TOTAL_BOUND')
    destination = PurePosixPath('/opt/aioa-coding-deps')
    argv, created = ['--dir', str(destination)], {destination}
    for name, entry in sorted(files.items()):
        source = manifest.parent / 'files' / name
        data = _dependency_file(source, artifacts_root, 16777216)
        _dependency_require(len(data) == entry['bytes'] and hashlib.sha256(data).hexdigest() == entry['sha256'],
                            'CODING_DEPS_MEMBER_HASH')
        target = destination / name
        for parent in reversed(target.parents):
            if (parent == destination or parent.is_relative_to(destination)) and parent not in created:
                argv += ['--dir', str(parent)]
                created.add(parent)
        argv += ['--ro-bind', str(source), str(target)]
    argv += ['--setenv', 'PYTHONPATH', '/app:/opt/aioa-coding-deps',
             '--setenv', 'PYTHONPYCACHEPREFIX', '/tmp/aioa-coding-pyc']
    _dependency_require(sum(len(part.encode()) for part in argv) <= 131072, 'CODING_DEPS_ARGV_BOUND')
    return argv


def verify_dependency_imports():
    dependencies = {}
    for name in ('pydantic', 'pydantic_core', 'annotated_types', 'typing_inspection', 'typing_extensions', 'uuid6'):
        module = importlib.import_module(name)
        path = Path(module.__file__).resolve()
        _dependency_require(path.is_relative_to('/opt/aioa-coding-deps'), 'CODING_DEPS_IMPORT_ORIGIN')
        dependencies[name] = str(path)
    for name, module in tuple(sys.modules.items()):
        if name == 'runtime' or name.startswith(('runtime.', 'nonzero_cloudops.')) or name in ('main', 'webapp'):
            origin = getattr(module, '__file__', None)
            if origin is not None:
                _dependency_require(Path(origin).resolve().is_relative_to('/app'), 'CODING_SOURCE_IMPORT_ORIGIN')
    return dependencies


def drive_coding_lifecycle(case, task, pipe, session):
    """One actual STOP handler call after worker readiness; explicit bounded READs."""
    driver = r'''(async()=>{
      const node=id=>document.getElementById('coding-'+id);
      const wait=async(predicate)=>{for(let n=0;n<300;n++){
        if(predicate())return;await new Promise(r=>setTimeout(r,20));
      }throw Error('Core UI state timeout');};
      const state=()=>{try{return JSON.parse(node('evidence').textContent).state;}catch(_){return null;}};
      node('task').value=TASK_JSON;
      node('create').click();await wait(()=>state()==='QUEUED');
      const queued=JSON.parse(node('evidence').textContent);
      if(!queued.receipt_present&&queued.authority!=='NONE')throw Error('Core view missing');
      node('start').click();await wait(()=>state()==='RUNNING');
      return {queued:queued.state,running:state()};
    })()'''.replace('TASK_JSON', json.dumps(json.dumps(asdict(task))))
    answer = pipe.call('Runtime.evaluate', {'expression': driver, 'returnByValue': True,
                                          'awaitPromise': True}, session)
    assert not answer.get('exceptionDetails'), 'Browser queue/start failed'
    stages = answer['result']['value']
    assert stages == {'queued': 'QUEUED', 'running': 'RUNNING'}
    # RUNNING is committed before WaitingWorker.start; it is not readiness ACK.
    case.wait_started(task)
    stop_driver = r'''(async()=>{
      const node=id=>document.getElementById('coding-'+id);
      const state=()=>{try{return JSON.parse(node('evidence').textContent).state;}catch(_){return null;}};
      if(node('stop').disabled||typeof node('stop').onclick!=='function')throw Error('STOP unavailable');
      // Await the real mounted handler: exactly one POST, including its ACK.
      await node('stop').onclick();
      for(let n=0;n<300&&state()!=='CANCELLED';n++){
        if(state()&&state()!=='RUNNING')throw Error('Unexpected terminal or unresolved state');
        if(node('refresh').disabled||typeof node('refresh').onclick!=='function')throw Error('READ unavailable');
        // Each explicit UI refresh completes before another GET may start.
        await node('refresh').onclick();
        if(state()!=='CANCELLED')await new Promise(r=>setTimeout(r,20));
      }
      if(state()!=='CANCELLED')throw Error('Signed cancellation readback timeout');
      return {final:state(),approve_disabled:node('approve').disabled,
        apply_disabled:node('apply').disabled,stop_disabled:node('stop').disabled,
        persisted_secrets:localStorage.length+sessionStorage.length};
    })()'''
    answer = pipe.call('Runtime.evaluate', {'expression': stop_driver, 'returnByValue': True,
                                          'awaitPromise': True}, session)
    assert not answer.get('exceptionDetails'), 'Browser STOP/readback failed'
    return {'queued': stages['queued'], **answer['result']['value']}


def worker():
    from mobile_device_console_browser import verify_isolation
    verify_isolation()
    dependency_origins = verify_dependency_imports()
    import test_nz11_controller as support

    from runtime.core_admission import Capability
    from runtime.main import AgentRuntime
    from runtime.mobile_gateway.chrome_console import Pipe, cleanup_owned
    from runtime.webapp import AOIAWebHandler, WebRuntimeService, make_server
    case = support.ControllerTests('test_two_active_runs_cancel_independently_without_worker_or_core_replay')
    case.setUp()
    runtime = server = process = thread = None
    fds = []
    try:
        tasks = case.service()
        runtime = AgentRuntime(None, '', case.case.case.root, inspection_only=True, coding_tasks=tasks)
        principals = {name: case.fx.p(getattr(Capability, name))
                      for name in ('READ', 'MANAGE', 'COMMIT', 'OWNER_APPROVAL')}
        service = WebRuntimeService(runtime=runtime, coding_principals=principals)
        capture = []

        class CaptureHandler(AOIAWebHandler):
            def do_GET(self):
                capture.append(('GET', self.path))
                return super().do_GET()

            def do_POST(self):
                capture.append(('POST', self.path))
                return super().do_POST()

        with patch('runtime.webapp.AOIAWebHandler', CaptureHandler):
            server = make_server('127.0.0.1', 0, service)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        browser_read, parent_write = os.pipe()
        parent_read, browser_write = os.pipe()
        fds = [parent_read, parent_write]
        command = ['/bin/bash', '-c', 'exec 3<&' + str(browser_read) + ' 4>&' + str(browser_write) + '; exec "$@"',
                   'aioa-offline-coding-probe', '/opt/google/chrome/chrome', '--headless=new',
                   '--no-sandbox', '--disable-dev-shm-usage', '--remote-debugging-pipe',
                   '--disable-background-networking', '--disable-component-update', '--no-proxy-server',
                   '--user-data-dir=/tmp/coding-chrome', 'about:blank']
        process = __import__('subprocess').Popen(command, pass_fds=(browser_read, browser_write),
                    stdin=__import__('subprocess').DEVNULL, stdout=__import__('subprocess').DEVNULL,
                    stderr=__import__('subprocess').DEVNULL, start_new_session=True)
        os.close(browser_read)
        os.close(browser_write)
        pipe = Pipe(parent_write, parent_read)
        pipe.call('Browser.getVersion')
        target = pipe.call('Target.createTarget', {'url': 'about:blank'})['targetId']
        session = pipe.call('Target.attachToTarget', {'targetId': target, 'flatten': True})['sessionId']
        url = 'http://127.0.0.1:' + str(server.server_port) + '/'
        reply = pipe.call('Page.navigate', {'url': url}, session)
        assert not reply.get('errorText')
        for _ in range(200):
            state = pipe.call('Runtime.evaluate', {'expression':
                'document.querySelector("#coding-panel")?.hidden===false', 'returnByValue': True}, session)
            if state.get('result', {}).get('value') is True:
                break
            time.sleep(.02)
        else:
            raise AssertionError('Existing coding panel did not bootstrap')
        task = case.case.task
        ui = drive_coding_lifecycle(case, task, pipe, session)
        assert ui == {'queued': 'QUEUED', 'final': 'CANCELLED', 'approve_disabled': True,
                      'apply_disabled': True, 'stop_disabled': True, 'persisted_secrets': 0}, ui
        assert tasks.wait(task.task_id, 3)
        canonical = tasks.request(case.fx.p(Capability.READ), 'get_receipts', {'task_id': task.task_id})
        assert canonical['state'] == 'CANCELLED'
        assert [row['receipt']['state'] for row in canonical['receipts']] == ['QUEUED', 'RUNNING', 'CANCELLED']
        assert case.workers[task.task_id].cancels == 1
        assert len([r for r in capture if r == ('POST', '/api/agent/coding/start')]) == 1
        assert len([r for r in capture if r == ('POST', '/api/agent/coding/stop')]) == 1
        # Host invalidation changes the actual existing CSRF check. The old
        # browser session must close on that real 403 with no readback retry.
        service.csrf_token = secrets.token_urlsafe(32)
        before = len([r for r in capture if r[1].startswith('/api/agent/coding/')])
        expression = r'''(async()=>{
          const node=id=>document.getElementById('coding-'+id);
          node('refresh').click();
          for(let n=0;n<200&&!node('select').disabled;n++)await new Promise(r=>setTimeout(r,20));
          return {evidence:node('evidence').textContent,task:node('task').value,
                  id:node('task-id').value,closed:node('select').disabled&&node('start').disabled&&node('stop').disabled};
        })()'''
        value = pipe.call('Runtime.evaluate', {'expression': expression, 'returnByValue': True, 'awaitPromise': True}, session)
        assert value['result']['value'] == {'evidence': '', 'task': '', 'id': '', 'closed': True}
        after = len([r for r in capture if r[1].startswith('/api/agent/coding/')])
        assert after - before == 1, '403 caused a retry or hidden GET'
        # A fresh navigation obtains the new fixture session. pagehide clears
        # the real panel without changing/cancelling another Core operation.
        pipe.call('Page.reload', {}, session)
        for _ in range(200):
            value = pipe.call('Runtime.evaluate', {'expression':
                'document.querySelector("#coding-panel")?.hidden===false', 'returnByValue': True}, session)
            if value.get('result', {}).get('value') is True:
                break
            time.sleep(.02)
        expression = r'''(()=>{
          const node=id=>document.getElementById('coding-'+id);
          node('task-id').value='INERT_UNSENT_FIXTURE';node('task').value='INERT_UNSENT_FIXTURE';
          window.dispatchEvent(new Event('pagehide'));
          return node('task-id').value===''&&node('task').value===''&&node('evidence').textContent===''&&
            node('select').disabled&&node('create').disabled&&node('approve').disabled;
        })()'''
        value = pipe.call('Runtime.evaluate', {'expression': expression, 'returnByValue': True}, session)
        assert value['result']['value'] is True
        result = {'schema': 'aioa.nz13.coding-chrome-acceptance.v1', 'status': 'PASS_REAL_OFFLINE_UI_ONLY',
                  'same_core': runtime._memory_patch_admission is case.fx.core,
                  'actual_worker': 'WAITING_FIXTURE_NO_INFERENCE', 'states': ['QUEUED', 'RUNNING', 'CANCELLED'],
                  'receipts': canonical['receipts'], 'cancel_calls': 1,
                  'real_403_closed_session_no_retry': True, 'pagehide_cleared_ram_and_controls': True,
                  'provider_calls': 0, 'external_network': False, 'production_native': 'NOT_TOUCHED',
                  'repair_git_pipeline': 'SEPARATE_KERNEL_GATE', 'native_os_authentication': 'NOT_CERTIFIED_BY_THIS_GATE'}
        assert result['same_core']
        assert verify_dependency_imports() == dependency_origins
        result['dependency_origins'] = dependency_origins
        result['runtime_imports_from_current_app_verified'] = True
        Path('/out/NZ13_CODING_CHROME_ACCEPTANCE.json').write_text(json.dumps(result, indent=2))
        print(json.dumps({'status': result['status'], 'states': result['states']}), flush=True)
    finally:
        if process is not None:
            cleanup_owned(process, timeout=1)
        for fd in fds:
            os.close(fd)
        if server is not None:
            server.shutdown()
            server.server_close()
        if thread is not None:
            thread.join(3)
        if runtime is not None:
            runtime.close()
        case.doCleanups()


def main(output, sha, dependencies, dependency_sha256):
    extra = dependency_mounts(dependencies, dependency_sha256)
    output.mkdir(mode=0o700, parents=True, exist_ok=False)
    command = sandbox_command(output, 1280, 900, sha)
    command = command[:command.index('--')] + extra
    command += ['--ro-bind', str(ROOT / 'tests'), '/app/tests', '--',
                '/usr/bin/python3', '-B', '/app/tests/nz13_coding_browser_acceptance.py', '--worker']
    code, stdout, stderr = run_bounded(command, CancellationToken(), 120)
    assert code == 0, ('OFFLINE_CODING_CHROME_FAILED', code, stderr[-1500:].decode('utf-8', 'replace'))
    proof = json.loads((output / 'NZ13_CODING_CHROME_ACCEPTANCE.json').read_text())
    assert proof['status'] == 'PASS_REAL_OFFLINE_UI_ONLY'
    print(stdout.decode(), end='')


if __name__ == '__main__':
    if sys.argv[1:] == ['--worker']:
        worker()
    else:
        parser = argparse.ArgumentParser()
        parser.add_argument('output', type=Path)
        parser.add_argument('source_sha')
        parser.add_argument('dependencies', type=Path)
        parser.add_argument('dependencies_sha256')
        args = parser.parse_args()
        main(args.output, args.source_sha, args.dependencies, args.dependencies_sha256)
