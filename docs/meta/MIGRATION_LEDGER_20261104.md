# Migration ledger — 4 November 2026

One canonical repository. No wholesale merge, duplicate Core, database or runtime.

| Source | Ref / provenance | Decision | Canonical reuse / limitation |
|---|---|---|---|
| Cosmic4 Muse feature |613737fc2b012594525e51664b24593f040e7a4a, MIT|ALREADY_PRESENT|Existing Native composition, same SQLite runner, approvals, chat and device UI|
| Known-good running Native |b7f4002b2a945a52e8ae08b66fc6b4ceeb418f54, MIT|REFERENCE_ONLY|Immutable rollback source; same state root, keys and identity|
| Core authority/governor/journal |canonical runtime/core_admission.py and runtime/mission/, journal last change0399a787d7179d8df66f35ceb80c1c11a1eb2c99|ALREADY_PRESENT|Retain owner-wide UNKNOWN barrier and exact warrants|
| MCP READ and fixture agent |dc57ed18146586f8de6dd9a6b089f6280c10d9ea, MIT|ALREADY_PRESENT|Reuse strict payload validation; do not promote MOCK/fixture execution|
| MCP GitHub issue codec |8015728694b9afd114fa71324a4ac4c6976e4533, MIT|ALREADY_PRESENT|Codec only; not live transport|
| External GitHub agent worktree |6e9dd8ebc1dcb2c03345d9dc7d30895013751cd5; adapter files UNTRACKED|REFERENCE_ONLY|No port: no verified live executor. contracts SHA25666e8d8ca91cf36e6b50ae3dc0bf090b6cae6ae5f90cfda639a172ad4976580c2; adapter SHA256050a5f9f2df003b454ce0de413110a08a75f67d275d51812ee97b84ddb37c4d1|
| Legacy CPL |canonical runtime/critical_loop and mission/lite_cpl.py|ALREADY_PRESENT|Contract preview only. Native Meta provider/group budget binding absent|
| Nebius/Nemotron CLI and integration |historical external worktrees|FUTURE|No modification, no new inference, no import of state or credentials|
| Memory Patch / Cockroach / NonZero |existing canonical runtime packages and their provenance files|ALREADY_PRESENT|No schema/backend migration; production claims remain separately qualified|
| Cosmic fonts |google/fonts2fe1e8c6b137fb13041a7cfca6fdcd8a910ea4dc, bundledOFL1.1|ALREADY_PRESENT|Three local font SHA256 values verified against COSMIC_FONT_PROVENANCE.json|
| Android installed401 / delivered402 |existing cosmic4 package and preserved signer|ALREADY_PRESENT|No APK or Android source change in this Linux integration|

New glue, if tests qualify it, stays inside existing `runtime/mcp_bridge`, `runtime/meta_hackathon` and web assets. No external repository is deleted, archived, renamed or automatically merged. Read-only audit agents made no changes. Tests and release receipts will be added to the integration report; historical tests do not qualify new files.
