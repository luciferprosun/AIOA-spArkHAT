# Native #69 disposable CAS broker

RH-01 and RH-02 are local prototypes based on PR #69 commit
`8bf94361e8d0fdeabc25007b4faeefd33cc0cf8a` and tree
`4b0c991a90c9b86712a04266d8acb73de8f91f46`.

## Authority and transport

The launcher supplies a trusted fixture record representing an approved Core
START and its held reservation. Each broker accepts one bounded canonical JSON
frame on an authenticated Unix stream. A fixed length prefix and a write
half-close delimit the request. The receiver compares the kernel PID, UID and
GID with a pinned peer and compares every request field with the trusted
record. The permit digest binds the fields but conveys no authority by itself.
Epoch and validity checks precede an attempt. Executor enrollment contains only
the P-256 public identity, key epoch, validity interval and revocation state.

The private technical state directory holds a create-only permit record. It
fences the scoped operation, attempt ID and nonce as soon as it persists.
An additional consumed marker records progress. Either a completed permit
or a permit that survived a crash bars re-execution. The records confer no
authorization. Core remains the sole owner of intent, warrant, governor,
transaction, AUDIT and OUTBOX state.

## STOP and the commit permit

The proposal is `REQUIRES_OWNER_SECURITY_APPROVAL`. The prototype proposes
a synthetic permit followed by a second release check. STOP and release use
independent opens of the same protected lock inode. STOP that obtains the lock
first persists a durable stop marker and prevents CAS. Even after the permit
is durable, STOP can win before final release. The broker holds the lock
from final release through the exclusive ref link and ref-directory sync.

The exclusive link that creates the previously absent ref is the irreversible
operation. STOP may wait behind a broker that has acquired the final release
lock. It therefore has different ordering from the existing in-process
pre-link cancellation check. Permit expiry is sampled at release; scheduling
between the sample and the link can cross the wall-clock deadline. Production
integration requires agreement on both semantics and a mechanism for binding
this ordering to the actual Core journal. A duplicated OFD-lock descriptor
would share lock ownership. An alternative using independent OFD-lock opens
would still need separate proof of mutual exclusion, journal ordering and
crash release.
