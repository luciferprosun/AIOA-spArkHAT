# U9 — końcowe dowody ONE AIOA

FAKTY, data 2026-11-01. Repo `luciferprosun/AIOA-spArkHAT`, gałąź
`integration/one-aioa-core-muse-mobile-20261101`.
Zamrożony kod po jedynym fix pass: `1cd2a91da0a1e8ef10186458327d4a115d9444a0`.
Capsule 76 plików: `2d587c399a4cba5342182bea7f17a7c3ea1dfe6775c1ccc6d938077aba642dfa`.
Prywatne dowody: `/home/l/projects/AIOA_UNIFICATION_PRIVATE_20261101/U_20261101T064644Z`. Raporty/commity dokumentacji są późniejsze;
exact head publikacji, bieżący main i końcowy smoke są przypięte w draft PR.
Nie zastępuj SHA wykonanego przebiegu późniejszym SHA raportu.

## Wyniki po poprawkach review

| Kontrola | Rzeczywisty wynik | Prywatny dowód |
|---|---|---|
| Pełne Python discovery | 2488 total = 2483 PASS +5 SKIP; 2138 subtests; 0 fail/error; 1173.759s | U9_PORTABLE_POST_REVIEW/result.json, suite.log, command.json |
| Native Core/worker/HTTP/mobile/Git/restart | 42/42 PASS, 28 subtests, 0 skip; 171.511s | U9_NATIVE_POST_REVIEW/ |
| Node | 15/15 PASS, 0 fail/skip; zawiera SOURCE checks Androida | U9_NODE_POST_REVIEW/suite.log |
| Wheel i sdist | 2/2 PASS, source/PYTHONPATH hidden, oddzielny PID/net namespace | U9_PACKAGING_POST_REVIEW/acceptance/result.json |
| AST3.11 + compile na3.12 | wszystkie666 tracked plików Python PASS; interpreter3.11 nieuruchomiony | U9_STATIC_POST_REVIEW_HOST3/AST.json |
| Android build input | MATCH; Kotlin/JVM/lint/APK NOT_RUN | U9_STATIC_POST_REVIEW_HOST3/ANDROID_INPUTS.json |
| NonZero ownership/provenance/license | PASS, 0 findings, 39 native files | U9_STATIC_POST_REVIEW_HOST3/architecture-license.log |
| Licencje/provenance | Zachowane MIT/MemoryPatch/NonZero/Apache notices, pinned wrapper | U9_STATIC_POST_REVIEW_HOST3/LICENSE_PROVENANCE.json |
| Dirty źródło i procesy | 185/185 publicznych hashy zachowane, 5/5 PID/cwd/exe zachowane | U9_STATIC_POST_REVIEW_HOST3/INVARIANTS.json |
| git diff --check | PASS | U9_STATIC_POST_REVIEW_HOST3/diff-check.log |
| Niezależny review | 0 Critical, 3 Important, 1 Minor; Important naprawione test-first + final green suite | INDEPENDENT_REVIEW.md |

Pięć skipów to istniejące warunki CI: 2 Playwright (brak optional biblioteki),
2 Textual (brak optional biblioteki), 1 NVIDIA NAT ATIF (brak pinned site).
Nie pominięto żadnego native host case. Liczniki nie obejmują Kotlin/JVM,
Compose, urządzenia, TLS ani rzeczywistego Chrome. Pięć testów wygenerowanego
projektu jest wynikiem receptury, nie dodatkową sumą testów Core.

## Środowisko i komendy

Python3.12.3, Git2.43.0, istniejące kwalifikowane bwrap/cc/user-cgroups/seccomp,
pojedynczy worker. Brak instalacji JDK/SDK, płatnych API i zewnętrznego Chrome.
Portable QA działa w read-only root/net namespace, z ephemeral /tmp i maskami
rzeczywistych config/.ssh/.codex/state; bez kluczy w env. Prywatny interpreter
korzysta tylko z zapieczętowanych już zainstalowanych pydantic2.13.4,
pydantic-core2.46.4 i uuid6 2025.0.1; bez pobierania/instalacji zależności.
Native QA ma dodatkowy guard odmowy odczytu sekretów, external/protected network
i zapisu do źródłowych worktrees; brak nowych odmów guarda.

```bash
PYTHONPATH=.:tests PYTHONDONTWRITEBYTECODE=1 python3 -B -m unittest discover -s tests -p 'test*.py'
PYTHONPATH=.:tests PYTHONDONTWRITEBYTECODE=1 python3 -B -m unittest discover -s tests -p 'host_unified_*.py'
node --test tests/*.test.cjs
python3 -B -m runtime.mobile_gateway.build_handoff --check
python3 -B -m runtime.tools.nonzero_architecture --project-root .
python3 -B tests/packaging_acceptance.py --output /absolute/fresh/private/package-qa --isolate-filesystem
git diff --check
```

Packaging instaluje tylko własny wheel offline `--no-index --no-deps`
w świeżych prywatnych venv; nie instaluje hostowych pakietów. Unified native
startup wymaga qualified source checkoutu; bare-wheel startup na innym hoście
nie jest poświadczony. AST3.11 nie jest uruchomieniem Pythona3.11.

## Rzeczywisty lokalny E2E

`U9_DEMO_POST_REVIEW/evidence/DEMO_REPORT.json` dokumentuje podpisaną propozycję,
dokładne syntetyczne host approvals, realne create/append/rename, pięć testów,
niezależny readback, lokalny commit z zatwierdzonych artefaktów, remote403
i podpisany receipt po rzeczywistym uruchomieniu nowego procesu aplikacji.
Pełny JSON i prywatny klucz fixture pozostają poza repo. Źródło jest przypięte
w raporcie; jego SHA-256: `35c0a947444110b2bee95b3312c01550cfcd6d8cdb8a3f95cb366a8f5ee4090c`.
`model_invoked=false`, `paid_api_calls=0`, produkcyjny owner NOT_BOUND;
to Android-like fixture, bez fizycznego telefonu i verified TLS.
Task workspace `agent-a1d37f7cdc8edf4e6ee2de983dc47f0a`; receipt SHA-256
`2dea1c06f4462c8f87acf73940d5b1d9fc4cfd6b8bd56010b368abc586d2f9fc`; task digest `e6c711137460ea2664fbdd0a0774f9f4a3f911814b714fae2c73ba4380a1e600`.
Git task `agent-74ae23b326f25b529e31b95e93e77fd9`; przewidziany i rzeczywisty HEAD
`f54ba30c1651c667631387b0e98eb7dc42f428d2`, tree `e0d5e3f964ad96a78181a85d4bdefff806d91e24`.
Budżet lokalny money_nano=0, risk_units=2.
Końcowy powtórzony smoke exact head publikacji trafia do opisu PR.

## Inwarianty i odmowy

| Granica | Testy |
|---|---|
| Missing/forged owner, exact source/task/scope/digest | host_unified_missions, host_unified_security, test_unified_zero_intent, test_core_tool_composition |
| Expiry/revoke/session/epoch/CPL | host_unified_security, test_review_revocation, test_meta_model_api, test_unified_zero_intent |
| USD0, real risk, jednorazowy START/UNKNOWN | test_unified_zero_intent, test_core_intent, test_dual_governor |
| Unauthorized shell/write/install/remote | host_unified_http, host_unified_mcp, test_unified_install, test_unified_git |
| Nofollow/hardlink/resource/output | host_unified_security, test_sandbox_contracts, host_unified_faults |
| CPU/memory/output/STOP | host_unified_faults: actual TIMEOUT, MemoryError pod AS bound, OUTPUT_LIMIT, owned cgroup terminal/no project effect |
| ACK loss/restart/no replay | host_unified_missions, host_unified_faults Git postcommit, host_unified_demo, test_core_intent |
| Mobile cross-device/old session/replay | host_unified_mobile, test_meta_mobile_gateway/http/wire |
| Android local pending-ID handoff | test_meta_mobile_android: SOURCE guards; przyszłe WireContractTest NOT_RUN |
| Provider identity/no fake LIVE | test_unified_providers, test_meta_model_api, test_meta_p2_receipts |
| Chrome source mount completeness | test_meta_mobile_chrome_mounts: 76 capsule files, no whole checkout/home; actual capture NOT_RUN |
| Remote401/403/429/ACK | test_unified_git: offline klasyfikacja + stałe DENY; brak rzeczywistego publishera |

Nie deklarujemy atomowości filesystem+Core DB ani certyfikacji dowolnego
kodu/kernel sandboxa. UNKNOWN rozlicza niezależny verifier; nigdy retry.
Istniejący DurableFactory COW/core-records.json nie jest produkcyjnym M12/Cockroach.

## Review i zachowane nieudane przebiegi

Świeży niezależny reviewer zbadał cały zakres main de6fddb..f0ddb3e:
42 commity/214 plików, z naciskiem na wykonywalne granice. Nie uruchamiał
efektów ani nie czytał sekretów. Ocena With fixes, 0C/3I/1M.
Autor wykonał JEDEN fix pass, bez ponownego niezależnego review:
I1 RED6/5fail → GREEN82/82 (shared revoke);
I2 SOURCE RED13/3fail → GREEN40/40 oraz signed native restart1/1;
I3 RED4/3fail → GREEN20/20 (76 mounts).
Wszystkie poprawki obejmuje końcowy green suite powyżej. M1 pagination
Android v2 >16 zadań jawnie odroczono; host/task-ID handoff pozostaje dostępny.
Pełne rozstrzygnięcia i koszty: OWNER_HANDOFF_PL.md / INDEPENDENT_REVIEW.md.

Zachowano początkowy full2477/12fail/27error/79skip: maska stanu ukrywała
już istniejące NonZero deps, maska /dev/null na nodev dawała Git EACCES,
a stary Meta-only branding nie spełniał wspólnego HTTP kontraktu. Skorygowano
środowisko i nazwę jednej aplikacji. Pierwszy green2477/2062 dotyczył6f020f5.
Home-cache RED ujawnił użycie publicznego codec do prywatnych locatorów;
9f5e6b4 naprawia save/load prywatnym codec, zachowując publiczny path guard.
Izolowany static gate zatrzymał się na metadata /proc (namespace EACCES);
helper poprawiono, aby UNKNOWN_METADATA_ONLY nie traktować jak SHA-256;
powtórzony read-only host static gate obejmuje wyłącznie185 zapieczętowanych
plików publicznych i te same procesy, bez zmiany sandboxa produktu. Błędny
helper wcześniej tymczasowo hashował38 logów/testów z oznaczeniem UNKNOWN;
nie opublikowano ich treści/hashów ani nie zaimportowano ich do produktu.
Porównanie statusów poprawiono także do oryginalnego --untracked-files=all.
Pierwsze nieudane helper logs zachowano. Przebieg f0 U9_PORTABLE_RELEASE przerwano po findings; jest INCOMPLETE,
nie PASS. Zachowano również pierwsze fault harness i błędne nazwy dwóch
modułów review-I3; poprawione rzeczywiste zestawy są green.

## Sekrety, licencje i publikacja

Post-code skan na `1cd2a91da0a1e8ef10186458327d4a115d9444a0`: 215 plików bieżących,
raw FAIL4; cała wychodząca historia 45 commitów /
341 unique blobs, raw FAIL6. Wszystkie flagi to
odziedziczone jawne negative fixtures, independently reviewed na f0.
Dodanie testu revoke zmienia hash jednego pliku, lecz fingerprinty samych
kandydatów pozostają identyczne jak public17280c0; nie twierdzimy, że cały
bieżący plik jest byte-identical. Nieznanych flag:0; raw FAIL zachowano,
skanera nie wyciszono. Finalny scan po raportach jest przypięty w PR.

MIT AIOA/MemoryPatch/NonZero/Apache notices zachowano. Wrapper/distribution
Gradle8.13 potwierdzono przez [oficjalne checksums](https://gradle.org/release-checksums/).
Nie kopiowano unlicensed Android labs, W7A/venv, sekretów, recovery,
AWS/GOLD72 ani Nemotron CLI. Brak zmian workflow względem main G8.
Standardowy public runner ma darmowy compute według [GitHub billing](https://docs.github.com/en/billing/concepts/product-billing/github-actions);
nie zamówiono larger runner, Copilot review ani Android artefaktu. Automatyczny
CodeQL odnotowuje się osobno; brak CI run nie jest CI PASS.

DECYZJA: UNIFIED_CANDIDATE_READY / MAIN_MERGE_PENDING_OWNER_GO.
Produkcyjny owner/CPL/storage, paid API, remote publisher, installer,
JVM/APK/phone/TLS i main promotion nie są zatwierdzone powyższymi wynikami.
