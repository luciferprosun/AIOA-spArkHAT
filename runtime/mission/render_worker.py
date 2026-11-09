"""Fixed renderer parent for LinuxSandboxBroker; refuses execution on the host."""
import base64
import fcntl
import hashlib
import json
import os
import runpy
import subprocess
import sys
import time
from pathlib import Path


def require(value, code):
    if not value:
        raise ValueError(code)


def confined():
    status = Path('/proc/self/status').read_text()
    require('NoNewPrivs:\t1' in status and 'Seccomp:\t2' in status
            and Path('/bootstrap').is_file()
            and os.statvfs('/inputs/recipe.py').f_flag & os.ST_RDONLY,
            'SANDBOX_ONLY_RENDERER')


def chrome_argv():
    return ['/opt/google/chrome/chrome', '--headless=new', '--no-sandbox', '--no-zygote',
            '--disable-gpu', '--disable-software-rasterizer', '--disable-dev-shm-usage',
            '--disable-background-networking', '--disable-component-update',
            '--disable-extensions', '--disable-sync', '--no-first-run',
            '--no-default-browser-check', '--disable-breakpad', '--disable-crash-reporter',
            '--password-store=basic', '--use-mock-keychain', '--renderer-process-limit=1',
            '--remote-debugging-pipe', '--user-data-dir=/work/chrome', 'about:blank']


def chrome_exec(read_fd, write_fd):
    require(read_fd >= 3 and write_fd >= 3 and read_fd != write_fd, 'RENDER_PIPE_FDS')
    # Copy both before remapping, including the source-fd 3/4 collision case.
    read_copy = fcntl.fcntl(read_fd, fcntl.F_DUPFD_CLOEXEC, 10)
    write_copy = fcntl.fcntl(write_fd, fcntl.F_DUPFD_CLOEXEC, 10)
    os.dup2(read_copy, 3, inheritable=True)
    os.dup2(write_copy, 4, inheritable=True)
    for fd in {read_fd, write_fd, read_copy, write_copy} - {3, 4}:
        os.close(fd)
    os.execve(chrome_argv()[0], chrome_argv(), {
        'PATH': '/usr/bin:/bin', 'LANG': 'C.UTF-8', 'HOME': '/work/chrome', 'TMPDIR': '/tmp',
        'FONTCONFIG_FILE': '/inputs/fonts.conf'})


def run():
    config = json.loads(Path('/inputs/render.json').read_bytes())
    require(type(config) is dict and set(config) == {'schema', 'recipe_digest', 'viewport', 'bundle'}
            and config['schema'] == 'aioa.hermetic-render-input.v1', 'RENDER_INPUT_SCHEMA')
    site = Path('/work/site')
    site.mkdir(mode=0o700)
    require(type(config['bundle']) is dict and 1 <= len(config['bundle']) <= 3
            and 'index.html' in config['bundle'], 'RENDER_BUNDLE')
    for name, pin in config['bundle'].items():
        require(name in ('index.html', 'style.css', 'app.js'), 'RENDER_BUNDLE')
        data = Path('/inputs/page-' + name).read_bytes()
        require(type(pin) is dict and pin == {'sha256': hashlib.sha256(data).hexdigest(), 'bytes': len(data)}
                and 0 < len(data) <= 32768, 'RENDER_BUNDLE_PIN')
        with (site / name).open('xb') as stream:
            stream.write(data)
    Path('/work/chrome').mkdir(mode=0o700)
    Path('/work/font-cache').mkdir(mode=0o700)
    support = runpy.run_path('/inputs/chrome_pipe.py')
    browser_read, parent_write = os.pipe()
    parent_read, browser_write = os.pipe()
    process = None
    session = None
    errors = 0

    def event(value):
        nonlocal errors
        if value.get('sessionId') != session:
            return
        if (value.get('method') == 'Runtime.exceptionThrown'
                or value.get('method') == 'Runtime.consoleAPICalled'
                and value.get('params', {}).get('type') in ('error', 'assert')):
            errors += 1
            require(errors <= 32, 'RENDER_EVENT_BUDGET')

    try:
        process = subprocess.Popen(
            ['/usr/bin/python3.12', '-I', '-S', '-B', '/inputs/recipe.py',
             '--chrome-exec', str(browser_read), str(browser_write)],
            pass_fds=(browser_read, browser_write), stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, close_fds=True,
            env={'PATH': '/usr/bin:/bin', 'LANG': 'C.UTF-8'})
        os.close(browser_read)
        os.close(browser_write)
        browser_read = browser_write = None
        pipe = support['Pipe'](parent_write, parent_read, on_event=event)
        pipe.call('Browser.getVersion')
        target = pipe.call('Target.createTarget', {'url': 'about:blank'})['targetId']
        session = pipe.call('Target.attachToTarget', {'targetId': target, 'flatten': True})['sessionId']
        pipe.call('Runtime.enable', {}, session)
        pipe.call('Page.enable', {}, session)
        width, height = config['viewport']
        pipe.call('Emulation.setDeviceMetricsOverride', {
            'width': width, 'height': height, 'deviceScaleFactor': 1, 'mobile': False}, session)
        result = pipe.call('Page.navigate', {'url': 'file:///work/site/index.html'}, session)
        require(not result.get('errorText') and not result.get('isDownload'), 'RENDER_NAVIGATION')
        require(type(result.get('frameId')) is str and 0 < len(result['frameId']) <= 128, 'RENDER_NAVIGATION')
        Path('/artifacts/render-browser-ready.txt').write_bytes(b'CHROME_FILE_NAVIGATION_ACK\n')
        expression = ('({href:location.href,ready_state:document.readyState,'
                      'title:document.title.slice(0,257),body_text:(document.body?.innerText||"").slice(0,2049)})')
        document = None
        for _ in range(30):
            document = pipe.call('Runtime.evaluate', {'expression': expression, 'returnByValue': True}, session)
            document = document.get('result', {}).get('value')
            if (type(document) is dict and document.get('href') == 'file:///work/site/index.html'
                    and document.get('ready_state') == 'complete'):
                break
            time.sleep(.05)
        require(type(document) is dict and document.get('ready_state') == 'complete', 'RENDER_DOCUMENT_NOT_READY')
        screenshot = pipe.call('Page.captureScreenshot', {
            'format': 'png', 'captureBeyondViewport': False, 'fromSurface': True}, session)['data']
        require(type(screenshot) is str and len(screenshot) <= 10924
                and len(base64.b64decode(screenshot, validate=True)) <= 8192, 'RENDER_SCREENSHOT_BOUND')
        # This final command also drains already queued exception/console events.
        pipe.call('Runtime.evaluate', {'expression': 'document.readyState', 'returnByValue': True}, session)
        value = {'schema': 'aioa.hermetic-render-observation.v1', 'recipe_digest': config['recipe_digest'],
                 'document': document, 'screenshot_base64': screenshot, 'console_errors': errors,
                 'transport': {'kind': 'CDP_PIPE', 'network': 'OFF', 'profile': 'FRESH'}}
        raw = json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False).encode()
        require(len(raw) <= 16384, 'RENDER_OBSERVATION_BOUND')
        Path('/artifacts/render-executed.txt').write_bytes(b'RENDER_PROCESS_FINISHED\n')
        sys.stdout.buffer.write(raw + b'\n')
    finally:
        for fd in (browser_read, browser_write, parent_read, parent_write):
            if fd is not None:
                os.close(fd)
        if process is not None:
            support['cleanup_owned'](process, timeout=1)


if __name__ == '__main__':
    confined()
    if len(sys.argv) == 4 and sys.argv[1] == '--chrome-exec':
        chrome_exec(int(sys.argv[2]), int(sys.argv[3]))
    else:
        require(len(sys.argv) == 1, 'RENDER_FIXED_ENTRYPOINT')
        run()
