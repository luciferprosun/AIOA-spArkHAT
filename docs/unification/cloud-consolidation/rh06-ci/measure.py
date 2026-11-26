"""One diagnostic trial. Run in a clean baseline or PR checkout via nz12_ci_host.sh.

Overlay two clock-instrumented source files only inside the networkless worker.
The release workflow and its test sources stay byte-for-byte intact.
"""
import hashlib
import os
from pathlib import Path
import subprocess
import sys
import tempfile

root = Path.cwd()
sys.path[:0] = [str(root), str(root / "tests")]
import mobile_device_console_browser as fixture


def add_clock(source, anchor, addition):
    if source.count(anchor) != 1:
        raise ValueError("Unexpected clock location")
    return source.replace(anchor, addition + anchor)


def checked_source(relative, blob):
    path = root / relative
    actual = subprocess.check_output(["git", "hash-object", str(path)], text=True).strip()
    if actual != blob:
        raise ValueError(f"Unexpected source for {relative}")
    return path.read_text()


def main():
    browser = checked_source("tests/mobile_device_console_browser.py", "cafd2c1d0180437a6bfd7f9dcd5887a3b50397f0")
    pipe = checked_source("runtime/mobile_gateway/chrome_console.py", "678deb657d537e6d45e5fa28269c87190cd2fcfe")
    browser = add_clock(browser, "            process=subprocess.Popen(command", "            launch=time.monotonic()\n")
    browser = add_clock(browser, "                    # Invalid canary,", """                    finally:
                        print('RH06_CLOCK '+json.dumps({'launch':launch,'open_document':started,
                              'worker_python':sys.version.split()[0],'worker_path':sys.executable,
                              'first_data':getattr(pipe,'first_data',None),
                              'first_reply':getattr(pipe,'first_reply',None),
                              'send_complete':getattr(pipe,'send_complete',None)}),flush=True)
""")
    pipe = add_clock(pipe, "        while True:\n            # A ready pipe",
                     "        if identity==1:self.send_complete=deadline-15\n")
    pipe = add_clock(pipe, "            self.buffer+=chunk",
                     "            if identity==1 and not hasattr(self,'first_data'):self.first_data=time.monotonic()\n")
    pipe = add_clock(pipe, "                    return value.get('result',{})",
                     "                    if identity==1:self.first_reply=time.monotonic()\n")
    if os.environ.get("RH06_LATE_OBSERVATION") == "1":
        browser = add_clock(browser, "                        raise\n                    finally:", """                        if pipe.sequence == 1 and str(sys.exc_info()[1]) == 'CHROME_COMMAND_UNKNOWN':
                            import select
                            deadline = time.monotonic() + 10
                            pending = pipe.buffer
                            result = 'NO_MATCH'
                            while len(pending) <= 2 * 1024 * 1024:
                                remaining = deadline - time.monotonic()
                                if remaining <= 0 or not select.select([pipe.reader], [], [], remaining)[0]:
                                    break
                                chunk = os.read(pipe.reader, 65536)
                                if not chunk:
                                    result = 'EOF'
                                    break
                                pending += chunk
                                while b'\\0' in pending:
                                    packet, pending = pending.split(b'\\0', 1)
                                    obj = json.loads(packet)
                                    if type(obj.get('id')) is int and obj['id'] == 1:
                                        result = 'MATCH_RESULT' if isinstance(obj.get('result'), dict) else 'MATCH_ERROR'
                                        break
                                if result != 'NO_MATCH':
                                    break
                            print('RH06_LATE', result, round(time.monotonic()-pipe.send_complete, 6), flush=True)
""")
    build = fixture.browser_command
    with tempfile.TemporaryDirectory() as temp:
        mounts = []
        for source, target in [(browser, "/app/tests/mobile_device_console_browser.py"),
                               (pipe, "/app/runtime/mobile_gateway/chrome_console.py")]:
            path = Path(temp) / Path(target).name
            path.write_text(source)
            compile(source, target, "exec")
            print("clock_overlay", target, hashlib.sha256(path.read_bytes()).hexdigest(), flush=True)
            mounts.extend(["--ro-bind", str(path), target])

        def with_clocks(output, sha):
            argv = build(output, sha)
            index = argv.index("--")
            return argv[:index] + mounts + argv[index:]

        fixture.browser_command = with_clocks
        sys.argv = [str(root / "tests/mobile_device_console_browser.py")]
        fixture.main()


if __name__ == "__main__":
    main()
