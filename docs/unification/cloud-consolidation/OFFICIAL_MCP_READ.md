# Official GitHub MCP READ through Native Core

The private operator socket accepts one fixed read of the public
`luciferprosun/AIOA-spArkHAT` repository (ID 1247349659). Core admits the OS
owner, checks the configured profile, source and TLS, signs the reviewed
permit and records a pending request before starting the child. A timeout,
crash or lost response leaves the original request available through
`tool_readback`. There is no automatic dispatch from recovery.

## Reviewed server and target

Use the Linux x86-64 artifact from the [official v1.0.5 release](https://github.com/github/github-mcp-server/releases/tag/v1.0.5).
The annotated tag is `1d17d33bf5fa4e22b84e5ff28ad7c87f9b3575b3` and its source
commit is `c471ae94bb04059dc26e12c305e219c8fd4299e4`. Asset 423381432
(`github-mcp-server_Linux_x86_64.tar.gz`, 7,268,454 bytes) has SHA-256
`201082f569a846eaefd4318f13bccb5d9227c2cec45037d1d292ee83111173c1`.
Its executable (21,864,632 bytes) has SHA-256
`e38247271e98ea3e0771db747523914b35e37787fa2c120ab6864ee6b4a2c87c`.
Core hashes the bytes copied into a write-sealed Linux memfd and executes that descriptor.

The client negotiates protocol `2025-06-18`, verifies the server name and
version, then compares the complete sorted tool descriptors with SHA-256
`243b05c2f6ed9a7c600e503c827bfeb12b2c59f700443acbe8cb405b08dfbccc`.
The server flags are `stdio --read-only --tools get_file_contents,search_repositories`.
The client denies a write locally, searches the exact repository and reads
`LICENSE` at commit `d2870f33bb740184f7c2a18a7ea8f90b070fbd64`.
The local Git object database must contain that commit and its tree
`569f5591b2be0ae34c81701a3a54ea46e018c411`. The remote file call binds
the commit URI, Git blob `00eb8a94bdcf22d647d94e23c9c6938ef93d5802`,
1,074 UTF-8 bytes and SHA-256
`a039f83d1d59d97624c355653e0eab74a45b867a091d3d10d12ac1183535e14c`.
The tree hash is verified locally. The source HEAD, tree and runtime capsule
of the executing Core are measured separately when preparing the permit.

## Existing owner profile

On the admitted Native host, review the exact fine-grained token by ID in
GitHub's token settings. Verify its repository selection, expiration and
permissions: this repository only, Contents read-only and Metadata read-only,
with no other grants. Keep the value private. The credential digest pins the
installed bytes. The scope field is an operator attestation. Neither field
independently measures the GitHub grants. A general GitHub CLI login cannot
establish those permissions.

Use the normal existing Native operator profile and its secured Unix socket.
Set shell variables below to the existing profile directory, the verified
official binary, an owner-private credential file and its reviewed numeric ID.

```sh
umask 077
install -d -m 0700 "$root/official-mcp-read"
install -m 0500 "$upstream_binary" "$root/official-mcp-read/github-mcp-server"
install -m 0600 "$private_token_file" "$root/official-mcp-read/read-token"
PYTHONPATH=.:runtime python -B scripts/unification/official_mcp_read.py prepare \
    --state-dir "$root" --credential-id "$credential_id"
```

Review the full permit and UTC epoch timestamps, the OS UID and owner scope,
source and target, signer identity, tool inventory, private proof destination,
credential ID, one-session budget (20 s, 262144 B total, 65536 B/frame,
32768 B receipt, up to five reads, two inventory pages, zero writes/retries).
The window is at most 30 minutes. Only the admitted owner may approve its
exact displayed digest. Keep the directory and artifacts throughout recovery.

```sh
PYTHONPATH=.:runtime python -B scripts/unification/official_mcp_read.py execute \
    --state-dir "$root" --approve-sha256 "$reviewed_digest"
```

The private directory contains the signed approval, bounded transcript and
signed result when each is available. The existing Core signs the receipt
which binds the hash of the data and transcript. GitHub does not sign it.
After an authorized cold restart of the same profile and renewed normal
operator admission, retrieve the original result without launching MCP.

```sh
PYTHONPATH=.:runtime python -B scripts/unification/official_mcp_read.py readback \
    --state-dir "$root"
```

A verified receipt and a distinct Core instance ID are required for cold
acceptance. Retain the 0700 directory and 0600 proof files privately. Publish
only bindings, counts, sanitized statuses and hashes. An uncertain request
retains its reservation. Preserve the failed attempt for operator review
before proposing any separately authorized follow-up.

## Offline evidence from the candidate preparation

The release binary ran in a disposable bubblewrap namespace with networking
unshared, no credentials, a synthetic inert token string and no mounted user
files. Initialize, initialized notification and inventory succeeded. There
were zero tool calls. Private capture hashes (including capture formatting):

| Offline record | Bytes | SHA-256 |
| --- | ---: | --- |
| Handshake | 3304 | `19661c0fefa7aa4552b4b8b4def8963628e38bdd945f820c052153be66915243` |
| Inventory | 4382 | `cc91b86b82336a06dff78a7b8660e94322b0842999ed6868c20b777f3a91975d` |

The host inspection found an existing profile and signer file, a dormant
operator socket path and no official read approval, window or dedicated
credential in the profile. LIVE A was NOT_RUN. A fixture successful read
and a process restart exercise the Core receipt path only. Reproduce the
focused tests offline:

```sh
PYTHONPATH=.:runtime:tests python -B -m unittest -v \
    test_native_official_mcp test_native_tools test_mcp_official_read_transcript \
    test_nz26_mcp_public_license test_mcp_bridge_contract
```
