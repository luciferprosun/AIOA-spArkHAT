# Source conflicts and semantic decisions

Frozen comparison base: `2be99da7aa07f7eb5faa9459fe8a78c5d0b6653a`.
All 76 remote heads, 22 canonical local heads, 39 PR heads, tags and imported local refs are enumerated in the CSV inventories. There are 320 source refs and 177 distinct object tips; annotated tags are not extra features. Forty remote heads are ancestors of main; 36 are not. The 35 tags are ancestors of fetched remote heads after peeling. PRs 19, 22, 44 and 45 have tips outside main; a merged PR does not imply its exact tip is an ancestor.

Genealogy coverage is complete for discovered refs. Semantic review covers feature slices and relevant call paths, **not every inherited file or every intermediate historical tree**. Corpora and sensitive/untracked noncode directories are not content/provenance-certified. No branch is approved for deletion by this report.

Inventory counts describe the frozen source snapshot before this integration branch and PR. `owner-private:aioa-all-local-sources.bundle#<ref>` evidence locators refer to the independently verified private bundle, not a public GitHub URL. Local-only history was not published simply to make a link. Tag `head_sha` preserves the exact backed-up object; a public commit evidence link uses its peeled commit.

Test names on `SOURCE_VALIDATED`/`DISCOVERED` feature rows identify tests in the declared historical source tree. They are not claims that those tests exist or pass in the current candidate. Current qualification is recorded separately in `test_status` and TEST_RESULTS.md.

## Canonical choices

| Overlap | Selected boundary | Rejected whole-stack import |
| --- | --- | --- |
| Native versus legacy/prototype runtime | Existing NativeMobileComposition, CoreAdmission, TransactionRunner, CoreWarrantLedger, host signer and existing SQLite | Legacy AgentRuntime/WorkspaceStore/provider lifecycles as another production Core |
| Approval DTOs and R3 manifests | Core-admitted principals, exact effect warrants, ServiceGuard | Fixture approval structures, R3 metadata or model text as authority |
| Memory stores and HAT tags | MemoryPatch/NativeLearning borrowing current Core persistence | Historical SQLiteTagStore, help queue, knowledge.sqlite3 and duplicate audit ledgers |
| CPL/review variants | Current CriticalPromptLoopService 1+3+1 and existing provider gates | Desktop composer, Orchestra LIVE provider/configuration stack and its separate sessions |
| Local Git versus remote Git | Distinct typed effects, existing local publish contract and PR45 create-only route | Treating a local commit, issue proposal or mail ACK as a remotely verified code commit |
| Pairing and UI variants | Current mobile_gateway and White Hole Mission Control | Companion enrollment gateway, frontend-v2 server or read-only mission listener as another app |

## Remote source families outside main

The following are **selective source decisions**, not blanket deletion classifications. The 29 older RHCSA/CPT/Orchestra/R3/demo/M2/repair/NZ/inert-NVIDIA heads share merge base `d7e3448afa4e33d58be8babbfcc615b13dff533f`. Gmail, Nemotron48 and PR22 share `81656e6ccbb0c02307d049e865b6df3225ddb578`. PR44/45 share current main. Funding uses `d26266e54ee940d7ada30aa02783dc697618a72c`; Product Hunt/PR19 uses `c01efad814277865babdf258ac821ce5d5a2f3d3`.

| Source SHA | Unique/overlapping slice | Decision and runtime gap |
| --- | --- | --- |
| 090d471186f5505cb2d01be9df1d11b9851857a8 | Gmail MIME/wire/PKCE contracts | Port six pure files and isolated tests. CoreMailEffectGate is an unimplemented Protocol; historical outbox uses another SQLite store. No account connection, token exchange, send or delivery claim. |
| 5d7669733813f0545ef62abd5b1bee631ee3f3d8 | RHCSA grammar; Memory Hats | Port grammar/CLI and fixed pattern file; no permission inference. Historical tag storage is not imported. Large command corpora remain unreviewed. |
| 33dfeb52263a50e23aa7edabdaab1fc47e60c9b9 | Provider-neutral knowledge context and citation validation | Retain requirements; adapt to native retrieval bundles. Its provider stack and external German-law subprocess adapter are not canonical. |
| bedef3dec3ea0f4ba3b3c8356f5c62ecea2b0bec | Generic HAT attachment and direct law-corpus reader | Prefer this pinned `mode=ro&immutable=1` data adapter over subprocess execution; external corpus identity, availability and rights remain unverified. Do not import desktop lifecycle. |
| 9d29ec5d8a6ac59914da9eaddb52fc5a0f850f28 / 8f9b14b7ea0f7d5a963244c62d27d3f3dcbeb26c | CPT deterministic prompt preview | Optional pure transformation; overlaps review role, grants no execution. Requires an intentional native preview contract before port. |
| 89e1e0b17694c2f7465702f16cb4fc4f9087de21 / eda1449e6a63b6a41d8bc16409aa31a128176804 / 46695cde96d12a52e20bea82ebe2e1798b7451fd / 8e09457cf97669e5f7742a59adaf091ca705ca4f | Orchestra binding, revision and human comparison | Comparison/hash-binding cases are useful; old LIVE session/provider configuration is duplicate authority/lifecycle. Adapt presentation to canonical CPL evidence. |
| 5ec74f85256c260dadbc795143eb132b4119aab6 | Desktop critical review | Canonical `runtime/critical_loop/review.py` explicitly records the selective port; current original-contract/redaction tests preserve lineage. No desktop reimport. |
| 360e900b66396a19fc09cccf69641cc015691ad8 | Jury/knowledge demo | Overlaps native NachwG contracts and chat; provenance anchor alone does not certify all old files migrated. |
| 3dcd8f326053ed15706817413514371e040bb877 / 12ceb5a757a3b52f06323dccbd841750d641f75f | R3 exact binding/adapter metadata | Inert schemas; checked-in adapter registry is empty. Mine negative cases without a second approval API. |
| 45501e2cb0a44a119824dba1392a7eb15633cfd1 / afca2cd07c44b81f805d59f1054ac92347f36e7c | Old NZ startup/backup/release attestation | Unique operational requirements tied to retired persistence/recovery. Distinct from current native NonZero CloudOps; do not copy as a replacement. |
| bc895122dd203b55b8305e1020c0153a6cb90619 / 796d6811930907d78d611429269f928c2059f6ac | Inert NVIDIA foundation | Superseded by current bounded NVIDIA/Nebius provider ports. No additional runtime interface. |
| 224cdc3ee57c5f3a45599fe9614bcaf3557c7720 | Nemotron48 document discovery | Unique experiment with separate knowledge.sqlite3, provider and SMTP supervision. Preserve inert extraction cases; no claim of a live 48-hour run. |
| e19dd4082ed2e812f9662cfba5eebc620b195ea5 | JSONL event ledger | Do not add a second audit truth; retain integrity test ideas. |
| 399279bec01f5b596a840cb9a986138fe12f9a9e | Historical Bash permission classifier | RISK: static path calls `echo ok > local.txt` safe/not_required. Not used for authority; advisory corpus only. |
| 1f79ff6e630c5954d82d88076f76f86a1d0d8e57 / e27a4b1d0280675c23fe59eed248770875838276 | RED-1 legacy execution freezes | Current public execution boundary already denies unsupported effects. Never restore historical environment override. |
| 36089a24458fe1a55ffe4a172f5e4159b73d4c50 | Product Hunt/PR19 chain verifier | `scripts/verify_gold24_chain.py` byte-identical to main, blob `fad26ebbb5fdc39a3a095bd15abca15df0337cf2`. No runtime port. |
| 3a640703e3248476b9e5d3095e14fe28d8f74057 | PR22 receipt-report utility | Unique 35-line stdin counter, no tests/runtime binding. Optional tooling, not Core capability. |
| fbfa02919c064a5228f893d42755ed373122d3f3 | Funding/governance documents | No new runtime feature. |
| 16fcfeed477f92f2ec65bd235e0b1cd98f87e7fd / ff38e17a837b223a65cb095f832e1a103e573572 | PR44/45 | Integrated coherent chat plus unique remote adapter; see DECISION_LOG and tests. |

M2 cockpit/provider, auth-redaction repairs, workspace hermeticity and governance tips received tip-delta/dependency review. Their inherited hundreds of files are not exhaustively classified; retain PARTIAL/CODE_ONLY where no stronger evidence exists.

## Local-only preservation

Forty-five distinct local commit tips are outside fetched remote/tag/PR ancestry, with twelve maximal tips. Exact raw refs and per-source SHA are in REF_INVENTORY.csv and the independently restored bundle.

| Maximal local tip | Disposition |
| --- | --- |
| cd8b82a31bedf7a192b2346641fe2b4f49f3b552 | Unique knowledge staging/acquisition/factory/release and no-unmount metadata interlock; historical CoreRecovery/scheduler dependencies absent from current Native. Do not restore standalone FTS/help stores. |
| 0978ca0db55eb91df9e393b271ad44eab5265a60 | Five submission/evidence docs atop the preceding runtime family; no new executable tip feature. |
| 53c24fe86bca63da0a0b1223ee926c1794c2b80e | Older read-only mission UI/server; current product surface replaces its role, not proof every fixture is redundant. |
| c3968fd47c88392bc9880f0ed7f01404ce7a53df | Prototype observer/task/report contracts; library/insights mostly thin wrappers. Separate WorkspaceStore/free-provider server and fixture Muse echo are not imported. Current migration ledger explicitly deferred many files. |
| af6488c7641bc2c02dbea891c7dcce3d81ff61ae | Companion EXP72/recovery, unrelated history; missing production OriginalCoreAdapter. No qualified 72-hour run. |
| cddbaff8a88dd5f2195a005d0dc88dba079114f8 | Diagnostic storage/journal/mount observation candidates, unrelated gateway/history; kernel/receipt adaptation required. |
| 3f43b0512b498601f72bed25989756e6d7fce838 | Older foreground pairing; current mobile_gateway remains canonical. |
| fb8642f108aea7db5db7a0b1446d4145f4167991 | Android Agent Lab explicitly non-Core; independent authority/SQLite claims are unsuitable direct imports. |
| 12dd3a73c7af1046be4afb9a243e307443ac3f11 | Android presentation overlap; historical manifest records UNKNOWN_NO_LICENSE_FILE_FOUND. Keep neutral compatible native implementation. |
| d01f70bd0cd9c9a4cce80943c7ce7b9ce2757cc2 | Parallel Nebius advisory constructs direct LIVE providers and its own key reference; must use existing admission/governors before any port. |
| da78ddc69e5bd7a993a14ca7bed324e970ced2d3 | Later W7A repair loop, Codex JSONL worker, capsule and Docker/backend machinery genuinely postdate frozen CloudOps import. Keep; adapt contracts to native warrants instead of importing its file effect store/GitHub authority. |
| 4277ebe5a89ecffb43a75f4cd64c829d670b59fa | Extensionless nvbuild/nvbuild-mcp developer tools; separate direct provider/auth path, not product runtime. |

Of 99 dirty/untracked code files inspected in local01 sources, 93 match reachable imported blobs. Six earlier variants in `nebius-nemotron-integration-20261028` do not: prototype `__main__.py`/`service.py`, providers `exact.py`, UI-v2 `server.py`, frontend-v2 `client.js`/`prototype.js`. Their exact bytes are in the private uncommitted-file archive. They are not safe to discard. Noncode/private-named files were not exhaustively inspected.
