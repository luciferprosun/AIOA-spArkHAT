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

The broker's outer operation ceiling remains 20 seconds. The renderer must
pass actual broker startup, oracle, negative-observation and active STOP tests;
mock CDP responses and prepared unit tests do not certify Chrome execution.
Default profile resource limits and network denial remain unchanged.

The explicit renderer profile has a finite 4 TiB virtual address-space limit
for Chrome/V8 reservations. This is distinct from committed physical memory:
`MemoryMax` remains 512 MiB and `MemorySwapMax` remains zero. The default
profile retains its original 512 MiB address-space limit. A model cannot supply
an address-space parameter. Real renderer startup and 600 MiB physical-memory
denial must be demonstrated before qualification; the larger virtual allowance
alone does not certify browser execution.

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
