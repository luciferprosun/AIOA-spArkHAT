# Android post-merge A11–A20 — raport właścicielski, 2026-11-01

**Wynik: BUILD_BLOCKED_OWNER_GATE. APK_NOT_BUILT.**
**CodeQL Kotlin: CODEQL_KOTLIN_BLOCKED — przygotowany patch, brak rzeczywistego nowego analyze.**

## Źródło i zakres

Repo: https://github.com/luciferprosun/AIOA-spArkHAT.
Potwierdzony main/base: `ad5ae30494b9844e0433ffb1712254b781b3fa77`
(PR #27), tree `dda2cbb2047c35df79b8eb1833453ec1b67d689b`.
Gałąź lokalna: `codex/android-postmerge-apk-20261101`.
Code head po poprawkach review: `e1a93ad7894183d0f715b069d6e85d4831e87045`.
Niezależny review obejmował head `6e859ba4864ac7368c41905831e44cad159a59e2`;
następnie autor zamknął pięć Important testami RED→GREEN, bez drugiego review.
Końcowy head/tree i SHA patcha są zapisane w prywatnym OWNER_GATE.json;
nie wpisujemy do pliku jego własnego przyszłego commitu.
Nowy PR: **NONE**. Push/merge/security migration/dispatch: **NOT_EXECUTED**.

To jeden dodatkowy patch w kanonicznym repo. Brak zmian w `runtime/`,
`clients/android/`, providerach, chronionych usługach, dawnych branchach
Nebius/Muse/GOLD72, ustawieniach Tailscale i kwalifikacji dysków.
Poprzednie 19 checkoutów, 185 publicznych dirty plików i pięć chronionych
procesów zachowano. 38 prywatnych/niebezpiecznych pozycji manifestu nie
odczytywano. Critical capsule76 pozostaje
`2d587c399a4cba5342182bea7f17a7c3ea1dfe6775c1ccc6d938077aba642dfa`.
Manifest Android:
`c86e49f9a33985e152ebf85a398b5d4df3fe101eb122480d06bcdc467a154b35`.

## Co przygotowano

| Faza | Stan i dowód |
|---|---|
| A11 | Świeży main, jeden izolowany writer, baseline i prywatne statusy/seals |
| A12 | Istniejący manual workflow + helper wymagają exact main SHA, workflow bytes/revision, ownera, attempt1 i faktycznego obrazu; branch drift odmawia przed/po efekcie |
| A13 | Oficjalne piny Node24, dokładne JDK/SDK/Gradle, bounded zasoby; [supplier evidence](A13_SUPPLY_CHAIN.md) |
| A14 | Opcjonalny init(manual) → prawdziwy compileDebugKotlin przez trace-command → analyze → SARIF readback; aktualne cztery grupy języków zachowane w gated advanced config. NIE URUCHOMIONO |
| A15 | Ten sam builder test/lint/assemble, świeży prywatny signer DEBUG, porównanie certu, bounded copy oraz niezależny aapt/apksigner/sha256sum i raporty. APK/JVM NIE URUCHOMIONO |
| A16 | Istniejący ES256/session/nonce/UNKNOWN/STOP bez zmian; [projekt edge i odbiór Xiaomi](EDGE_AND_XIAOMI_ACCEPTANCE.md), remote owner/TLS NOT_BOUND |
| A17 | Targeted RED→GREEN, regresje i końcowy niezależny review; wyniki poniżej |
| A18 | Lokalne logiczne commity, gotowy patch/PR body, bez publikacji |
| A19 | Ten raport + prywatny JSON, patch, logi, review i jeden owner gate |
| A20 | Lokalna implementacja przygotowana; build i fizyczny telefon pozostają niewykonane |

Zmiany: `.github/workflows/android-manual-build.yml`, nowy
`.github/workflows/codeql-static.yml`, `scripts/android/ci_build.py`,
`scripts/android/build_apk.py`; testy Android manual/postmerge/CodeQL/signer
i naprawa atomowego PID-ready w testowej fixture supervisora; dokumenty
A11/A13/A16, niniejszy raport i plan. Pełną listę daje
`git diff --name-only ad5ae30494b9844e0433ffb1712254b781b3fa77..HEAD`.

## Testy i ograniczenia dowodów

| Zestaw | Wynik rzeczywisty | Zakres |
|---|---|---|
| Android tooling/CI po review | 83/83 PASS, 89 subtests, 4.161s | Offline; keytool/aapt/apksigner/Gradle/CodeQL zastąpione fixture w testach kontraktu; realny sha256sum na fixture i proces modelujący fallback cwd CLI |
| Core/warrant/intent/effects/MCP/unified | 202/202 PASS, 255 subtests, 160.215s | Izolowane procesy i prywatne testowe storage, bez provider API |
| Mobile wire/gateway/HTTP/source/doctor | 77/77 PASS, 35 subtests, 41.140s | Podpisy i odczyty lokalne; brak urządzenia Android |
| Node UI | 15/15 PASS, bez skip | Rzeczywiste kontrakty JS i source checks UI |
| Host native | 42/42 PASS, 28 subtests, 157.682s | Izolowane własne katalogi/cgroups, bounded READ/WRITE/Git/STOP/restart; nigdy produkcyjny owner |
| Kotlin JVM / lint / assemble / Android15 / HyperOS2 | NOT_RUN | Nie wolno zastąpić ich liczbą testów Python/JS |

Surowe RED i nieudane próby są zachowane. Pierwszy run Core miał jeden
błąd selektora (`test_core_admission` nie istnieje), 136 realnych testów PASS;
poprawiony pełny wybór dał 202/202. W pierwszym Android run wykryto race
testowej publikacji PID; naprawiono atomic rename, bez zmiany supervisora.
RED pokazał też brak powiązania własnego signera/kopii, NameError przy
raporcie wersji i pustą provenance SARIF; końcowy GREEN obejmuje poprawki.
Żaden mockowany sukces nie oznacza skompilowanego APK.

Razem:419 wykonanych przypadków i407 subtests, bez skip. Zestawy runtime
przeszły na `25235e1`; po review zmieniły się wyłącznie CI/helper/testy/dokumenty,
bez zmiany któregokolwiek z76 zapieczętowanych źródeł Core/mobile.

Niezależny reviewer: `/root/review_android_postmerge_final_20261101`,
GPT-6 Astra max, tryb read-only. Werdykt oryginalny: **With fixes**,0Critical,
5Important,1Minor. R1: jawny working-dir Android dla trace-command; R2:
upload-database:false; R3: filtrowany failure JSON; R4: opcjonalna provenance
SARIF + rzeczywisty analyze sarif-id i pending server readback; R5: tygodniowe
skany czterech grup. Wszystkie Important zamknięto w jednej serii autora:
RED7 (5fail/3errors) → GREEN83; dodatkowy RED brakującego upload ID → GREEN.
Nie nazywamy tego ponownym PASS reviewera. Reviewer nie uruchamiał JVM/CI.
Prywatne REVIEW_RESULT.json i AUTHOR_REVIEW_RESPONSE.md zachowują ustalenia.

Minor M1 odroczony: exact ImageVersion obowiązuje także automatyczny SAST.
Zmiana hosted image zatrzyma skany przed analizą, dopóki pin nie otrzyma
nowego review. To koszt utrzymania fail-closed, nie gwarancja ciągłej analizy.

## Faktyczny CodeQL i wymagane ustawienie

Obecny default setup nadal `configured`, query_suite `default`, threat_model
`remote`, runner `standard`, schedule `weekly`. Cztery grupy: actions,
c-cpp, javascript-typescript, python (API zwraca też aliasy javascript/typescript).
`AIOA_CODEQL_PROFILE`: NOT_SET. Niczego nie wyłączono ani nie zmieniono.

[Run41303106848](https://github.com/luciferprosun/AIOA-spArkHAT/actions/runs/41303106848)
na main ad5: FAIL, job124837962048, finalize exit32/build-mode:none.
ForceDependencyResolutionPlugin nie skompilował Kotlina. Dotychczasowy
czterojęzykowy run41303090382 był PASS. Nowa analiza Kotlina: NONE.

Przygotowana migracja po osobnym GO:

1. Najpierw push jednego patcha i jeden PR do wskazanego base. Default setup
   działa podczas review; możliwe automatyczne skany PR/merge są osobnym
   skutkiem zgody. Żaden push/PR nie uruchamia Android builda.
2. Po zatwierdzonym exact head/base i sprawdzeniu merge tree w main utworzyć
   repo variable `AIOA_CODEQL_PROFILE=advanced-v1` (obecnie brak).
3. Zamienić default setup na przygotowany advanced. Efekt API to
   `PATCH /repos/luciferprosun/AIOA-spArkHAT/code-scanning/default-setup`
   z `{"state":"not-configured"}`. Jest to security OWNER GATE, nie
   wykonana operacja ani zgoda na pozostawienie repo bez skanowania.
4. Ten sam jeden zatwierdzony dispatch uruchamia APK, potem Kotlin manual
   i reusable SAST dla dotychczasowych czterech grup. Upload SARIF dostaje
   `security-events:write` tylko w jobach CodeQL; APK pozostaje contents:read.
   Kolejne push/PR oraz harmonogram poniedziałek03:17UTC w advanced skanują
   cztery grupy; Kotlin wymaga osobnego
   manualnego odbioru, bez automatycznej kompilacji Androida.

GitHub wymaga zastąpienia default setup dla własnych uploadów advanced;
[oficjalna instrukcja przejścia](https://docs.github.com/en/code-security/how-tos/find-and-fix-code-vulnerabilities/configure-code-scanning/configuring-advanced-setup-for-code-scanning)
i [API ustawień](https://docs.github.com/en/rest/code-scanning/code-scanning#update-a-code-scanning-default-setup-configuration).
Zmiana nie jest atomowa z workflow. Przy braku/niepewnej odpowiedzi:
odczytać stan; nie wysyłać w ciemno kolejnej mutacji.

## Dokładny plan jednego buildu — DRY RUN

Workflow: `.github/workflows/android-manual-build.yml`, id403351712,
`workflow_dispatch`, ref `main`, actor+triggering_actor `luciferprosun`, attempt1.
Źródło: faktyczny SHA zaakceptowanego przyszłego merge. Musi mieć tree
identyczne z końcowym reviewowanym lokalnym HEAD, nadal być HEAD main,
oraz odpowiadać GITHUB_SHA i GITHUB_WORKFLOW_SHA. Nie znamy przyszłego
merge SHA; nie podstawiamy ad5 (nie zawiera poprawek) ani starego N1.

Reviewed ImageVersion: **20261026.354.1**.
Workflow SHA256:
**ef7fb9e6e4edcd610e316c46a20feddfe3c44649aebbc62f2f3c1d4573be1c4c**.
Dowolny inny rzeczywisty obraz kończy próbę przed checkout/setup/build.
Nie wystarczy zmienić tekstowego inputu. Hosted label ubuntu-24.04 może
zostać przeniesiony na inny obraz; nie ma automatycznego retry.

Payload do `POST /repos/luciferprosun/AIOA-spArkHAT/actions/workflows/403351712/dispatches`:

```json
{
  "ref": "main",
  "inputs": {
    "expected_source_sha": "ACTUAL_APPROVED_MERGE_SHA_40_HEX",
    "expected_runner_image": "20261026.354.1",
    "expected_workflow_revision": "ef7fb9e6e4edcd610e316c46a20feddfe3c44649aebbc62f2f3c1d4573be1c4c",
    "approve_run": false,
    "sdk_license_ack": false,
    "artifact_exposure_ack": false,
    "enable_codeql": false,
    "codeql_settings_ack": false
  }
}
```

Pola false oznaczają brak udzielonej zgody. Dopiero jawne GO obejmujące
każdą bramkę pozwoli ustawić je true; nie akceptujemy licencji za ownera.
Najpierw prywatny zapis exact payload/time/sha i DISPATCH_PENDING; jeden
POST, potem readback workflow runs (workflow, event, main SHA, actor, czas)
i trwałe powiązanie run ID. Utrata ACK/204 bez ID/niejednoznaczność →
UNKNOWN, tylko GET/list/readback, bez kolejnego dispatch/re-run attempt2.

Kwalifikowany runner wykona istniejące:

```text
cd clients/android
./gradlew --no-daemon --max-workers=1 testDebugUnitTest lintDebug assembleDebug
```

Rzeczywista komenda helpera dodaje wyłączenie auto-download SDK/JDK,
prywatne output/cache/init, ograniczenie JVM i weryfikację wersji/integralności.
Jeden Gradle worker, no-daemon, 35min job / 1800s proces, 8MiB log limit.
JDK17.0.21+9, Gradle8.13, SDK36rev2, buildtools35.0.0,
cmdline22.0, Kotlin2.2.21, AGP8.11.1. Brak lokalnej instalacji/WD writes.
Zależności Maven/Gradle pozostają ONLINE_VENDOR_REPOSITORIES_NOT_FULLY_HASH_LOCKED.

## Ekspozycja i odbiór APK

Publiczne repo oznacza dostęp do artefaktu dla osób mających dostęp do runu.
Retencja: 1 dzień, missing-files:error, bez hidden files/overwrite/cache.
Publikowane tylko `aioa-companion-debug.apk`, filtrowany `APK_EVIDENCE.json`
i osobny ograniczony `CODEQL_EVIDENCE.json`; przy porażce wyłącznie osobny
`BUILD_FAILURE_EVIDENCE.json` z retencją1d, bez APK. Failure JSON zawiera etap,
exit/status, hashe logów i ograniczone rozpoznane publiczne lokalizacje/kategorie
kompilatora. Nieznane wyjście: DIAGNOSTIC_UNAVAILABLE, bez eksportu raw tekstu.
Nie publikujemy debug.keystore,
prywatnego DEBUG_SIGNER.json/cert-key binding, pełnych logów/cache, tokenów,
operator sessions, enrollment code, danych Tailscale ani prywatnych dowodów.
SARIF to osobny wynik Code Scanning, bez raw SARIF w artefakcie.
Upload bazy CodeQL jest jawnie wyłączony we wszystkich krokach analyze.
Same logi Actions mają własną retencję GitHub i nie znikają po jednym dniu.
Raw prywatny build.log jest efemeryczny; trwale zachowujemy tylko ograniczony
failure JSON/hash, nie obiecujemy odzyskania pełnego logu po usunięciu runnera.

Po realnym SUCCESS wszystkich wymaganych jobów: odczytać run head SHA,
ImageVersion/versions i status uploadu; pobrać artifact przez `gh run download
RUN_ID --repo luciferprosun/AIOA-spArkHAT --name aioa-companion-debug-SHA-1`
do nowego prywatnego katalogu na zakwalifikowanym dysku. Weryfikować hash
ZIP/artefaktu GitHub oddzielnie od SHA-256 APK, następnie sha256sum,
aapt badging, apksigner, cert fingerprint i wszystkie pola JSON.
Brak zgodności lub źródła → odrzucenie, nie instalacja.

Readback Kotlin CodeQL używa `server_sarif_id` z rzeczywistego outputu kroku
analyze. Odczytać `GET /repos/luciferprosun/AIOA-spArkHAT/code-scanning/sarifs/ID`,
wymagać processing_status=complete, następnie pobrać zwrócone analyses_url
i sprawdzić commit_sha=zaakceptowany merge, ref main, kategorię java-kotlin,
tool/version, brak błędu i powiązanie z runem. Analogicznie odebrać cztery
pozostałe analizy i statusy wszystkich jobów. Nie podążać za obcą domeną/URL
z danych bez walidacji. [Oficjalny kontrakt readback](https://docs.github.com/en/rest/code-scanning/code-scanning#get-information-about-a-sarif-upload).
Lokalny JSON ma zawsze server_upload_verified:false oraz
PENDING_SERVER_COMMIT_SHA_READBACK aż do tego niezależnego odbioru.
Brak opcjonalnego versionControlProvenance w SARIF nie tworzy fikcyjnej
provenance; sprzeczna obecna wartość nadal odmawia.

Oczekiwany pakiet: eu.sparkhat.aioa.companion, versionCode2 / 0.2.0-n1,
min26, target36, jedyne permission android.permission.INTERNET, debuggable.
Signer jest świeży na run: zgodność aktualizacji starego APK UNKNOWN.
Nie wykonano adb install, odinstalowania ani migracji danych.
Instalacja, nowy Keystore P-256, HTTPS/enrollment i Wi-Fi/LTE to osobny P1.

| Pole dowodu faktycznego | Stan teraz |
|---|---|
| Android build run ID/link | NONE |
| APK/artifact SHA256/rozmiar | NONE |
| Faktyczny signer/cert fingerprint | NONE |
| Rzeczywisty JVM JUnit count/lint/assemble | NOT_RUN |
| Source APK | NONE |
| Native production owner/TLS edge | NOT_BOUND |
| Xiaomi Android15/HyperOS2/E2E | NOT_RUN |
| Płatne wywołania modelu | 0 |

## Co można uruchomić teraz

Istniejący zweryfikowany Core w lokalnym profilu offline:

```bash
cd /home/l/AIOA_LOCAL_WORKTREES/one-aioa-main-verified-20261101
python3 -B -m runtime.webapp --unified-offline --host 127.0.0.1 --port 0
```

Wyświetlony loopback URL służy UI; port0 nie zajmuje chronionych portów.
To SYNTHETIC_OFFLINE_FIXTURE: lokalny bounded efekt/readback działa,
model nie jest wywoływany, owner produkcyjny NOT_BOUND. Nie jest to
komenda parowania telefonu ani prawdziwe połączenie Muse LIVE.

## Ryzyka, rollback i jedna decyzja

| Ryzyko | Granica i rollback |
|---|---|
| Hosted image drift | Stop przed setup; aktualizacja reviewowanego pina/testów wymaga nowej decyzji, nie podmiany inputu |
| Pierwsza kompilacja ujawni błąd Kotlin/lint | BUILD_FAILED_REAL, run i filtrowany failure JSON; raw log efemeryczny; brak automatycznej kolejnej próby |
| Advanced migration lub SARIF fail | Nie usuwać wyników; wyłączyć nowy profile variable i przywrócić poprzedni configured/default/remote/standard/weekly/four-language setup. Restore może wywołać skan i wymaga zgody |
| Świeży DEBUG cert | Nie nadpisywać starego APK ani danych; fizyczna instalacja osobno |
| Własne dependency/SDK/Supplier trust | Piny/archiwalne hashe i runtime inventory; brak twierdzenia o pełnym Maven lock lub niezależnej weryfikacji każdego bajtu obrazu/CodeQL cache |
| Edge/owner niegotowy | Nie zmieniać fixture; zachować REMOTE_DEPLOYMENT_BLOCKED, osobny odbiór P1 |

Przed publikacją rollback to zachowanie tej gałęzi/patcha i używanie main
ad5 — bez reset/clean/stash cudzych zmian. Po merge tylko nowy reviewowany
revert naszych plików; nie resetować Core ledger, approvals, UNKNOWN ani
źródłowych worktree. Nie usuwać prywatnych dowodów.

**Jedno żądanie GO** (dokładny końcowy head/base w OWNER_GATE.json):
push tej jednej gałęzi, jeden PR i merge wyłącznie reviewowanego exact head
do niezmienionego ad5; akceptacja możliwych automatycznych skanów PR/merge;
opisana migracja CodeQL/default→advanced i jeden workflow_dispatch z
weryfikacją drzewa/SHA/obrazu; owner akceptuje Actions billing/limity,
vendor network, rzeczywiste [warunki SDK](https://developer.android.com/studio/terms),
publiczny DEBUG APK/ograniczone evidence, także failure JSON, z retencją1d,
przyszłe automatyczne SAST push/PR/tygodniowe oraz warunkowy restore
poprzedniego CodeQL bez ponowienia Android builda.

GO nie obejmuje model/API spend, telefonu, produkcyjnego ownera,
Tailscale/Serve/Funnel/ACL, publikacji UI ani usług 4314/4315/4316/4321.
Bez tej decyzji: **BUILD_BLOCKED_OWNER_GATE / APK_NOT_BUILT**.

## Decyzje autora i koszt

| Decyzja | Koszt/granica |
|---|---|
| Samodzielne decyzje projektu zgodnie z mandatem PDF, jeden końcowy review | Architektura wymagała niezależnego sprawdzenia; brak dodatkowych menu zgody na lokalny kod |
| Zachować prywatne dowody i worktree | Zajętość dysku; bez ich publikacji/usuwania |
| Exact oficjalny obraz26.354.1 | Pierwsza próba i przyszły SAST mogą odmówić po image drift; Minor M1 pozostaje odroczony |
| SARIF write tylko w osobnych owner-gated jobach | Dodatkowe joby i jawna migracja security settings |
| Curated env + oficjalny trace-command | Brak dziedziczenia tokenów; rzeczywista instrumentacja nadal NOT_RUN |
| Jeden dispatch APK + reusable cztery grupy i osobny Kotlin compile | Więcej hosted jobs/network; brak drugiego APKbuildera/Core |
| Edge tylko zaprojektowany do czasu autentycznego owner/TLS | APK sam nie sparuje telefonu; P1 pozostaje zablokowane |
| Targeted regresje i zachowanie gałęzi zamiast ogólnego cleanup/menu/full20min | Nie powtórzono całego historycznego suite eksperymentów; zachowano źródła/dowody |
| Source/upload CodeQL pending do APIreadback rzeczywistego sarif-id/commit_sha | Sam lokalny SARIF nie zamyka bramki i nie stanowi atestacji serwera |
