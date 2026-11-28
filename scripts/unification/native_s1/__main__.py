"""Native S1 operator commands. Only the installed launcher can run roles."""

import argparse
import hashlib
import json
import os
import re
import sys
import tarfile
from pathlib import Path

from scripts.unification import noble_preflight as preflight
from scripts.unification.native_s1 import host


def _pins(cmd, *, installed=False):
    cmd.add_argument("--manifest", type=Path, default=host.CONFIG / "manifest.json" if installed else None)
    cmd.add_argument("--manifest-sha256", required=not installed)
    cmd.add_argument("--management-receipt", type=Path,
                     default=host.CONFIG / "management.json" if installed else None)


def parser():
    cli = argparse.ArgumentParser(description=__doc__)
    commands = cli.add_subparsers(dest="command", required=True)
    receipt = commands.add_parser("management-receipt", help="pack externally authenticated management facts")
    for flag in ("image", "boot", "signed-packages"):
        receipt.add_argument("--" + flag, required=True)
    receipt.add_argument("--output", type=Path, required=True)

    manifest = commands.add_parser("manifest", help="pin the exact code, external receipt and runtime inputs")
    for flag in ("source", "tree", "kernel", "runtime-digest", "wheels-digest"):
        manifest.add_argument("--" + flag, required=True)
    manifest.add_argument("--receipt", type=Path, required=True)
    manifest.add_argument("--core-uid", type=int, required=True)
    manifest.add_argument("--output", type=Path, required=True)

    measure = commands.add_parser("measure-runtime", help="measure guest Python sandbox inputs without attesting them")
    measure.add_argument("--output", type=Path, required=True)
    inspect = commands.add_parser("preflight", help="check environment, source pins and external receipt")
    _pins(inspect, installed=True)

    install = commands.add_parser("install", help="install frozen source and the scoped service unit on Noble")
    _pins(install)
    install.add_argument("--runtime", type=Path, required=True)
    install.add_argument("--wheelhouse", type=Path, required=True)

    run = commands.add_parser("run", help="run a supported case on the installed, authorized host")
    run.add_argument("--manifest-sha256", required=True)
    run.add_argument("--predecessor", help="retained F4 session for the F4-FOLLOWUP case")
    run.add_argument("case")
    matrix = commands.add_parser("matrix", help="run the installed cases and report uncovered acceptance evidence")
    matrix.add_argument("--manifest-sha256", required=True)
    collect = commands.add_parser("collect", help="create a private redacted case archive with SHA256SUMS")
    collect.add_argument("--session", required=True)
    collect.add_argument("--output", type=Path, required=True)
    child = commands.add_parser("_role", help=argparse.SUPPRESS)
    child.add_argument("name")
    child.add_argument("control", type=int)
    child.add_argument("ready", type=int)
    child.add_argument("completion", nargs="?", type=int)
    return cli


def _check(args):
    if args.manifest_sha256 is None:
        observed = preflight.observe()
        gaps = preflight.host_gaps(observed)
        print(json.dumps({"status": "BLOCKED_HOST", "missing": gaps + ["EXTERNAL_OPERATOR_PINS"],
                          "source": observed["source"], "tree": observed["tree"], "sessions": 0}))
        return 2
    _, observed = host.host_pins(args.manifest, args.manifest_sha256, args.management_receipt,
                                 system=os.geteuid() == 0)
    print(json.dumps({"status": "HOST_PINS_MATCHED", "observed": observed, "sessions": 0}))
    return 0


def _collect(session, output):
    # Private operational evidence. Keys, raw DBs, raw role logs and task
    # material are deliberately excluded from this archive.
    import io
    import stat

    host.host_release()
    host.require(os.geteuid() == 0 and re.fullmatch("[0-9a-f]{32}", session), "NATIVE_S1_EXPORT")
    root = host.BASE / session
    host.trusted(root, directory=True)
    names = ["operator/case.json", "writer-policy", "writer-launch", "writer-process",
             "writer-closed", "writer-closed-synced", "tls-ca.pem"]
    names.extend("operator/" + name + ".apparmor" for name in ("core", "broker", "verifier", "sequencer"))
    evidence = root / "evidence"
    if evidence.is_dir():
        names.extend("evidence/" + item.name for item in sorted(evidence.iterdir())
                     if re.fullmatch(r"(?:completion-)?[0-9a-f]{64}", item.name))
    contents = {}
    for name in names:
        try:
            fd = os.open(root / name, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW | os.O_NONBLOCK)
        except FileNotFoundError:
            continue
        with os.fdopen(fd, "rb") as stream:
            row = os.fstat(stream.fileno())
            host.require(stat.S_ISREG(row.st_mode) and row.st_nlink == 1
                         and 0 < row.st_size <= 65536, "NATIVE_S1_EXPORT_SOURCE")
            raw = stream.read(65537)
            host.require(len(raw) == row.st_size, "NATIVE_S1_EXPORT_DRIFT")
        contents[name] = raw
    host.require("operator/case.json" in contents, "NATIVE_S1_EXPORT_REPORT")
    contents["SHA256SUMS"] = "".join(f"{hashlib.sha256(raw).hexdigest()}  {name}\n"
                                    for name, raw in contents.items()).encode("ascii")
    with os.fdopen(os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600), "wb") as stream:
        with tarfile.open(fileobj=stream, mode="w:gz") as archive:
            for name, raw in contents.items():
                member = tarfile.TarInfo(name)
                member.size, member.mode = len(raw), 0o600
                archive.addfile(member, io.BytesIO(raw))
        stream.flush()
        os.fsync(stream.fileno())


def _matrix(digest):
    from scripts.unification.native_s1.coordinator import MANDATORY, SCENARIOS, run_case
    from scripts.unification.native_s1.roles import B2_CASES, REPLAYS

    rows = []
    cases = {}
    held = None

    def retained_case(session):
        root = host.BASE / session
        paths = [root / 'core/profile/core-records.sqlite3', root / 'operator/case.json',
                 root / 'sequencer/outstanding', *(root / 'state').iterdir()]
        return {path.relative_to(root).as_posix(): host.sha(path.read_bytes()) for path in paths if path.is_file()}

    for case in MANDATORY:
        if case == 'H0':
            continue  # Report only after actual P1 role attestation below.
        if case in ('R2', 'B2'):
            variants = [run_case(name, digest) for name in (REPLAYS if case == 'R2' else B2_CASES)]
            rows.append({'case': case, 'status': 'PASS' if all(row['status'] == 'PASS' for row in variants) else 'FAIL',
                         'cases': [{key: variant[key] for key in ('case', 'status', 'session', 'metrics')}
                                   for variant in variants]})
            continue
        if case == 'I1':
            separate = cases.get('F3', {})
            covered = held is not None and separate.get('status') == 'PASS'
            unchanged = covered and held == retained_case(cases['C3']['session'])
            rows.append({'case': 'I1', 'status': 'FAIL' if covered and not unchanged else 'NOT_RUN',
                         'reason': 'ORIGINAL_HISTORY_RETENTION_EVIDENCE_REQUIRED', 'historical_journal': 'NOT_ACCESSED',
                         'synthetic_held_isolation': 'PASS' if unchanged else 'FAIL' if covered else 'NOT_RUN'})
            continue
        if case not in SCENARIOS:
            rows.append({"case": case, "status": "NOT_RUN", "reason": "HOST_CASE_DRIVER_UNIMPLEMENTED"})
            continue
        result = run_case(case, digest)
        cases[case] = result
        if case == 'C3' and result['status'] == 'PASS':
            held = retained_case(result['session'])
        if case == 'F4' and result['status'] == 'PASS':
            second = run_case('F4-FOLLOWUP', digest, predecessor=result['session'])
            rows.append({'case': 'F4', 'status': second['status'], 'cases': [
                {key: run[key] for key in ('case', 'status', 'session', 'metrics')} for run in (result, second)]})
            continue
        rows.append({key: result[key] for key in ("case", "status", "session", "metrics")})
    p1 = cases['P1']
    rows.insert(0, {'case': 'H0', 'status': 'PASS' if p1['status'] == 'PASS' else 'NOT_RUN',
                    'session': p1['session'], 'scope': 'Actual host, policy and role proof from P1'})
    print(json.dumps({"status": "INCOMPLETE" if any(row["status"] != "PASS" for row in rows) else "PASS",
                      "cases": rows}, sort_keys=True))
    return 1 if any(row["status"] != "PASS" for row in rows) else 0


def main():
    args = parser().parse_args()
    try:
        if args.command == "management-receipt":
            print(host.management_receipt(image=args.image, boot=args.boot, signed_packages=args.signed_packages,
                                          output=args.output))
        elif args.command == "manifest":
            print(host.manifest(source=args.source, tree=args.tree, kernel=args.kernel, receipt=args.receipt,
                                runtime_digest=args.runtime_digest, wheels_digest=args.wheels_digest,
                                core_uid=args.core_uid, output=args.output))
        elif args.command == "measure-runtime":
            raw = host.canonical({"schema": "aioa.native-s1.runtime.v1", "files": host.runtime_allowlist()})
            with args.output.open("xb") as stream:
                stream.write(raw)
            print(host.sha(raw))
        elif args.command == "preflight":
            return _check(args)
        elif args.command == "install":
            print(json.dumps(host.install(args.manifest, args.manifest_sha256, args.management_receipt,
                                          args.runtime, wheelhouse=args.wheelhouse)))
        elif args.command == "run":
            from scripts.unification.native_s1.coordinator import run_case

            result = run_case(args.case, args.manifest_sha256, predecessor=args.predecessor)
            print(json.dumps(result, sort_keys=True))
            return 0 if result["status"] == "PASS" else 1
        elif args.command == "matrix":
            return _matrix(args.manifest_sha256)
        elif args.command == "collect":
            _collect(args.session, args.output)
        else:
            from scripts.unification.native_s1.roles import child

            host.host_release()
            host.require(host.INSTALL.samefile(Path(os.path.abspath(sys.argv[0])))
                         and sys.flags.isolated and sys.flags.no_site, "NATIVE_S1_INSTALLED_LAUNCHER")
            return child(args.name, args.control, args.ready, args.completion)
    except (OSError, ValueError, KeyError) as error:
        message = str(error)
        blocked = message.startswith("BLOCKED_HOST:") or message == "UBUNTU_24_04_NOBLE"
        print(json.dumps({"status": "BLOCKED_HOST" if blocked else "FAIL", "reason": message}))
        return 2 if blocked else 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
