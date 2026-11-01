# AIOA spArkHAT / METAGuardiansSPARK — PROMPT 03 FINAL

Data: 2026-10-31. Zakres: lokalna implementacja i testy z `Muse_Prompt_03_FINAL_2026-10-31.pdf`. P01/P02 zachowano, nie powtarzano portu ani audytu całego systemu.

## Werdykt i rozdzielenie dowodów

**OFFLINE_INTEGRATED. One Core / One UI: PASS.** Istniejący runtime.webapp prowadzi zadanie, plan mock, dokładne zatwierdzenie fixture, Core warrant, READ fixture, wynik/hash/correlation/receipt oraz STOP. Domknięto R6 i dodano host-only binding istniejącej authority; nie dodano drugiego Core, approval engine, bazy lub głównego frontendu.

| Funkcja | Poziom | Stan |
| --- | --- | --- |
| Model advisory → Core → browser fixture → evidence/STOP | OFFLINE_TESTED | PASS; jedna istniejąca aplikacja |
| R6 durable receipt/UNKNOWN/restart/integrity | OFFLINE_TESTED | PASS na rzeczywistych klasach Core i syntetycznym HTTPS; rzeczywisty API receipt w tej sesji: none |
| Meta API provider/native host port | OFFLINE_TESTED | Wpięty/testowany; rzeczywisty model **BLOCKED_EXTERNAL**: owner admission + Billing + exact GO nie dostarczono |
| Chrome renderowanie istniejącego UI, fixture Run/STOP/scroll | LOCAL_UI_BROWSER_TESTED | Prawdziwy własny Chrome w networkless bwrap; prawdziwy PNG i hashe |
| Publiczny Chrome research READ | BLOCKED_EXTERNAL | Brak zatwierdzonego kontrolowanego egress/drivera i exact origin GO; nie wykonano |
| Android E2E/Companion | DEFERRED | Brak fizycznego telefonu/audytowanego portu misji; gateway tasks/chat/stop=false |
| Nebius/Nemotron | REUSED / OPTIONAL_PROVIDER | Istniejący provider/router zachowany; brak fallbacku Meta→Nebius i brak wywołań płatnych |
| Film/publikacja/push/zgłoszenie | BLOCKED_EXTERNAL | Scenariusz przygotowany; niczego nie nagrano ani nie wysłano |

Nie ma podstaw do `META_LIVE_VERIFIED`, `CHROME_LIVE_VERIFIED`, `ANDROID_E2E_VERIFIED` lub `AGENT_READY`. Lokalny Chrome UI nie jest publicznym browser READ, a native-shaped mock nie dowodzi odpowiedzi modelu Meta.

## G0 — checkpoint i ochrona pracy

TARGET `/home/l/projects/AIOA-spArkHAT-META`; branch `AIOA-METAGuardiansSPARK`; origin `https://github.com/luciferprosun/AIOA-spArkHAT.git`. Start: **44bf1628b92a2e6e424135fcdf8076ba635054e9**, worktree/index czyste. Metadane procesów Codex/Muse sprawdzono bez odczytu ich argv/env; nie wykryto procesu o cwd TARGET ani obcych zmian w checkoutcie. Parent pozostaje jedynym writerem. Reviewer czyta wyłącznie prywatny snapshot.

P01: `5d0c62d`, `34490b9`; P02: `0c2ada5`, `c0d535a`, `6fe6846`, `44bf162`. REUSED. Baseline P03: 228 Meta PASS. Kod AIOA/Nebius ma zachowane pochodzenie październikowe, źródła read-only.

Prywatny katalog dowodów i kopii (0700): `/home/l/projects/META_INTEGRATION_PRIVATE_20261031/P03_20261031T163047Z`. Zawiera manifesty przed/po, kopie 9 wybranych plików, source/code seals, RED/GREEN, review oraz odrębne katalogi każdej próby HTTP/Chrome. Nie kopiowano prywatnej bazy użytkownika, klucza, cookies, APK ani całego repo do publicznych artefaktów. Standardowy Codex/Muse config, source worktree, Companion, Nemotron, GOLD72 i chronione usługi pozostają bez zmian.

## G1 — R6, authority a obserwacja wyniku

`runtime/providers/meta_receipts.py` jest wąskim portem do **istniejącego scoped TransactionRunner/OPERATION/RECEIPT**, nie nowym ledgerem uprawnień. Jednoznaczna immutable attempt identity i CAS blokują powtórzenie tego samego requestu. Record observations ADMITTED/IN_FLIGHT/COMPLETED/FAILED/UNKNOWN/STOPPED nie mogą zatwierdzić, zarezerwować, rozliczyć lub wznowić efektu.

Admission sprawdza dokładne zapisane owner approval, principal/session/scope/model, warrant/nonce, task/source SHA/capsule, policy epoch/expiry oraz istniejącą rezerwację przed odczytem klucza. Core consume i governor dispatch-commit/UNKNOWN hold następują przed pojedynczym HTTPS. Nie obiecujemy atomowości storage + HTTP ani automatycznego refundu. Każdy błąd ACK przed dispatch blokuje wysłanie; po niepewnym wyniku nie ma retry.

R6 odczytuje rekordy przez Core READ i weryfikuje scope/source/capsule/model/attempt/correlation, approval/consumption, nonce, reservation/epoch, receipt i usage. Pending po utracie procesu projektowany jest jako UNKNOWN. Uszkodzone/niezgodne lub niedostępne dowody nie są wyświetlane jako zweryfikowany receipt. Model response/error body, Authorization, prompt i klucz nie są zapisywane. Nowe pola są addytywne: `call_state`, `billing_status`, `credits_confirmed`, `last_attempt`, `last_live_receipt`, `cost_estimate`, `settled_cost`, `budget_ledger_state`; zachowano `last_api_receipt` i pola P02.

Po review granica projekcji ma zamknięte pola/typy/koszty: dodatkowy poufny payload lub niepoprawny koszt nie może wyciec nawet podczas UNKNOWN. Najnowsza próba i ostatni poprawny receipt są odczytywane niezależnie: nieudane B nie usuwa dowodu wcześniejszego A ani nie autoryzuje retry B. Native spend ma jawny kontrakt **META_MODEL_PLAN_V2** z commitmentem public binding (także correlation/origins/token/timeout bounds). V1 nie jest reinterpretowane jako V2; stara zgoda wymaga nowego dokładnego zatwierdzenia, a nie migracji uprawnień. Zaktualizowano odpowiednie syntetyczne fixtures `test_meta_model_api.py` i testu hosta, bez osłabiania dotychczasowych asercji. READ fixture/MCP/HTTP P01/P02 pozostają zgodne. Ceiling musi mieć walutę USD.

COMPLETED opisuje odpowiedź modelu; nie oznacza settlement, nowego spend permission lub ukończonej misji browser. `billing_confirmed` w native binding jest zaufaną deklaracją hosta, nie odczytem salda. Brak niezależnego Billing readback utrzymuje **UNVERIFIED / credits_confirmed=false / settled_cost=null**. W tej sesji rzeczywisty API attempt: NOT_ATTEMPTED, prawdziwy receipt: none.

## G2 — jeden model provider i istniejący Core

W istniejącym `MetaModelProvider` zachowano `muse-spark-1.3`, Chat Completions, dokładną schemę i pojedynczy request, bez silent fallbacku. `ProviderManager.generate_meta_plan` pozostaje jedynym typowanym portem modelu w kompozycji. DISABLED domyślnie, MOCK w zwykłej demonstracji; OfflineMuseProvider nie dostał sieci.

`MissionService.bind_live_request` przyjmuje wyłącznie istniejące, już zatwierdzone native Core binding i dokładny MetaPlanRequest. Nie tworzy ownera, rezerwacji lub warrantu. HTTP/model nie może go skonstruować. Po binding zmienia się preview digest i wymagany jest jawny Run z intentem `meta-run-approved-v1`; dotychczasowy fixture intent zachowano. Restart nie odtwarza efemerycznej zdolności do dispatch. Maksymalnie jedna aktywna misja, także w LIVE_PENDING_AUTHORIZATION.

Po poprawnym model response host czyta trwały receipt z Core. **Nie uruchamia browser fake pod etykietą LIVE.** Bez osobnej, autoryzowanej i izolowanej ścieżki READ misja ma BLOCKED/CHROME_LIVE_BLOCKED_CONTAINMENT, nawet jeżeli samo wywołanie modelu się zakończyło. Native host rzeczywiście skonfigurowany do płatnego wywołania nie jest dostępny w obecnym launcherze; `--meta-live-one-shot` nadal wyłącznie raportuje brakujące bramki i api_calls=0.

## G3 — Linux Chrome, izolacja i ograniczenia

Nowy `runtime/browser_agent/chrome_process_read.py` używa istniejących `/usr/bin/bwrap` i `/opt/google/chrome/chrome`. Bez instalacji, firewall changes, sudo i `--no-sandbox`. Supervisor ma bounded stdout/stderr, deadline/cancel i reaping wyłącznie własnej grupy procesu. Nie przyjmuje PID-u/DevTools endpointu cudzej sesji, nie wystawia click/type/upload/execute.

Worker uruchamia jeden istniejący WebRuntimeService z fixture Core w odrębnych user/PID/network/mount namespaces, z cap-drop ALL, pustym HOME, ro-bind wybranych katalogów kodu i bez `.git`, sekretów, danych użytkownika lub osobistego profilu. Przed Chrome sprawdza inny netns, wyłącznie loopback, brak tras, brak HOME właściciela i brak capability; test połączenia do adresu dokumentacyjnego jest odrzucony przez kernel bez trasy. To rzeczywiste OS containment **bez sieci zewnętrznej**, nie sam Python URL filter.

Supervisor nadal sprawdza STOP po EOF. Linux WNOWAIT zachowuje PID lidera do sprzątnięcia własnej grupy TERM/KILL i reaping, także po wyjściu lidera; test sprawdza zakończenie potomka trzymającego pipe. Kapsuła obejmuje27 wybranych plików, w tym governor, cancellation, warrant i persistence/serialization. Nie jest to atest całego systemu operacyjnego ani wszystkich zależności Pythona.

Wykonano lokalny browser test: prawdziwe renderowanie istniejącego HTML/JS, Preview/Run/evidence, STOP, scroll i PNG większy niż 1×1. Testowy handler wstrzykuje tylko statyczny JS automatyzujący te lokalne czynności; zwykła aplikacja go nie serwuje jako własnego kontrolera. Pierwsza próba UI ujawniła błąd harnessu z przekazaniem wspólnego service do handlera; zachowano failed artifact, poprawiono po RED i ponowiono z wynikiem PASS.

Próba po review wykryła też rozjazd przyspieszonego czasu Chrome i rzeczywistego cancellable delay fixture: test kończył oczekiwanie przy RUNNING. Zachowano timeout/failed artifact. Stały probe testowy synchronizuje oba zegary przez namespace-local endpoint `/p03-local-clock`; zwykły serwer nie wystawia tej ścieżki. Nie zwiększano statusu do DONE ani nie usuwano kontroli Core. Niezależny HTTP test i regresje potwierdzają zachowanie aplikacji poza tym testowym zegarem.

Wąskie okno: żądany screenshot 390×844, **rzeczywisty CSS viewport Chrome 500×757** (minimalna szerokość desktopowego headless). Szerokie: PNG1280×900, CSS1280×813. Potwierdzono scroll i brak poziomego overflow w tych obserwowanych viewportach, bez udawania emulacji Androida390 lub fizycznego telefonu.

Public `navigate_read` w nowym driverze pozostaje fail closed. Networkless namespace nie zapewnia zatwierdzonego dostępu do Internetu; do public READ brakuje kontrolowanego egress/DNS rebinding/redirect/subresource/WS/SW/download enforcement i osobnej zgody na domenę. Dotychczasowy ChromeReadAdapter/fake i polityki P01/P02 są zachowane. MCP ALLOW nie daje native execution.

## G4/G5 — jedno UI i mapa migracji

Ten sam `runtime/webapp.py` i `web/{index.html,app.js,meta_mission.js,styles.css}`: exact preview/Run, osobny native intent, STOP, evidence, R6, approval/correlation/origin/budget/digest i jawne UNKNOWN/BLOCKED. Brak modelowego owner override, otwarcia publicznego portu lub drugiej aplikacji frontend-v2. Sesja loopback jest ochroną transportu UI, nie produkcyjnym owner admission dla LIVE.

54 source paths z faktycznymi SHA-256 i decyzjami REUSED/ADAPTED/OPTIONAL_PROVIDER/DEFERRED/EXCLUDED: [P03_FINAL_SOURCE_MAP_20261031.md](P03_FINAL_SOURCE_MAP_20261031.md). Zachowano MIT notice. Dla nieimportowanych repo licencja UNKNOWN jest oznaczona jawnie. Companion przeczytano read-only; jego ES256/pairing/M12 transport nie jest gotowym portem tasks/stop/evidence do tego UI. Nie dopisano drugiej authority ani deklaracji Android E2E.

## G6/G7 — testy, review, checkpointy i dowody

Komendy, rzeczywiste counts, RED/GREEN, ograniczenia i review: [P03_TEST_MATRIX_20261031.md](../../../reports/meta/P03_TEST_MATRIX_20261031.md). Source/capsule/hash/receipts i wskaźniki do prywatnych artefaktów: [P03_EVIDENCE_INDEX_20261031.json](../../../reports/meta/P03_EVIDENCE_INDEX_20261031.json). Końcowe wyniki i rozliczenie review są w sekcji zamknięcia poniżej; nie utożsamiamy mock z rzeczywistym API.

Niezależny reviewer przeczytał35 zapieczętowanych plików kopii zakresu44bf162..6b75518, bez dostępu do TARGET i bez uruchamiania kodu. Wynik: brak Critical, 5 Important, 2 Minor. Parent podniósł oba Minor do Important: nieprawdziwe „no paid calls/fixture” przy native operacji może zmylić zgodę człowieka, a pominięta waluta narusza finansowy scope. Wszystkie7 punktów zamknięto jedną rundą TDD RED→GREEN: redaction, binding commitment, niezależny last receipt, STOP/descendants, capsule dependencies, UI semantics i USD. Nie było ponownego niezależnego review końcowych bytes; końcowe poprawki i wykonanie testów zweryfikował parent. Deferred minors: brak.

Rozstrzygnięcia rzeczy odłożonych przez review: wyniki wykonania opierają się na świeżych próbach parenta, bez certyfikacji wykonania przez reviewera; Meta/Billing pozostają BLOCKED_EXTERNAL; publiczny Chrome również BLOCKED mimo lokalnego dowodu;500CSS nie oznacza390CSS ani Androida; końcowe G5–G7 sprawdza parent. Ich błędna interpretacja groziłaby odpowiednio zawyżeniem dowodów, nieautoryzowanym kosztem, SSRF/fałszywym LIVE, fałszywą deklaracją mobile lub błędnym handoffem. Prywatne dowody zachowano zgodnie z mandatem zamiast usuwać scratch skillu — błędna decyzja groziłaby utratą odtwarzalności.

Po commitach lokalny CLI/HTTP test używa tego samego serwera: status → Preview → EXACT Run → evidence → replay409 → kolejna misja STOP → nowa pending → restart → UNKNOWN i brak replay. Stary token sesji jest odrzucony. Własne subprocessy zakończone; cudzych sesji/usług nie zatrzymywano. Pełnego GOLD72, ciężkiego endurance, płatnych prób i deploymentu nie wykonywano.

Checkpointy lokalne:

1. `937bf0b151394b4fbc4d9b24260703f3a4bd7dcf` — R6, native host port, testy.
2. `6b7551826aebe805558b4a10e61b717e36196e20` — ten sam UI/API, networkless Chrome driver i testy.
3. Commit zawierający ten raport — końcowe poprawki review, dowody/mapa/runbook/demo. SHA ustala `git log -1 --format=%H -- docs/meta/migration/P03_FINAL_MIGRATION_REPORT_20261031.md`.

Nie zmieniano globalnego Gita, nie robiono reset/clean/stash/pull/rebase/merge/push. Dokładny End HEAD, clean status, source preservation i wyniki po ostatnim commicie zapisane są w prywatnym FINAL_VERIFICATION.json i raporcie terminalowym. Publiczne dowody opisują jawny source HEAD oraz working-tree seals z czasu próby; nie deklarują nieznanego w chwili zapisu SHA własnego commitu dokumentacji.

## Brakujące rzeczywiste bramki i czynności właściciela

Rzeczywisty owner/Core binding i niezależne Billing/typ klucza: **BLOCKED_EXTERNAL**. Potem osobne GO dla konkretnego request digest/modelu/kwoty do0,05USD/liczby1/output≤512/timeout/source/capsule/epoch/nonce. Tego zgłoszenia programistycznego nie traktujemy jako takiej zgody. Nie odczytywano zawartości, długości ani fingerprintu istniejącego Meta API key.

Najmniejszy krok właściciela: potwierdzić Billing/typ dostępu w swoim projekcie i udostępnić rzeczywisty admission przez zaufany host Core. Dopiero po przygotowaniu dokładnego planu można udzielić jednorazowego GO. Dla Chrome osobno zatwierdzić mechanizm kontrolowanego egress, prywatny profil i exact origin; obecny brak sieci nie może być zastąpiony obejściem. Nie ma bezpiecznego globalnego przełącznika „autoryzuj wszystko”.

Rozruch, pięć działań i rollback trzech checkpointów bez kasowania P01/P02/UNKNOWN: [P03_FINAL_RUNBOOK.md](../P03_FINAL_RUNBOOK.md). Scenariusz 2–3min z uczciwymi etykietami: [P03_JUDGE_DEMO_2MIN.md](../P03_JUDGE_DEMO_2MIN.md). Nie nagrano filmu ani nie zgłoszono projektu. Push pozostaje NOT EXECUTED i wymaga świeżej osobnej zgody.
