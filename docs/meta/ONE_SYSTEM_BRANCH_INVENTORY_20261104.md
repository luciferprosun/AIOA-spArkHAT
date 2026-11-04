# One system — pre-merge branch/worktree inventory

Owner decision: one canonical repository `luciferprosun/AIOA-spArkHAT`, release target `main`, integration only through PR #40. This is a **pre-merge inventory**, not permission to delete anything and not a post-merge cleanup report.

Observed 2026-11-04T09:17:15.166996+00:00. Candidate source `7f75021d1cce566d96e3d2271ee99397af425c71`. Counts: 74 remote heads, 17 local heads, 14 worktrees. No additional repository or integration branch was created for this owner update.

All 17 local heads are ancestors of/equal to the candidate. Forty remote heads are in its history; 34 have unique history requiring selective review. The initial local audit could resolve only 40 remote HEAD objects. A subsequent read-only commit/history inspection resolved all 74; many historical source blobs still are unavailable in this partial clone. Object/ancestry availability is not implementation certification.

`IN_CANDIDATE` does not mean merged into `main`. `UNIQUE_REQUIRES_REVIEW` does not mean missing functionality: patch-equivalent code can already exist under another commit. No whole-branch migration is proposed.

## Remote heads

| Branch | Exact SHA | Classification |
|---|---|---|
| `AIOA-METAGuardiansSPARK` | `0741d37db0630233b4e7212f6f3af6320106c792` | IN_CANDIDATE |
| `archive/meta-before-metaguardiansspark-20261031` | `9ee80c635f6cb2fea13613152188220a2fa90564` | IN_CANDIDATE |
| `chatgpt/nebius-live-gate` | `a0ea11d815edf9bdb8e38b230212a42201f8d46c` | IN_CANDIDATE |
| `checkpoint/nvidia-24h-sprint-start-20260922T184843Z` | `e865f7c2af01c6079a8c0d67a23bebeec1fef907` | IN_CANDIDATE |
| `checkpoint/pre-nvidia-m2-repaired-20260805-1a` | `be162673ce3dafb5f2017844a19e876e2ede0373` | UNIQUE_REQUIRES_REVIEW |
| `checkpoint/step17-nvidia-inert-foundation-boundary-clean-certified-20260805-1a` | `796d6811930907d78d611429269f928c2059f6ac` | UNIQUE_REQUIRES_REVIEW |
| `codex/android-apk-contract-20261102` | `67520358f2fa86a228df16a8addac1e33db6d3cd` | IN_CANDIDATE |
| `codex/android-component-order-20261102` | `c1750d94282d9f0a9a25a66665c3e63c0ee60ef3` | IN_CANDIDATE |
| `codex/android-debug-profile-20261102` | `5fc475f4b4b7a68c3b618771fde724fd371ff2ef` | IN_CANDIDATE |
| `codex/android-g8-workflow-registration-20261101` | `93a0a5357f9c2b846a696fc2e092793c9db7cfa2` | IN_CANDIDATE |
| `codex/android-native-pairing-20261102` | `594ac2a159f40572b94a1683e21e40c98d64dd5b` | IN_CANDIDATE |
| `codex/android-pinned-jdk-repair-20261101` | `b9ee022336ac5ed3653db9aa64b196ce8577ff33` | IN_CANDIDATE |
| `codex/android-postmerge-apk-20261101` | `1a4e5f5e54aef7c2e25ef4759ca8f0c59e444482` | IN_CANDIDATE |
| `codex/android-sdk-version-probe-20261102` | `452ac41dc112e7dd11458bb7d90bbc3e4b7aaaa3` | IN_CANDIDATE |
| `codex/android-toolchain-mobile-20261031` | `17280c012561ecc59b1b6f7c65689d8e52506c69` | IN_CANDIDATE |
| `codex/cosmic-one-tap-20261102` | `66eca413f8923d81e4eb933f82c8672260dc3cf2` | IN_CANDIDATE |
| `codex/nebius-verified-delta-bridge` | `e24aa767135d4df366b14816bbb31335dd136f5c` | IN_CANDIDATE |
| `codex/nvidia-final-week-20260921` | `dddf04d66e5a1433133f9925202599006ac83700` | IN_CANDIDATE |
| `codex/w7a-verified-pr-agent24h-4dbfc58d3e0a455eaea4fa6692e4ff22` | `3a640703e3248476b9e5d3095e14fe28d8f74057` | UNIQUE_REQUIRES_REVIEW |
| `demo/knowledge-hat-bridge-german-law-v2-1a` | `bedef3dec3ea0f4ba3b3c8356f5c62ecea2b0bec` | UNIQUE_REQUIRES_REVIEW |
| `demo/openai-competition-desktop-1a` | `5ec74f85256c260dadbc795143eb132b4119aab6` | UNIQUE_REQUIRES_REVIEW |
| `dev/gt-runtime-5-single-event-ledger` | `e19dd4082ed2e812f9662cfba5eebc620b195ea5` | UNIQUE_REQUIRES_REVIEW |
| `dev/gt-runtime-8-bash-safety-planning` | `399279bec01f5b596a840cb9a986138fe12f9a9e` | UNIQUE_REQUIRES_REVIEW |
| `dev/rhcsa-command-grammar-layer` | `5d7669733813f0545ef62abd5b1bee631ee3f3d8` | UNIQUE_REQUIRES_REVIEW |
| `docs/nvidia-submission-pack-20260922` | `cf4e87b8d3ce6b0caad1979425c209365e938be5` | IN_CANDIDATE |
| `docs/product-hunt-postmerge-links-20261014` | `78105d3705cedba679ccb131b610bffdd6730a0b` | IN_CANDIDATE |
| `experiment/nemotron48-data-sniffer-20261027` | `224cdc3ee57c5f3a45599fe9614bcaf3557c7720` | UNIQUE_REQUIRES_REVIEW |
| `feat/cosmic-design-system-20261103` | `5fae31002031ab0eb0aa94b9e57e8f6fbb3b6e01` | IN_CANDIDATE |
| `feat/cosmic4-muse-chat-20261103` | `7f75021d1cce566d96e3d2271ee99397af425c71` | PR40_ONLY_INTEGRATION_PATH |
| `feat/cosmic4-usb-20261103` | `4c00d7bb35185eaba0e8a1a84418c49f39d21a84` | IN_CANDIDATE |
| `feature/agents-branch-governance-repair-1a` | `f62a8f713e21562f98301c52a0de6d5ad8ecbc54` | UNIQUE_REQUIRES_REVIEW |
| `feature/aioa-gmail-gateway` | `090d471186f5505cb2d01be9df1d11b9851857a8` | UNIQUE_REQUIRES_REVIEW |
| `feature/auth-identity-path-redaction-repair-1a` | `037373f8204533ccdead521df70b4a6f9886db2c` | UNIQUE_REQUIRES_REVIEW |
| `feature/cpt-a-phase-1` | `9d29ec5d8a6ac59914da9eaddb52fc5a0f850f28` | UNIQUE_REQUIRES_REVIEW |
| `feature/cpt-a1-b-hardening` | `8f9b14b7ea0f7d5a963244c62d27d3f3dcbeb26c` | UNIQUE_REQUIRES_REVIEW |
| `feature/cpt-a2-composer-transform` | `d1ceed5d98a3b6bb876748afe9e44704e595cf6f` | UNIQUE_REQUIRES_REVIEW |
| `feature/epistemic-orchestra-contracts-cpt-1a` | `89e1e0b17694c2f7465702f16cb4fc4f9087de21` | UNIQUE_REQUIRES_REVIEW |
| `feature/knowledge-provider-bridge-1a` | `33dfeb52263a50e23aa7edabdaab1fc47e60c9b9` | UNIQUE_REQUIRES_REVIEW |
| `feature/m2-auth-identity-path-redaction-repair-1a` | `8db3a228539492c44cbe8d7d4a3ae9aabd6b2749` | UNIQUE_REQUIRES_REVIEW |
| `feature/m2-b0-provider-critic-inert-core` | `7f61a3b167a028d7e34b852cca4ade809ceec571` | UNIQUE_REQUIRES_REVIEW |
| `feature/m2-workspace-containment-test-hermeticity-repair-1a` | `be162673ce3dafb5f2017844a19e876e2ede0373` | UNIQUE_REQUIRES_REVIEW |
| `feature/nvidia-correlation-secret-reflection-repair-1a` | `796d6811930907d78d611429269f928c2059f6ac` | UNIQUE_REQUIRES_REVIEW |
| `feature/nvidia-inert-integration-foundation-1a` | `bc895122dd203b55b8305e1020c0153a6cb90619` | UNIQUE_REQUIRES_REVIEW |
| `feature/orchestra-human-review-workspace-final-response-comparison-1a` | `8e09457cf97669e5f7742a59adaf091ca705ca4f` | UNIQUE_REQUIRES_REVIEW |
| `feature/orchestra-session-view-critic-audit-presentation-1a` | `46695cde96d12a52e20bea82ebe2e1798b7451fd` | UNIQUE_REQUIRES_REVIEW |
| `feature/orchestra-user-provider-connections-1a` | `eda1449e6a63b6a41d8bc16409aa31a128176804` | UNIQUE_REQUIRES_REVIEW |
| `feature/r3-1-canonical-authority-contracts-1a` | `3dcd8f326053ed15706817413514371e040bb877` | UNIQUE_REQUIRES_REVIEW |
| `feature/r3-2-adapter-manifest-registry-1a` | `12ceb5a757a3b52f06323dccbd841750d641f75f` | UNIQUE_REQUIRES_REVIEW |
| `feature/red1-e-shell-executor-freeze` | `1f79ff6e630c5954d82d88076f76f86a1d0d8e57` | UNIQUE_REQUIRES_REVIEW |
| `feature/red1-final-surface-reconciliation` | `e27a4b1d0280675c23fe59eed248770875838276` | UNIQUE_REQUIRES_REVIEW |
| `fix/canonical-aioa-sparkhat-name-20261009` | `8a89e63b910b0c7a353b55c08342eefff774a825` | IN_CANDIDATE |
| `fix/fresh-clone-web-wrapper-20260922` | `93b03e75cde5780e7ef9360de1771a9d03eebb4d` | IN_CANDIDATE |
| `fix/nonzero-public-response-privacy-v1` | `a448e510d3d48e8ac966fc89e3c7241e3940b52b` | IN_CANDIDATE |
| `fix/nv10-ci-child-path` | `6cdcba4a03f9e6560c44dd680d0db196bcf043bc` | IN_CANDIDATE |
| `funding/github-secure-oss-20261004` | `fbfa02919c064a5228f893d42755ed373122d3f3` | UNIQUE_REQUIRES_REVIEW |
| `integration/one-aioa-core-muse-mobile-20261101` | `ff9550fd88ea786273fc899bc3e9f8f2bccd0196` | IN_CANDIDATE |
| `integration/owner-approved-20261011` | `bb3cd0426dc5e7c0d9871fbf0a19c9accf1ab1d2` | IN_CANDIDATE |
| `launch/product-hunt-evidence-gates-20261013` | `36089a24458fe1a55ffe4a172f5e4159b73d4c50` | UNIQUE_REQUIRES_REVIEW |
| `main` | `bda9d3126150b7c44f94d923ed236e10de5dba59` | PROTECTED_MAIN |
| `nebius-final-candidate-20261009` | `cd1419f0062bb5ea5ca3da06254fce0daa1cd4d5` | IN_CANDIDATE |
| `nebius-personal-ai` | `944590c4837629d5fe3b5b193a7ec75364e99eec` | IN_CANDIDATE |
| `nvidia/reviewer-hardening-20260922` | `9f4edbeb8ca1fc844223f4af302a3b13320923a1` | IN_CANDIDATE |
| `nvidia/use-case-dashboard-20260922` | `c624285dc939c544e424da299a09a1b996c5088a` | IN_CANDIDATE |
| `nz/p2-production-readiness` | `45501e2cb0a44a119824dba1392a7eb15633cfd1` | UNIQUE_REQUIRES_REVIEW |
| `recovery/nz-green-baseline-2026-08-22` | `afca2cd07c44b81f805d59f1054ac92347f36e7c` | UNIQUE_REQUIRES_REVIEW |
| `release/hackathon-jury-final` | `360e900b66396a19fc09cccf69641cc015691ad8` | UNIQUE_REQUIRES_REVIEW |
| `repair/c11-installed-core-packaging-v1` | `48fbfc4d8dfa486c79de0bc79a8c41230241d97b` | IN_CANDIDATE |
| `snapshot/prototype-fund-20261009-main` | `d26266e54ee940d7ada30aa02783dc697618a72c` | IN_CANDIDATE |
| `snapshot/prototype-fund-20261009-nebius` | `944590c4837629d5fe3b5b193a7ec75364e99eec` | IN_CANDIDATE |
| `sol/nvidia-final-integration-20260923` | `d9a839041f9fff3e5cc3618f21dd2ad6d3e6bd8a` | IN_CANDIDATE |
| `sol/nvidia-publication-closure-20260923` | `e256b81a2ef00acbf186f0fe48de43a651bf0146` | IN_CANDIDATE |
| `sol/nvidia-reviewer-skill-20260922` | `074d76b0aafb9487ba33c6404efcbd6aa0e312de` | IN_CANDIDATE |
| `submission/nlnet-safe-d7e3448` | `d7e3448afa4e33d58be8babbfcc615b13dff533f` | IN_CANDIDATE |
| `unification/sparkhub-20261009` | `bf22bc55e5c4197da49bb4452a3fb82af1024c92` | IN_CANDIDATE |

## Local heads

| Branch | Exact SHA | Relation |
|---|---|---|
| `codex/android-apk-contract-20261102` | `2e112d29ad7f3c64f4bd8ac9979bf31a6f81901d` | IN_CANDIDATE |
| `codex/android-component-order-20261102` | `c1750d94282d9f0a9a25a66665c3e63c0ee60ef3` | IN_CANDIDATE |
| `codex/android-debug-profile-20261102` | `5fc475f4b4b7a68c3b618771fde724fd371ff2ef` | IN_CANDIDATE |
| `codex/android-g8-workflow-registration-20261101` | `93a0a5357f9c2b846a696fc2e092793c9db7cfa2` | IN_CANDIDATE |
| `codex/android-native-pairing-20261102` | `f71fb33da8e3632bfd5e5276194c7921247ed16b` | IN_CANDIDATE |
| `codex/android-pinned-jdk-repair-20261101` | `b9ee022336ac5ed3653db9aa64b196ce8577ff33` | IN_CANDIDATE |
| `codex/android-postmerge-apk-20261101` | `1a4e5f5e54aef7c2e25ef4759ca8f0c59e444482` | IN_CANDIDATE |
| `codex/android-sdk-version-probe-20261102` | `452ac41dc112e7dd11458bb7d90bbc3e4b7aaaa3` | IN_CANDIDATE |
| `codex/cosmic-one-tap-20261102` | `bda9d3126150b7c44f94d923ed236e10de5dba59` | IN_CANDIDATE |
| `feat/cosmic-design-system-20261103` | `5fae31002031ab0eb0aa94b9e57e8f6fbb3b6e01` | IN_CANDIDATE |
| `feat/cosmic4-muse-chat-20261103` | `613737fc2b012594525e51664b24593f040e7a4a` | IN_CANDIDATE |
| `feat/cosmic4-usb-20261103` | `4c00d7bb35185eaba0e8a1a84418c49f39d21a84` | IN_CANDIDATE |
| `feat/ultra-one-system-20261104` | `7f75021d1cce566d96e3d2271ee99397af425c71` | IN_CANDIDATE |
| `fix/cosmic-mobile-http-close-20261103` | `11b1505730da3759f0e00091157416005ff196a0` | IN_CANDIDATE |
| `fix/cosmic-pairing-errors-20261103` | `df1a13ece15f94cf19357f437dd54a73170087c0` | IN_CANDIDATE |
| `integration/one-aioa-core-muse-mobile-20261101` | `ff9550fd88ea786273fc899bc3e9f8f2bccd0196` | IN_CANDIDATE |
| `main` | `81656e6ccbb0c02307d049e865b6df3225ddb578` | IN_CANDIDATE |

## Worktrees

| Existing workspace | HEAD | Preserved status |
|---|---|---|
| `android-g8-workflow-registration-20261101` | `93a0a5357f9c2b846a696fc2e092793c9db7cfa2` | CLEAN |
| `android-postmerge-apk-20261101` | `f71fb33da8e3632bfd5e5276194c7921247ed16b` | `?? docs/meta/ANDROID_LINUX_PAIRING_FINAL_20261102.md`<br>`?? docs/meta/MOBILE_MUSE_E2E_CHECKPOINT_20261102.md` |
| `cosmic-one-tap-20261102` | `11b1505730da3759f0e00091157416005ff196a0` | CLEAN |
| `cosmic-pairing-diagnostics-20261103` | `5fae31002031ab0eb0aa94b9e57e8f6fbb3b6e01` | `?? .superpowers/sdd/2026-11-03-pairing-diagnostics/review.md`<br>`?? CODEX_COSMIC_FINAL_IMPLEMENTATION.md` |
| `cosmic4-muse-chat-20261103` | `613737fc2b012594525e51664b24593f040e7a4a` | CLEAN |
| `cosmic4-muse-native-20261103` | `0b3f48ef0842833e17cf6bb79e8b72d44e7e7eee` | CLEAN |
| `cosmic4-muse-native-english-20261104` | `9c385dcf16b87eeeaf942febe52a9def3450a855` | CLEAN |
| `cosmic4-muse-native-english-fixed-20261104` | `b7f4002b2a945a52e8ae08b66fc6b4ceeb418f54` | CLEAN |
| `cosmic4-usb-20261103` | `4c00d7bb35185eaba0e8a1a84418c49f39d21a84` | CLEAN |
| `one-aioa-core-muse-mobile-20261101` | `ff9550fd88ea786273fc899bc3e9f8f2bccd0196` | CLEAN |
| `one-aioa-main-verified-20261101` | `ad5ae30494b9844e0433ffb1712254b781b3fa77` | CLEAN |
| `ultra-native-9e7dd3f-20261104` | `9e7dd3f1ea7f03a61b7aac9e67e93f605b74e7e1` | CLEAN |
| `ultra-one-system-20261104` | `7f75021d1cce566d96e3d2271ee99397af425c71` | CLEAN |
| `frozen-source` | `f490132bdb15cd6664e01497ee0b62f1e6582d59` | CLEAN |

## Cleanup gate

Protect `main`, the current PR40 path, active Native9e7, rollbackB7, Android delivery/frozen sources, and every dirty workspace. A clean worktree can still be required by a running process or rollback. Preserve the two operator workspaces with untracked files. No branch is declared safe to delete in this phase.

After explicit owner-approved PR40 merge: re-enumerate actual remote/local refs and worktrees against the resulting main SHA, verify branch protection and active process cwd/source, retain every unique/unverified commit and every untracked file, then produce the requested post-merge cleanup report. Only a separately reviewed cleanup proposal may follow. No force-push, deletion, reset or clean is part of this report.
