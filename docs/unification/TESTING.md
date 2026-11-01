# Offline verification

Portable contracts and the existing project regressions:

```bash
PYTHONPATH=.:tests PYTHONDONTWRITEBYTECODE=1 python3 -B -m unittest discover -s tests -p 'test*.py'
node --test tests/*.test.cjs
```

Actual namespace/cgroup/worker acceptance is a separate explicit command on a
qualified Linux host. It requires the installed pinned Git v3 binary, Python3.12,
bubblewrap, C compiler, delegated user cgroups, seccomp and user namespaces.
It installs none of them. It is intentionally outside generic `test*.py`
discovery, so hosted unit CI does not attempt unqualified native effects or
silently skip an unqualified host as a successful native certification.

```bash
PYTHONPATH=.:tests PYTHONDONTWRITEBYTECODE=1 python3 -B -m unittest discover -s tests -p 'host_unified_*.py'
```

Reproduce the signed Android-like fixture, exact local approvals, real workspace
files and five Python checks, independently verified local Git commit, remote
denial and readback after an actual app process restart:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -B -m scripts.unification.offline_demo --evidence-dir /absolute/fresh/private/qa-directory
```

The evidence directory must be fresh. It is retained, not overwritten. The
harness uses the existing app composition and documented webapp command; it is
not another product server. Generated fixture transport keys remain private.
Its report contains no token, enrollment code or private key.

Python Android source checks and signed fixtures do not compile Kotlin/JVM or
produce an APK. JDK/SDK, Gradle downloads/licenses, hosted Android Actions,
physical phone/TLS and any LIVE model/GitHub effect require separate gates.
No tests authorize retrying an UNKNOWN effect. Use independent readback instead.
