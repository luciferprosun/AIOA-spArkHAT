# U9 — dowody odbioru ONE AIOA

Data: 2026-11-01.
Prywatne dowody: `/home/l/projects/AIOA_UNIFICATION_PRIVATE_20261101/U_20261101T064644Z`. Repo: `luciferprosun/AIOA-spArkHAT`.
Gałąź: `integration/one-aioa-core-muse-mobile-20261101`.
Pierwszy pełny GREEN: `6f020f5b641acbbbe3df2256e0022020803896ee`.
Aktualny kod po poprawce home cache: `9f5e6b437df5a9ebd711c257a092da102d12b038`;
końcowa pełna regresja tego kodu jest wymagana przed publikacją.
Native acceptance: `9f5e6b437df5a9ebd711c257a092da102d12b038`;
41 przypadków po poprawce home cache, 28 subtests, 0 failure/error/skip.
Capsule 76 plików krytycznych:
`2024da817a5a37f655f09af21d46c3a63e7b29a2b2963d3adf7d531ee6df3bf6`.
Dokładny head publikacji i końcowy smoke są przypięte w opisie draft PR;
commity raportów nie są podmieniane za SHA rzeczywistych przebiegów.

## Środowisko i komendy

FAKTY: Python3.12.3, Git2.43.0, kwalifikowany lokalny Linux x86_64,
istniejący bwrap/cc/user-cgroups/seccomp. Brak instalacji JDK/SDK/Gradle.
Testy pojedynczym workerem; żadnych połączeń model API ani zewnętrznego Chrome.

Pełny portable suite odtworzono przez prywatny `qa_run.py`, który uruchamia
ten sam unittest discovery/result runner wewnątrz bwrap: root read-only,
oddzielna sieć, ephemeral /tmp, zasłonięte rzeczywiste .config/.ssh/.codex/state,
czyste env bez kluczy. Użyto istniejących pydantic2.13.4,
pydantic-core2.46.4, uuid6 2025.0.1 z read-only publicznego cache pakietów,
z SHA/METADATA seals, poprzez prywatny interpreter QA. Nie pobierano ani
instalowano tych zależności. Fresh `-I` subprocessy korzystają z tego samego
interpretera; nie importują cudzych modułów runtime/testów.

Odpowiadające komendy projektu (w już przygotowanym środowisku):

```bash
PYTHONPATH=.:tests PYTHONDONTWRITEBYTECODE=1 python3 -B -m unittest discover -s tests -p 'test*.py'
PYTHONPATH=.:tests PYTHONDONTWRITEBYTECODE=1 python3 -B -m unittest discover -s tests -p 'host_unified_*.py'
node --test tests/*.test.cjs
python3 -B -m runtime.mobile_gateway.build_handoff --check
python3 -B -m runtime.tools.nonzero_architecture --project-root .
python3 -B tests/packaging_acceptance.py --output /absolute/fresh/private/package-qa --isolate-filesystem
git diff --check
```

Native suite wykonano na hoście, z prywatnym guardem odmawiającym odczytu
rzeczywistych sekretów, sieci zewnętrznej/chronionych portów i zapisu do
źródłowych worktrees. Nie ma nowych odmów guarda. To dodatkowy guard QA;
nie nowy moduł authority produktu. Kernel sandbox pozostaje istniejącym brokerem.

## Wyniki końcowe

| Sprawdzenie | Wynik | Dowód prywatny |
|---|---|---|
| Pełne Python discovery | 2477 total: 2472 PASS +5 SKIP, 2062 subtests,0fail/error,1235.469s na6f; finalny rerun po poprawce9f PENDING | `U9_PORTABLE_GREEN/result.json`, `suite.log`, `command.json` |
| Native Core / namespace / cgroup / worker / signed mobile / HTTP / restart | 41 testów, 28 subtests, PASS, 0 skips; runner150.482s | `U9_NATIVE_RELEASE/` |
| Dodatkowe awarie CPU/memory/output/STOP/post-commit ACK | 5/5 PASS,36.389s; ponownie PASS jako część bieżących41 (CPU TIMEOUT, MemoryError, OUTPUT_LIMIT, owned STOP, Git ACK/restart) | `U9_NATIVE_FAULTS_PROOF/`, `U9_NATIVE_COMBINED/`, `U9_NATIVE_RELEASE/` |
| Node | 15 PASS, 0 fail/skip; 688.013ms | `U9_NODE_GREEN.log` |
| Wheel i sdist | 2/2 PASS, source/PYTHONPATH hidden; odrębna sieć/PID | `U9_PACKAGING_FINAL/acceptance/result.json` |
| Android build input manifest | MATCH, APK NOT_BUILT | `U9_STATIC_FINAL/android-inputs.log` |
| NonZero ownership/provenance/license/static architecture | PASS, 0 findings, 39 native files, no second Core/server/credential layer | `U9_STATIC_FINAL/architecture-license.log` |
| AST Python3.11 + compile na3.12 | 543 pliki PASS, AST3.11 i compile na3.12; bez uruchomienia interpretera3.11 | `U9_AST_RELEASE.json` |
| Diff whitespace | PASS | `U9_STATIC_FINAL/diff-check.log` |
| Zachowanie źródła | 185/185 publicznych dirty-source hashes bez zmian | `U9_INVARIANT_RECHECK_PRE_REVIEW.json` |
| Chronione procesy | 5/5 te same PID/cwd/exe; bez cutover | ten sam invariant recheck |
| Niezależny review | PENDING — świeży niezależny review całego migration diff przed publikacją | raport zostanie zapisany osobno, bez nadpisywania wcześniejszych dowodów |

Pięć zgodnych z istniejącą polityką CI pominięć: 2 Playwright (brak biblioteki), 2 moduły Textual (brak opcjonalnej biblioteki), 1 oficjalny walidator NVIDIA NAT ATIF (brak skonfigurowanego pinned site). Żaden native host case nie jest pomijany. Python3.11 sprawdzono AST, nie uruchomiono interpretera3.11.

Liczby Python/Node nie obejmują wykonania JVM/Compose/lint/APK ani fizycznego
telefonu/TLS. Pięć lokalnych testów projektu jest wynikiem receptury, nie
dodatkowymi pięcioma przypadkami dopisywanymi do licznika każdego testu Core.
Nie użyto historycznych „533 Python / 10 Node” jako dowodu tych zmian.

## E2E i przypadki odmowy

Utrwalony rzeczywisty przebieg `U9_DEMO_HOME_GREEN/DEMO_REPORT.json`, source `9f5e6b437df5a9ebd711c257a092da102d12b038`, capsule `2024da817a5a37f655f09af21d46c3a63e7b29a2b2963d3adf7d531ee6df3bf6`. Task workspace `agent-f3946e48dd415574a1c25242f52008af`, receipt SHA-256 `ebdae779e7fa5f5672283b0d5260b409310f9268c6483abe359fad1a873e394f`. Git task `agent-0c59aa4d8f9f17eb6e6d045fe154e8f4`, rzeczywisty/predicted HEAD `0d0885cead94fa88efb93dea9bc69b291e0fbe15`, tree `e0d5e3f964ad96a78181a85d4bdefff806d91e24`. 5 testów, podpisany readback z nowego procesu, remote403, model_invoked=false, paid_api_calls=0, production_owner=NOT_BOUND. SHA-256 raportu `bc3cac8c933a449a346ae0c04ace426eafd6f3079eb868680e2b0b4223961c99`. Dane i prywatny klucz transportowy fixture pozostają poza repo. To nie telefon ani TLS.

| Inwariant | Bieżące testy / dowód |
|---|---|
| Missing/forged native owner | `host_unified_missions.test_missing_and_forged_owner_never_dispatch`, `test_unified_zero_intent.test_forged_core_principal_cannot_start` |
| Expiry, revoke, epoch | `host_unified_security.test_valid_but_expired_owner_principal_denies`, `test_revoked_session_and_policy_epoch_change_deny_before_start`, `test_unified_zero_intent` revoke |
| Exact source/task/preview/schema/scope | `host_unified_missions.test_source_or_preview_change_denies_before_start`, `test_unified_zero_intent`, `test_sandbox_contracts`, `test_core_tool_composition`, `host_unified_mcp` |
| CPL veto i STOP | `host_unified_missions.test_cpl_veto_is_not_model_authority`, stop-before-start oraz końcowe native fault cases |
| USD0, real risk, warrant consume i durable UNKNOWN | `test_unified_zero_intent` 6 przypadków + istniejące intent/governor/tool regression |
| Unauthorized shell/WRITE/EXEC/INSTALL/remote | `host_unified_http.test_same_server_mcp_bounded_read_and_deny_generic_commands`, `host_unified_mcp`, `test_unified_install`, `test_unified_git` |
| Symlink/hardlink/readback/cache bounds | `host_unified_security.test_independent_readback_rejects_symlink_and_hardlink_receipts`, `host_unified_cache`, `test_sandbox_contracts`, closed workspace registry |
| Cross-device / stale key / replay | `host_unified_mobile`, istniejące `test_meta_mobile_gateway/http/wire` |
| File-effect ACK loss / restart bez retry | `host_unified_missions.test_post_effect_ack_loss_requires_independent_reconciliation_never_retry`, `host_unified_demo`, `test_core_intent` |
| Git commit / unchanged verified source | `host_unified_git`, końcowy post-commit fault; realny readback repo/HEAD/tree/branch/status/files |
| Remote401/403/429/ACK loss | `test_unified_git`: offline klasyfikacja i stała odmowa remote; NIE wykonanie prawdziwego transportu push/PR |
| Model identity / fake LIVE | `test_unified_providers`, `test_meta_model_api`, Node receipt presentation; model niewywołany przez local recipe |

Limity natywne są zakresem sprawdzonych profili i tego hosta; nie deklarujemy
certyfikacji dowolnego kodu/sandboxa ani atomiczności filesystem+Core DB.
Niepewny efekt pozostaje UNKNOWN, aż istniejący niezależny verifier go rozliczy.

## Błąd prywatnego cache pod home

Pierwszy utrwalony demo pod /home/l zatrzymał się przed dispatch. Private host
locators były serializowane publicznym canonical contract codec, który poprawnie
odrzuca takie ścieżki. Dodano test home/cache RED, następnie oddzielny prywatny
codec w save/load host cache. Publiczny path guard jest niezmieniony i nadal
sprawdzany odmową. Cztery cache/realCLI cases PASS,16.553s; końcowy native suite41 PASS; rzeczywisty retained
home demo powyżej PASS. Nie przedstawiamy wcześniejszych testów /tmp jako
dowodu, że katalog home działał przed tą poprawką.

## Pierwsze błędy i poprawki

Zachowano pierwszą pełną próbę: 2477 tests /2016subtests, 12fail/27error,
79skips,1106.967s. Nie jest raportowana jako PASS. Osłonięcie ~/.local/state
ukryło istniejące NonZero deps, a maska ~/.gitconfig na /dev/null w nodev
namespace powodowała EACCES Git. Zastosowano właściwy istniejący zestaw
zależności oraz pusty zwykły plik maski, bez osłabienia granic produktu.
Stara Meta-only nazwa HTML nie spełniała istniejącego HTTP testu jednej konsoli;
przywrócono wspólną tożsamość. Odpowiednie 68 testów: 0failure/error,
1 istniejący skip walidatora ATIF, 39subtests,35.305s.

Node pierwsze15: dwie source-only asercje odnosiły się do polskiego napisu
STOP i niewersjonowanej listy stanów N1. Zaktualizowano test do English oraz
dokładnego zestawu N1+v2, nadal wykluczając UNKNOWN; 15/15 PASS.

Pozostałe wcześniejsze RED/GREEN i diagnozy (m.in. ELF loader mode, session
limits, receipt links i kopiowanie faktycznych artefaktów Git) są zachowane
w dzienniku i logach poszczególnych U1–U9, bez nadpisywania źródeł.

## Sekrety, licencje, source review i publikacja

Raw skan bieżących plików: 4 flagi w publicznych odziedziczonych testach.
Raw skan wychodzącej historii na bazie S0: 37 commitów/314 unique blobs,
5 flag (jeden test ma dwie historyczne wersje); wszystkie dotyczą jawnie
syntetycznych negative fixtures, z osobnym redacted review/hash i wcześniejszym
publicznym pochodzeniem. Raw status FAIL pozostał zachowany; nie podmieniono
go na PASS ani nie wyciszono skanera. Nowy kod nie dodaje kandydatów sekretów.
Końcowy skan publikacji i liczby po raportach: PENDING po końcowych raportach; rozstrzygnięcia odziedziczonych synthetic fixtures zachowane..

Zachowano MIT AIOA i notices Memory Patch/NonZero/Apache Gradle wrapper.
Nie importowano unlicensed Android źródeł, W7A/venv, prywatnych baz/receipts,
recovery, AWS/GOLD72 ani eksperymentalnych Nemotron CLI. Workflows względem
main G8 bez zmian; Android manual build NIE jest dispatchowany.

Publiczny standardowy runner ma bezpłatny compute według
[GitHub Actions billing](https://docs.github.com/en/billing/concepts/product-billing/github-actions).
Nie zamówiono larger runner, Copilot review ani artefaktu Androida.
Automatyczny CodeQL po draft PR należy odnotować oddzielnie od lokalnej regresji;
brak uruchomienia Core CI nie jest nazywany CI PASS.

WNIOSKI i REKOMENDACJA: READY_FOR_INDEPENDENT_REVIEW; końcowa regresja i review nadal wymagane przed branch push/draft. MAIN_MERGE_PENDING_OWNER_GO. Produkcyjny owner, płatne modele,
remote Git, rzeczywisty installer i Android build/telefon/TLS pozostają poza
zakresem powyższych PASS. Ostateczna promocja main wymaga nowej dokładnej zgody.

Bieżące grupy pełnego wcześniejszego GREEN: Meta323, MCP99, Android tooling44,
NonZero105, Core109, unified39 (w tym historyczny Nebius20), sandbox29, Git6.
Grupy są częściami discovery, nie dodatkową sumą niezależnych testów.
