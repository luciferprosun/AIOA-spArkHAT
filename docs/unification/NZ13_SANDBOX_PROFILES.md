# Supported sandbox profiles

Recipes are operator-pinned inert inputs. A model proposes file changes; it
cannot choose commands, dependencies, resource limits, network policy or target
authority. Every operation uses the existing Core journal, warrant ledger and
Linux sandbox broker. A guest PASS string has no authority.

| Profile | Supported behavior | Fixed limits and restrictions |
| --- | --- | --- |
| `RESTRICTED_AST_JSON_V2` | The existing restricted AST and JSON function tests | Existing default policy, 512 MiB, 16 processes, network OFF |
| `ISOLATED_PYTHON_FUNCTIONS_V1` | Normal Python functions, imports and loops in a separate confined child; JSON arguments and host oracles | Mandatory Landlock ABI 6 or later; one-second child deadline, bounded output, read-only source/dependencies, private writable temporary files, no parent descriptors, sockets or signals to parent |
| Closed pure-Python wheel lock | Up to three operator-pinned wheel archives installed inside the sandbox | SHA-256 and RECORD validation; bounded files and expansion; no native extensions, dependency acquisition, startup hooks or install scripts; host never imports package code |
| `HEADLESS_RENDER_V1` | Fixed HTML/CSS/JS bundle, offline Chrome over CDP pipe, independent DOM/console/PNG oracles | Explicit opt-in; at most 64 processes, 512 MiB physical memory, swap disabled, network OFF, fresh profile and fixed viewport; no public CDP listener |
| `HEADLESS_RENDER_V2` | The same closed rendering flow with finite descriptor capacity for the fixed browser | Exactly 256 soft/hard open-file limit; V1/default retain 64; physical memory, swap, process, time, tmpfs, output and network bounds unchanged |

The broker's outer operation ceiling remains 20 seconds. The renderer must
pass actual broker startup, oracle, negative-observation and active STOP tests;
mock CDP responses and prepared unit tests do not certify Chrome execution.
Default profile resource limits and network denial remain unchanged.

Fixed HTML preparation selects V2. The closed version marker and pinned profile
digest select the limit; candidate input cannot supply a descriptor integer.
The broker reads `/proc/<trusted-bootstrap>/limits` through its already pinned
proc directory and checks its live pidfd before and after that bounded read,
before the existing final release check and ACK. Both soft and hard limits must
match exactly and are recorded in the same broker receipt. Missing, duplicate,
unlimited, malformed or mismatched evidence prevents execution. More private
file descriptors do not add host-socket or owner authority; existing IPC BPF
bytes and its specific descriptor checks remain unchanged. Actual EMFILE,
hard-limit raising refusal, cleanup and browser acceptance are separate gates.

The explicit renderer profile has a finite 4 TiB virtual address-space limit
for Chrome/V8 reservations. This is distinct from committed physical memory:
`MemoryMax` remains 512 MiB and `MemorySwapMax` remains zero. The default
profile retains its original 512 MiB address-space limit. A model cannot supply
an address-space parameter. Real renderer startup and 600 MiB physical-memory
denial must be demonstrated before qualification; the larger virtual allowance
alone does not certify browser execution.

The existing `RENDER_UNIX_SOCKETPAIR_V1` IPC policy permits fresh Unix
stream/seqpacket pairs and the single
`SOL_SOCKET/SO_PASSCRED` option with a four-byte setter value and a getter for
that same flag. The filter bounds descriptor and option arguments; it cannot
prove descriptor provenance or inspect pointed values/lengths. Getter output
and length are guest pointers validated by the kernel. Isolation also requires bootstrap to close every
inherited descriptor above stderr and provide only DEVNULL/bounded pipes at
stdin/stdout/stderr. Unix abstract auto-binding remains inside the job's
private network namespace. Socket creation, connect, bind, listen, other
getsockopt options, other socket options and INET access remain denied.
IPC credential flags never grant Core owner authority.

The separate operator-selected `RENDER_UNIX_LISTENER_V1` policy retains all
pair-policy decisions and additionally permits Chrome's ProcessSingleton to
create an `AF_UNIX/SOCK_STREAM` socket with protocol zero and only known
CLOEXEC/NONBLOCK flags, bind a guest sockaddr of 2 through 110 bytes, and listen
with the observed backlog of five. Bind/listen descriptor arguments remain
below 64; integer high bits are checked. Address pointers remain opaque.
Connect, accept, INET creation, peer queries, ptrace and host-FD import stay
denied. This is private browser housekeeping, not a remote access interface.

Pathname Unix sockets require the job's private mount namespace as well as
its private network namespace. No host service may connect to job-created
sockets. The manifest exposes no host service or writable host directories;
the handoff connection is closed before untrusted execution. The new profile
alone selects the trusted bootstrap compilation flag
`-DAIOA_RENDER_LISTENER=1`; the default remains zero. Bootstrap proves that a
fresh Unix stream still cannot connect to `/control`, that INET creation is
denied, and that all descriptors above stderr are closed. Compiled bootstrap
and filter hashes are bound into the profile and warrant. The existing pair,
default and setup filter bytes are unchanged. A model cannot select this IPC
policy through recipe input or worker arguments.

The renderer may half-close its own private pair with `SHUT_RD` or `SHUT_WR`.
Descriptor and mode high bits are checked, the descriptor stays below 64, and
`SHUT_RDWR` remains denied. This closes existing job IPC; it cannot create a
connection, import a descriptor or grant authority. Default profiles retain
their original shutdown denial.

Function validation uses an independently supplied expected result. Child
exceptions, malformed output, timeout, lost acknowledgement or unverifiable
cleanup never become success. Signed validation requires a canonical Applied
receipt and source/profile binding. A retained acknowledgement is read back
without replaying execution.

These profiles do not provide arbitrary shell access, online pip/uv/npm
installation, a persistent application server, general Node project execution
or the historical HTTP startup contract. Those capabilities need separate
reviewed contracts and acceptance evidence. Real model certification,
production Native binding and remote GitHub writes remain separate gates.

Actual acceptance fixtures are `nz13_function_acceptance.py`,
`nz13_function_confinement_acceptance.py` and `nz13_render_acceptance.py` in
`tests/`. They use disposable local state and the same Core/broker/Git flow;
they do not use provider credentials, production state or remote compute.
