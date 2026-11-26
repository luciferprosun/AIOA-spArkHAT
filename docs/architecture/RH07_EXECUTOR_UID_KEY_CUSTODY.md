# RH-07 executor and key custody

## Implemented contract

The new signer loader checks three distinct positive role UIDs and the actual
broker's real/effective/saved IDs and supplementary groups. It requires
NoNewPrivs, zero usable capabilities, and a non-dumpable process. It loads a
bounded P-256 key from a supervisor-issued, non-inheritable, read-only regular
FD owned by that broker UID at mode 0400. It validates the pinned public
enrollment, key epoch, validity and revocation before use. Checks compare
stable stat fields and tolerate atime changes caused by the read. A missing,
writable, inherited-on-exec, wrong-mode, or mismatched role/key FD cannot
enable the loader. The consumer should close the FD immediately after loading
and should not fork with it or the in-memory key.

The checked loader is a startup component. The RH-07 fixture has no trusted
supervisor provisioning privileges. The fixture broker uses a synthetic
signer and explicitly refuses a Core UID different from the broker UID,
because that path has no installed OS confinement. The role-separated
sequencer protocol can authenticate distinct registered UIDs, but the
qualified positive cross-UID publication path is still gated.

## Required Noble supervisor

The trusted supervisor must pin the service binaries, namespaces, enrolled
UID/GID and actual child lifetimes, then hand an allowlisted FD to the broker
only. Use a private signer path or a dedicated key service that exposes no
private bytes to Core. Configure dumpability and close all unrelated FDs
after the final exec and identity transition. Linux SO_PEERCRED is measured
when connecting. Provide private socket parents, endpoint custody, and
supervisor-controlled process lifetime or pidfd validation alongside it.
CLOEXEC is insufficient across fork. The sequencer state mount and directory
must be inaccessible for writes by both Core and broker. An untrusted client
can consume CPU or connections, so admission bounds are availability controls,
not proof of prompt STOP.

The broker currently holds a writable parent FD for a single authorized
loose ref. That FD is not restricted to one leaf by the kernel. The supervisor
must prevent writes to sibling names, other repository paths, and any
ref-parent ancestor, including rename into/out of scope. Use an independently
reviewed kernel policy or narrowly scoped trusted link executor only after
the exact positive and negative probes pass. openat2 and the post-IPC
physical recheck do not serialize the last pathname check with link.
The current private repository/evidence directories are 0700. A separate
verifier needs a reviewed read-only observation aperture, plus a protected
key and authenticated reply path. Giving it a writable repository descriptor
or a signer FD would defeat that division.

Never report key secrecy or OS exact-ref confinement as proved by peers with
one UID. The activation guard is external to this candidate and must remain
closed until that proof and owner approval exist.
