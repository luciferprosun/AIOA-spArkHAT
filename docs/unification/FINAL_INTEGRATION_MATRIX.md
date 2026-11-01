# ONE AIOA — macierz integracji

FAKTY: implementacja należy do `luciferprosun/AIOA-spArkHAT`, gałąź
`integration/one-aioa-core-muse-mobile-20261101`. Docelowym źródłem produktu
pozostaje `main`, po osobnym zatwierdzeniu konkretnego PR i SHA. Ten dokument
nie nadaje uprawnień wykonawczych ani nie potwierdza scalenia.

## Tożsamość źródeł

| ID | Repo / branch / pełny commit | Licencja i granica importu |
|---|---|---|
| S0 | AIOA `main`, `de6fddb236db1702879fc65838c0c94b53d24cb2` | MIT AIOA; istniejące Memory Patch/NonZero notices zachowane; zawiera jednoplikowy G8 PR26 |
| S1 | `/home/l/projects/AIOA-spArkHAT-META`, `AIOA-METAGuardiansSPARK`, `6216b16f22da167b401f8611291264d73eaacb40` | MIT AIOA; P01/P02/P03 i N1, rzeczywista historia commitów zachowana |
| S2 | `/home/l/AIOA_LOCAL_WORKTREES/android-toolchain-mobile-20261031`, `codex/android-toolchain-mobile-20261031`, `17280c012561ecc59b1b6f7c65689d8e52506c69` | MIT AIOA + dołączona licencja Apache Gradle wrapper; zawiera S1; źródło PR25 |
| S3 | `/home/l/AIOA_LOCAL_WORKTREES/nebius-nemotron-integration-20261028`, `feature/nebius-nemotron-integration-20261028`, `6e9dd8ebc1dcb2c03345d9dc7d30895013751cd5` + manifest bajtów dirty source | MIT AIOA; 24 modified / 199 untracked zachowane. Sam HEAD nie poświadcza untracked publishera. 185 publicznych plików przypięto SHA-256, bez sekretów/stanu |
| S4 | `/home/l/AIOA_LOCAL_WORKTREES/aioa-github-agent-20261028`, `feature/aioa-github-agent-20261028`, `6e9dd8ebc1dcb2c03345d9dc7d30895013751cd5` | MIT AIOA; odczyt referencyjny; nie skopiowano drugiego klienta/authority |
| S5 | Android AgentLab `fb8642f108aea7db5db7a0b1446d4145f4167991` i stary Companion `540f736ce6801c88d66586e19afc310ecbfd0897` | Licencja nieustalona: REFERENCE_ONLY, bez kopiowania kodu |

Merge-base S0/S2: `81656e6ccbb0c02307d049e865b6df3225ddb578`.
S0 dołączono lokalnym merge `3fc9233dca2cc851a52831e862cd806ef7269947`.
Pełny rejestr katalogów, remote i dirty: [U0_SOURCE_LEDGER.md](U0_SOURCE_LEDGER.md).

## Komponenty i rzeczywista gotowość

`IMPLEMENTED_AND_VERIFIED` poniżej oznacza zakres lokalnego profilu offline
i dowodów z [U9_QA_EVIDENCE.md](U9_QA_EVIDENCE.md), a nie certyfikat produkcyjny.

| Komponent / źródło | Kanoniczna implementacja i interfejs | Stan zaimplementowanego zakresu | Niezamknięta granica |
|---|---|---|---|
| Core / S0, istniejący `runtime/core_admission.py` | Ten sam CoreAdmission, TransactionRunner, WorkspaceStore, AUDIT i OUTBOX | Jeden admission/ledger, bez nowej bazy | Owner produkcyjny NOT_BOUND; fixture assignment jawnie syntetyczne |
| Human approval / S0 + kontrakty S3 | `mission/warrant.py`: zapisany OWNER_APPROVAL, exact warrant, session, assignment revision, revoke i expiry | Native approval witness sprawdzany w transakcji START | Tekst modelu, HTTP proposal i podpis telefonu nie nadają authority |
| Governor / intent / S0 + analiza S3 | `mission/intent.py`: `start_local_zero`; ten sam CoreDualGovernor i journal | USD0 + rzeczywista rezerwacja risk; consume warrant + UNKNOWN + OUTBOX atomowo w bazie; v1 zachowany | Brak atomowości DB+filesystem; utrata ACK wymaga readback, bez retry |
| CPL / S0 | Istniejące `runtime/critical_loop`; veto port w `agent_operations.py` | Bieżące regresje CPL i odmowa przy fixture veto | Unified profile ma fixture-only veto; rzeczywisty CPL LIVE NOT_BOUND |
| Orkiestracja / S1 `meta_hackathon/mission_service.py` | Ta sama MissionService; funkcje `agent_operations.py` | Typowane propose/run/view/stop/reconcile, trwały task i source seal | Brak dowolnego kodu/prompt-to-shell; registered recipe nie wywołuje modelu |
| Workspace / S0 sandbox + referencja S3 | `mission/project_recipe.py`, `workspace_worker.py`, `sensorbridge_checks.py` | Rzeczywiste create/append/rename, 3 pliki, 5 testów Python, diff/hash/receipt | Wyłącznie nowy disposable workspace i zamknięta receptura SensorBridge |
| Linux executor / S0 | Istniejący `mission/sandbox_linux.py`, broker C, namespaces/seccomp/cgroups | Rozszerzony istniejący broker; nofollow/single-link readback, STOP tylko własnego UUID | Zakwalifikowany Linux/Python/Git wymagany; nie system-wide shell |
| Local Git / S0 Git worker + wybrane kontrakty S3 AG04 | `mission/git_publish.py` LocalGitPlan v3; `git_publish_worker.py` korzysta z istniejącego Git helpera | Exact staged diff/tree/commit/branch i niezależny readback faktycznych artefaktów | Repo disposable, `canonical_base_verified=false`; nie poświadcza ancestry repo GitHub |
| GitHub publisher / S3 AG04 + S4 | `RemotePublishBoundary`, osobne przyszłe push/PR | Offline klasyfikacja 401/403/429/ACK oraz bezwarunkowa odmowa remote effect | Create-only produkcyjny transport, credential host i exact owner GO: NOT_BOUND; nie ma realnego push przez AIOA |
| GitHub READ / S0 | Istniejący `mcp_bridge` Task Bus/adaptery zachowane | Regresje istniejących kontraktów; brak nowego klienta GitHub | Żaden nowy odczyt prywatnego repo ani live authentication w tym zadaniu |
| Dependency install / S0 + typowany port | `mission/install_plan.py`, propozycja w tej samej MissionService | Exact package/version/hash/source/license/limits; prawdziwy odczyt fixture artifact | `OFFLINE_FAKE_INSTALLER`, `installed=false`; realne pip/apt/download/SYSTEM_INSTALL wyłączone |
| MCP / S0 | `mcp_bridge/adapter.py`: CoreMissionMCPAdapter; istniejący policy/parser | Rzeczywisty bounded LICENSE READ; WRITE proposal → ten sam Core → lokalny receipt | Namespace/origin/schema/source/expiry; nieznane narzędzia DENY; proposal nie jest permit |
| Android gateway / S1 N1 | Ten sam `mobile_gateway/service.py`; additive `views_v2.py`, `protocol/mobile_mission_v2.json` | Rzeczywiste podpisy P-256, scope przed odczytem, replay denial, receipt po restarcie | W telefonie run/approve/install/native_execute/github_write/meta_spend = false |
| Android app / S1, S2; S5 tylko referencja | Jeden `clients/android`; AgentMissionView, istniejący MobileClient/Keystore/ViewModel/ekran | Typed v2 source, files/diff/tests/Git/install/STOP/UNKNOWN; zachowano v1 | Kotlin/JVM/lint/APK NOT_RUN; fizyczny Xiaomi i qualified TLS NOT_VERIFIED |
| Meta/Muse / S1 | Istniejące `providers/meta_model_api.py`, `meta_receipts.py`; ProviderManager catalog | Mock inference i rzeczywiste fixture receipts odróżnione od niewywołanego modelu | LIVE/billing/credits/exact per-call approval BLOCKED; koszt API tej migracji 0 |
| Nebius/Nemotron / S0, S3 referencyjne | Istniejący `providers/nebius.py`; wpis w tym samym katalogu | Tożsamość i status NOT_BOUND widoczne, brak fallbacku | Nie skopiowano starego ledgera/budżetu ani nie wydano nowego spend permit |
| Local LLaMA | [LOCAL_LLAMA_PROVIDER_PORT.md](LOCAL_LLAMA_PROVIDER_PORT.md), ten sam katalog | SPECIFICATION_ONLY, niedostępny provider | Brak inference/GGUF/NDK/instalacji; nie drugi agent |
| Web i start / S0 + S1 | Jeden `runtime.webapp`, istniejące `web/`, additive Agent workspace | Authenticated status/proposals/exact offline approve/STOP/readback; ta sama MissionService/MCP/mobile | `--unified-offline` jawny profil; brak cutover starych usług, public listenera i prod ownera |
| Dystrybucja / S0 | Istniejący `pyproject.toml`, dodano brakujące JS do tych samych data-files | Wheel/sdist są sprawdzane osobną akceptacją w U9 | Unified profile wymaga source checkoutu i qualified hosta; installed unified niecertyfikowany |
| Android tooling / S2 + S0 G8 | Istniejące `scripts/android`, ten sam manual workflow | Kontrakty statyczne i odmowy; workflow_dispatch zarejestrowany na main | SDK/licencje/ImageVersion/Node24 build GO pozostają osobne; APK_BUILD_BLOCKED |

## Dublujące interfejsy i wyłączenia

Stare instancje 4314/4316/4321 i bramy Nemotrona 18765/18766 pozostają
niezmienionymi źródłami historycznymi; nie są nowym startupem produktu.
Nie kopiowano ich baz, sekretów, kluczy, recovery bundles, GOLD72, AWS ani
zewnętrznego W7A/venv. Zachowano historię, PR22 i PR25; nie zamknięto ich
automatycznie. Przyszłe hackathony rozszerzają powyższą kompozycję.

WNIOSKI: minimalny lokalny zakres U2–U8 jest implementacją z rzeczywistymi
efektami i fixture authority. REKOMENDACJA: akceptować wyłącznie tak opisany
zakres. Produkcyjne owner binding, wydatki, zdalny publisher, instalacje,
APK/telefon/TLS i promotion main wymagają odrębnych dowodów i zgód.

## Zamrożony kandydat po review

Finalne local/offline wyniki: U9_QA_EVIDENCE.md; niezależny raport i autorski
fix pass: INDEPENDENT_REVIEW.md. Recorded revoke działa także w legacy paths.
Android agent pending-ID ma explicit local handoff, bez cross-session authority.
M1 v2 history paging pozostaje odroczony. Produkcyjny owner, M12/storage,
paid inference, real remote publisher/installer i APK/phone/TLS nie uzyskały GO.
Main pozostaje celem osobnej dokładnej zgody: UNIFIED_CANDIDATE_READY /
MAIN_MERGE_PENDING_OWNER_GO. Exact final PR/head/base w przekazaniu właściciela.
