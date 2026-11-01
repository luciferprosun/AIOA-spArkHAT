# Android toolchain — handoff G0–G7

Zlecenie: `AIOA_Android_Codex_Master.pdf`, 31.10.2026; wykonanie obejmuje
01.11.2026 CET. **Lokalny build APK pozostaje BLOCKED.** Dostarczono narzędzia,
testy offline, definicję ręcznego CI i specyfikacje. Nie nadano nowych
uprawnień agentowi ani telefonowi.

## Tożsamość i zachowane źródła

Repo: `https://github.com/luciferprosun/AIOA-spArkHAT`.
Gałąź: `codex/android-toolchain-mobile-20261031`.
Worktree: `/home/l/AIOA_LOCAL_WORKTREES/android-toolchain-mobile-20261031`.
Niezmieniona baza lokalna N1: `6216b16f22da167b401f8611291264d73eaacb40`.
Kanoniczny checkout `/home/l/projects/AIOA-spArkHAT-META` zachował tę bazę,
gałąź `AIOA-METAGuardiansSPARK` i czysty status. Sprawdzono35 plików
wejściowych N1 w obu checkoutach:70 porównań SHA256/rozmiaru zgodnych.
Manifest Androida zwrócił `BUILD_INPUTS_MATCH`.

Checkpoint A: `9bfb8bff934f007649782cfa87cb467dbcbe7432` — lokalne narzędzia,
28 testów. Checkpoint B: `042469a362a5e9675ab9056bbca94b9e0ca56b02` — manualny
workflow, dodatkowe6 testów, architektura i placeholdery. Checkpoint C:
`32724a1a6dcfd8f99b26da3bb4b3fb0db628ca86` — poprawki review i końcowe
533 Python/10 Node PASS. Późniejszy commit handoff zmienia tylko ten dokument.
Bieżący HEAD odczytać
przez `git rev-parse HEAD`; dokładny końcowy SHA znajduje się także w prywatnym
`TOOLCHAIN_FINAL_EVIDENCE.json`, poza commitem, którego tożsamość opisuje.

## Stan bramek

| Gate | Status | Dowód | Co blokuje | Następna czynność właściciela |
|---|---|---|---|---|
| G0 | PASS | Izolowany worktree, baza/hash/status, prywatny manifest | — | Odbiór nowej gałęzi |
| G1 | BLOCKED_STORAGE_TOOLCHAIN | UUID/ext4/ścieżki/miejsce zgodne; brak bieżącej niezależnej kwalifikacji | Brak kwalifikacji SMART/USB i rozliczenia historycznych usterek | Niezależny odbiór storage przez właściwy zaufany monitoring/operatora |
| G2 | BLOCKED_G1 | Archiwa0, instalacje0 | G1; dodatkowo licencja SDK i brak niezależnie opublikowanego SHA256 API36/BT35 | Nie obchodzić G1; rozstrzygnąć licencję i silne sumy albo wybrać ręczny CI |
| G3 | PASS_OFFLINE | Testy zabezpieczeń, `bash -n`; rzeczywiste CLI odmawiają przed efektem | Rzeczywisty JDK/SDK/Gradle/build nieprzetestowany | Odbiór testów i późniejszy kontrolowany build |
| G4 | READY_FOR_OWNER_REVIEW / NOT_RUN | YAML workflow_dispatch-only, kontrakt testowany offline | Autoryzacja runu, billing/artefakty/licencja/obraz, rejestracja default-branch | Przejrzeć osobny runbook; nie uruchamiać bez osobnej zgody |
| G5 | SPECIFICATION_ONLY | Architektura i ADR-001 | Produkcyjny edge, owner channel, build i przyszłe zdolności coding/Git | Odebrać projekt; nie włączać Run/approve/WRITE |
| G6 | SPECIFICATION_ONLY | Manifest7 placeholderów i obliczenia kontrastu | Brak osobnej zgody/licencji/eksportów | Zatwierdzić specyfikację; grafiki nie powstały |
| G7 | PASS_OFFLINE / DRAFT_PR_CREATED | Jeden review,6 ustaleń zamkniętych testami;533 Python +10 Node PASS;PR25 | Odbiór właściciela; pozostałe bramki wykonania nadal czerwone | Przejrzeć draft i handoff, bez samoczynnego buildu |

## Wersje: plan, nie instalacja

| Składnik | Pin w dostarczonym katalogu / N1 | Zainstalowany i wykonany tutaj |
|---|---|---|
| JDK | Temurin17.0.21+9 Linux x64 | NIE |
| SDK cmdline-tools |22.0 / build15859902 | NIE |
| Android platform | API36 revision2, min26/target36 | NIE |
| build-tools |35.0.0 | NIE |
| Gradle |8.13, istniejący wrapper SHA zgodny | NIE; wrapper nieuruchomiony |
| AGP / Kotlin |8.11.1 /2.2.21 w istniejących plikach | Zadeklarowane; kompilacji nie wykonano |

Zweryfikowano wyłącznie oficjalne metadata/wersje/sumy, bez archiwów.
Google XML publikuje SHA1 dla dwóch wskazanych pakietów; `sha256:null` jest
celową blokadą, a nie zgodą na pobranie bez silnej sumy. Patrz
`scripts/android/toolchain.lock.json` i README.

LSC_DATA3: `/dev/sda1`, ext4, UUID `1c748500-8e12-4e23-80be-115ce7f3937a`.
Odczytane liczniki błędów0 i opcja `rw` nie są certyfikacją dysku. Brak
`smartctl` nie został naprawiony instalacją. Nie stworzono
`/media/l/LSC_DATA3/AIOA_ANDROID_TOOLCHAIN`, nie wykonano nawet16 KiB probe.
**Celowo zapisane przez zadanie bajty danych na tym woluminie:0.** Odczyty
mogą powodować normalny atime; nie twierdzimy, że mierzyliśmy fizyczne zapisy
kontrolera albo aktywność innych procesów.

G1 przewiduje jawny pin autentycznego raportu, ale nie znaleziono takiego
źródła. Proponowany schemat pliku nie jest istniejącą certyfikowaną usługą
WD Watch. Nie pisać ręcznie `PASS`, nie produkować raportu modelem ani nie
przenosić fixture jako kwalifikacji. Szczegóły: [G1_STORAGE_DECISION.md](G1_STORAGE_DECISION.md).

## Bezpieczne komendy dostępne teraz

Z katalogu nowego worktree:

```sh
python3 -B scripts/android/toolchain_doctor.py --json
bash scripts/android/install_toolchain.sh --dry-run --source-sha <PELNY_BIEZACY_HEAD>
bash scripts/android/build_apk.sh --source-sha <PELNY_BIEZACY_HEAD>
```

W obecnym środowisku poprawnym wynikiem tych komend jest exit2 /
`BLOCKED_STORAGE_TOOLCHAIN`, z zerem pobrań/prób buildu. Ostatnia komenda
po przyszłym spełnieniu bramek rzeczywiście rozpoczyna build — nie traktować
jej jako niezmiennego dry-run. `env.sh` jest per-command, bez zmiany globalnych
profili/HOME; wymaga potwierdzonego lokalnego toolchainu.

Testy skryptów: `python3 -B -m unittest discover -s tests -p 'test_android_*.py' -v`.
Kontrakt YAML korzysta z już obecnego lokalnie PyYAML; nie instalowano go ani
innych zależności. Produkcyjne skrypty Python używają standardowej biblioteki.
Shellcheck nie jest dostępny; wykonano3 kontrole `bash -n`, bez udawania
przeglądu shellcheck.

## Dowody testów i zasoby

Po finalnych poprawkach review:44 nowe tooling PASS,323 Meta/mobile,
13 Core warrant,99 MCP,4 audit compatibility,26 native persistence ports,
24 native lifecycle =533 Python PASS; dodatkowo10 Node PASS. Bez FAIL/SKIP
w tych zakończonych zestawach. RED sprzed implementacji są zachowane i nie
są przemianowane na GREEN. Wszystkie właściwe regresje ponowiono po poprawkach.

Komendy odpowiadają `unittest discover -s tests -p` z wzorcami
`test_android_*.py`, `test_meta_*.py`, `test_core_warrant.py`, `test_mcp_*.py`,
`test_governor_audit_compatibility.py`, `test_memory_patch_persistence_ports.py`,
`test_memory_patch_lifecycle.py`; Node:
`node --test tests/meta_mission_ui.test.cjs tests/meta_mobile_ui.test.cjs`.
Testy Android SOURCE w Meta nie są wykonaniem Kotlin/JVM ani telefonu.
Nie powtarzano testów obcych Companion ani całego repozytorium z eksperymentami.

Maszyna:2CPU, RAM3933564928 B. Obserwacja końcowego snapshotu przed review:
MemAvailable745590784 B, SwapFree274141184 B; root free13225177088 B
(około12.32 GiB), external154024210432 B (około143.45 GiB).
Meta:61.64s wall/67% CPU/maxRSS56260 KiB; pozostałe zestawy Python:
Core4.59s/38332 KiB, MCP8.03s/38908 KiB, audit4.70s/39272 KiB,
ports1.06s/28268 KiB, lifecycle30.73s/30964 KiB. Liczniki RSS pochodzą z
`/usr/bin/time`, nie z profilowania wszystkich procesów całego hosta.
Końcowy ponowiony Meta:56.34s/maxRSS56280 KiB; nowe44 testy tooling:
4.21s/maxRSS32180 KiB. Nie sumować ponownych uruchomień jako nowych przypadków.
Brak budżetu pamięci dla ciężkiego lokalnego buildu pozostaje dodatkowym
ograniczeniem; nie zatrzymywano cudzych procesów, aby go uzyskać.

APK: **NIE ZBUDOWANO**. Brak nowej ścieżki, SHA APK i nowego certyfikatu.
Nie użyto starego APK0.1.0 jako dowodu N1. Kotlin/JVM10 przygotowanych,
lint/assemble/apksigner/Android E2E/Meta LIVE: NOT_RUN lub BLOCKED.

## Review i publikacja

Niezależny review bazy6216b16..checkpointB miał werdykt With fixes:
0Critical/5Important/1Minor. M1 podniesiono do Important ze względu na limit
JVM/home. Autor poprawił wszystkie6 w jednej rundzie RED→GREEN;10 nowych
przypadków i właściwe regresje przeszły. Nie wykonano drugiego review i nie
przedstawiamy dyspozycji autora jako nowego niezależnego zatwierdzenia.
Szczegóły i wszystkie8 granic „Declined to judge” z kosztem błędu:
[G7_REVIEW_DISPOSITION.md](G7_REVIEW_DISPOSITION.md). Odroczonych Minor brak.

Poprawki: większy, osobno ograniczony manifest; inventory wyprowadzane ponownie
z prawidłowego archiwum producenta; blokady ignored SDK/Gradle override;
cleanup własnej grupy po SIGTERM; source binding UNKNOWN dla standalone APK;
skuteczne opcje JVM z testem launchera. Pierwsza próba GREEN miała błędny typ
odmowy brakującego archiwum, naprawiony przed końcowym PASS. Pełne logi zachowano.
Samodzielne `verify_apk.py` nie nadaje APK source SHA na podstawie nazwy katalogu.
Tylko udany kontrolowany build dopina source/invocation/log/report digests;
to dowód pochodzenia z lokalnego procesu, bez zewnętrznej atestacji buildu.

Utworzono wyłącznie nową gałąź oraz
[draft PR #25](https://github.com/luciferprosun/AIOA-spArkHAT/pull/25),
base `AIOA-METAGuardiansSPARK`, początkowy head32724a1. Późniejszy push
uzupełnia wyłącznie ten handoff. Nie wykonano merge ani push do main/bazy.
API GitHub po publikacji kodu i utworzeniu PR zwróciło0 workflow runs dla
nowej gałęzi. **Actions pozostaje NOT_RUN**, nie GITHUB_ACTIONS_PASS.
Wszystkie nowe commity zawierają `[skip ci]`; sprawdzono istniejące workflow
bazy/main: automatyczne zdarzenia dotyczą wyłącznie main, bez
pull_request_target/create/workflow_run. Nowy workflow pozostaje dispatch-only.

Zdalna `AIOA-METAGuardiansSPARK` wskazuje
`0741d37db0630233b4e7212f6f3af6320106c792`, czyli12 lokalnych commitów/93 pliki
przed bazą N1. Push nowej gałęzi zachowa je w historii. Nie jest to PR
obejmujący wyłącznie narzędzia w porównaniu ze zdalną gałęzią. Przeskanowano
również historyczne blob-y:3 dopasowania Bearer to jawne testowe literały
injection/error-redaction; jedyny odziedziczony binarny dodatek to oryginalny
wrapper43705 B z oficjalnym SHA256 i zachowaną licencją Apache-2.0.

Zakres **nowych zmian tego zadania**, względem6216b16:
`scripts/android/{__init__.py,toolchain_lib.py,installer.py,toolchain_doctor.py,toolchain.lock.json,install_toolchain.sh,env.sh,build_apk.py,build_apk.sh,verify_apk.py,ci_build.py,README.md}`;
`tests/{test_android_toolchain_guards.py,test_android_toolchain_cli.py,test_android_build_verification.py,test_android_manual_workflow.py,test_android_review_regressions.py}`;
`.github/workflows/android-manual-build.yml`;
`docs/android-toolchain/{G0_BASELINE.md,G1_STORAGE_DECISION.md,G4_GITHUB_ACTIONS_RUNBOOK.md,ARCHITECTURE_AIOA_COMPANION_V2.md,ADR_001_SINGLE_RUNTIME_COMPANION_V2.md,G7_REVIEW_DISPOSITION.md,FINAL_HANDOFF_20261031.md}`;
`docs/design/COSMIC_ASSET_MANIFEST_V1.md`. Dokładna lista i hashe są w końcowym
evidence. Żaden istniejący plik klienta/protokołu/runtime nie został zmieniony.

## Pozostałe czynności człowieka i rollback

Najpierw niezależny odbiór dysku albo osobny świadomy wybór CI. Następnie
kwalifikowany natywny HTTPS edge i rzeczywisty owner admission, build/podpis,
osobna zgoda na instalację Xiaomi i test pairingu/readback/UNKNOWN/STOP.
Tailscale Serve/ACL/public bindingów nie zmieniono. Telefon nie ma Run,
approval, budżetu, Git WRITE ani klucza modelu. Grafiki i coding demo
pozostają specyfikacją. Instrukcje sieciowe N1:
`docs/meta/mobile/XIAOMI_13T_PRO_SETUP_PL.md`; ograniczenia zachowane.

Lokalnie niczego nie instalowano, zatem nie ma nowego toolchainu do usunięcia
z LSC_DATA3. Nie wykonywać `rm -rf`, reset, clean ani kasowania cudzych cache.
Kod można wycofać na **tej izolowanej gałęzi** odwracając wyłącznie jej nowe
commity w odwrotnej kolejności przez `git revert --no-commit`, po potwierdzeniu
czystego statusu oraz zgodności HEAD z końcowym evidence. Dokładne polecenie
z pełnymi hashami jest w prywatnym `ROLLBACK_OWN_COMMITS.txt`, a lista w
`TOOLCHAIN_FINAL_EVIDENCE.json`; nie używać zmiennego HEAD jako skrótu do
nieznanych późniejszych zmian. Zestaw nie obejmuje12 commitów
odziedziczonych N1/P02/P03. Nie cofać bazy6216b16, ledgera lub UNKNOWN.
Jeżeli powstał draft PR, pozostawić go bez merge lub zamknąć w odrębnej
czynności właściciela. Gałąź, worktree i prywatne dowody są zachowane.

Prywatne dowody (0700/0600):
`/home/l/projects/ANDROID_TOOLCHAIN_PRIVATE_20261031/G_20261031T224359Z/`.
Zawierają progress, źródłowe hashe, metadata wydawców, RED/GREEN, surowe
logi testów, zasoby, review i `TOOLCHAIN_FINAL_EVIDENCE.json`. Nie dodawać
ich do publicznego repozytorium ani nie kopiować kluczy/baz do artefaktów.

**BLOCKED_LOCAL_APK_BUILD — OFFLINE_TOOLING_AND_SPECS_DELIVERED — NO_ANDROID_E2E.**
