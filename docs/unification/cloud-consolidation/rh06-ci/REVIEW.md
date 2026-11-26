# PR #73 — Cloud, CI i materiał do niezależnego review

**Przedmiot decyzji:** wyłączony kandydat RH-06, PR [#73](https://github.com/luciferprosun/AIOA-spArkHAT/pull/73). Baza i main `853484d7fe39fabf2922ff87fcedd0a980807817`, drzewo `11db20a7ebbac9ee5842e1b8510169987672c486`. Początkowy i końcowy HEAD PR `933be272d1dabe99dad59108fda8648018d93c50`, drzewo `455b274b54e8cc77b5833cf5b6ceb3272bb1e849`. PR jest otwartym draftem. GitHub wyliczył merge próbny `f9b14de0a8d7bdb14b70597897da4fdaed667810` z tymi dwoma rodzicami i tym samym drzewem. Oficjalny workflow pobiera jawnie SHA głowy PR; komenda checkoutu i wynik `git log -1 --format=%H` są w logach. Wersja workflow to blob `c9a228dfe35775b4391bafc95df9c7e7e4b50afd`. [Workflow kandydata](https://github.com/luciferprosun/AIOA-spArkHAT/blob/933be272d1dabe99dad59108fda8648018d93c50/.github/workflows/nonzero-pr.yml)

## Wynik oficjalny i dyspozycja PR

Ostatni odczyt 2026-11-26T05:07:21Z. Draft True, merged False, mergeable_state `clean`. Poniżej ID rzeczywistych wykonań. GitHub przeniósł dwa udane zadania pakowania i certify 3.12 do widoku drugiej próby bez ponownego wykonania.

| Wymagany check | Próba i dowód | Wynik | Pełna suita |
|---|---|---|---|
| Installed packaging (3.11) | 1, [job 139676766837](https://github.com/luciferprosun/AIOA-spArkHAT/actions/runs/45750474198/job/139676766837) | SUCCESS | — |
| Installed packaging (3.12) | 1, [job 139676766581](https://github.com/luciferprosun/AIOA-spArkHAT/actions/runs/45750474198/job/139676766581) | SUCCESS | — |
| certify (3.12) | 1, [job 139676766902](https://github.com/luciferprosun/AIOA-spArkHAT/actions/runs/45750474198/job/139676766902) | SUCCESS | 4506 wykonanych, 4501 PASS, 5 SKIP, 0 FAIL, 0 ERROR |
| certify (3.11) | 1, [job 139676766945](https://github.com/luciferprosun/AIOA-spArkHAT/actions/runs/45750474198/job/139676766945) | FAILURE | NOT_RUN |
| certify (3.11) | 2, [job 139696702626](https://github.com/luciferprosun/AIOA-spArkHAT/actions/runs/45750474198/job/139696702626) | SUCCESS | 4506 wykonanych, 4501 PASS, 5 SKIP, 0 FAIL, 0 ERROR |

Jedyne ponowienie oficjalnego certify (3.11) dotyczyło niezmienionego źródła. Dostawca Azure, obraz 20261116.376.1, Python 3.11.18. W dzienniku tej próby imiennie zakończone wyniki OK dla RH-06: 12, dla dwóch badanych RH-04: 2.

Zweryfikowano także SHA-256 pliku chrome-rest.log z [artefaktu retry 3.11](https://github.com/luciferprosun/AIOA-spArkHAT/actions/runs/45750474198/artifacts/15089650043). Identyfikatory 4506 testów obu wersji mają ten sam SHA-256 `1936d809e62ace3647fad455ca6f4a6bd7f661333090899d927ac1c191458bb1`. Ta próba przeszła; przyczyna lub stabilność nadal niepotwierdzona. Cztery obowiązkowe checki są zielone. Gotowy materiał można przekazać formalnemu reviewerowi. PR pozostaje HOLD zgodnie z dyspozycją utrzymania draftu. Niezależna osoba powinna rozliczyć dokumentowane ograniczenia dla wyłączonego kandydata, a właściciel wydać osobną dyspozycję przejścia do scalenia. Produkcja i kwalifikacja hosta mają osobne warunki.

## Decyzje Cloud i pochodzenie dowodów

Przed pracą odczytano lokalne dokumenty misji Cloud RH-06 i Local RH-07. Aktualne polecenie pozostawia PR w draft. Ani pod katalogiem źródeł, ani w drzewie kandydata nie znaleziono dodatkowego AGENTS.md. Cloud ma przydzielone hosted CI i review PR. Źródłowa gałąź RH-06 ma lokalny checkout wykonawcy. Materiał diagnostyczny znajduje się wyłącznie na gałęzi `cloud/rh06-ci-evidence-20261126`. Lista plików dodanych przez Cloud:

| Plik na gałęzi dowodowej | Funkcja |
|---|---|
| `.github/workflows/rh06-cloud-comparison.yml` | Ograniczony pomiar na przydzielonej VM; wyzwalany wyłącznie przy zmianie tego pliku na wskazanej gałęzi. Uprawnienia repozytorium tylko do odczytu, checkout bez utrwalenia tokenu. |
| `docs/unification/cloud-consolidation/rh06-ci/measure.py` | Sprawdza bloby źródeł, dodaje znaczniki monotoniczne w kopiach widocznych tylko dla procesu testowego. Druga wersja umożliwia obserwację tej samej odpowiedzi po FAIL. |
| `git-drift.sh` (w tym katalogu) | Próba negatywna z rzeczywiście różnymi bajtami Git i oryginalnymi pinami, plus odtworzenie obu tracebacków. |
| `receipts.json` i `REVIEW.md` | Wybrane bezpieczne pola logów GitHub, środowiska, wyniki, metoda i przekazanie. |

W [receipts.json](receipts.json) pola `null` oznaczają brak pomiaru. Puste listy imiennych wyników po zatrzymaniu przed suitą oznaczają NOT_RUN. Pola `head_sha`/tree w diagnostyce opisują checkout narzędzia; `samples[].trial` identyfikuje osobno badane źródła. Każdy wpis zawiera run, attempt, job i adres. Testy Chrome na instrumentowanych kopiach mają status eksperymentalny. Certyfikacja pochodzi wyłącznie z niezmodyfikowanego workflow.

## Chrome i kontrakt

Obie ścieżki `certify` wywołują `/usr/bin/python3 -B tests/nz12_source_runner.py tests/mobile_device_console_browser.py`. Wewnątrz bwrap worker również działa przez `/usr/bin/python3`. Wersja macierzy wybiera Pythona orkiestratora i pełnej suity. Worker musi widzieć osobną przestrzeń sieciową z samym loopbackiem, pustą tablicą routingu, zerowymi capabilities i bez katalogu operatora. Wrapper uruchamia osobną sesję oraz dwie anonimowe rury. Tylko wartości numerów FD są interpolowane do skryptu Bash. Argumenty Chrome przechodzą przez `"$@"`. Oryginalne polecenie z miejscami na efemeryczne wartości testowe:

```text
/bin/bash -c 'exec 3<&<browser_read> 4>&<browser_write>; exec "$@"' aioa-synthetic-pipe
  /opt/google/chrome/chrome --headless=new --no-sandbox --disable-dev-shm-usage
  --remote-debugging-pipe --window-size=1280,900 --no-proxy-server
  "--host-resolver-rules=MAP host.example.org 127.0.0.1"
  --ignore-certificate-errors-spki-list=<synthetic-TLS-SPKI>
  --disable-background-networking --disable-component-update
  --user-data-dir=<fresh-private-profile> about:blank
```

`--no-sandbox` jest istniejącą flagą tego testu wewnątrz zewnętrznego izolatora. Deskryptory 3/4 służą do CDP. Pierwsza komenda to JSON `{"id":1,"method":"Browser.getVersion","params":{}}` zakończony NUL. `Pipe.call` liczy 15 s od zakończenia zapisu pełnej ramki. Przetwarza już odebrane ramki, czeka przez `select`, odczytuje do 65536 bajtów i ogranicza bufor do 2 MiB. Wymaga kompletnej odpowiedzi o tym samym całkowitym ID. Inne odpowiedzi lub zdarzenia mogą zostać skonsumowane, dlatego historyczny pusty bufor sam nie dowodzi braku jakichkolwiek wcześniejszych bajtów. Przy timeout pierwszy request pozostaje nierozstrzygnięty. Testy cyklu życia wymagają egzekwowania pozostałego czasu i braku ponowienia. To wykonawcze kryterium zarówno klienta, jak i obowiązkowej bramki. [Transport i open_document](https://github.com/luciferprosun/AIOA-spArkHAT/blob/933be272d1dabe99dad59108fda8648018d93c50/runtime/mobile_gateway/chrome_console.py#L62-L113) · [Testy limitu](https://github.com/luciferprosun/AIOA-spArkHAT/blob/933be272d1dabe99dad59108fda8648018d93c50/tests/test_chrome_console_lifecycle.py#L20-L58)

Pomiar błędu `elapsed_seconds` zaczyna się bezpośrednio przed `open_document`, już po `Popen`. Stdin/stdout Chrome są skierowane do DEVNULL, stderr do prywatnego pliku tymczasowego. Przy błędzie test publikuje najwyżej 8192 końcowe bajty po redakcji dwóch syntetycznych wartości. Sprzątanie zamyka oba FD rodzica, wysyła TERM do własnego dziecka i po 2 s może wysłać KILL do sprawdzonej grupy. Zewnętrzny worker ma limit 55 s; wrapper sygnalizuje własną grupę przed odebraniem statusu lidera. [Fixture](https://github.com/luciferprosun/AIOA-spArkHAT/blob/933be272d1dabe99dad59108fda8648018d93c50/tests/mobile_device_console_browser.py#L273-L316) · [Wrapper](https://github.com/luciferprosun/AIOA-spArkHAT/blob/933be272d1dabe99dad59108fda8648018d93c50/runtime/browser_agent/chrome_process_read.py#L33-L71)

## Dowody i granice wnioskowania

Pierwszy oficjalny przebieg kandydata na 3.11 zatrzymał się po pięciu zaliczonych bramkach; dla Chrome odnotowano błąd 1/1, 15,008 s, komendę 1, bufor 0, wciąż żywy proces D z `folio_wait_bit_common` i 1399 głównymi błędami stron. Pełna suita 3.11 w tej próbie była NOT_RUN. Na 3.12 ten sam checkout przeszedł Chrome (cały pojedynczy test 5,311 s), wszystkie osiem bramek i pełną suitę. Recenzent obliczył SHA-256 obu zarchiwizowanych `chrome-rest.log`; zgodne z `result.json`/logiem kroku. [Artefakt 3.11](https://github.com/luciferprosun/AIOA-spArkHAT/actions/runs/45750474198/artifacts/15085327205) · [Artefakt 3.12](https://github.com/luciferprosun/AIOA-spArkHAT/actions/runs/45750474198/artifacts/15086851267)

W próbie 1 bazowego main oba interpretery zatrzymały się na pierwszej komendzie, a w próbie 2 rezultat był FAIL/PASS. PR #71 na drzewie identycznym z bazą przeszedł na obu. W tych ośmiu historycznych obserwacjach (2 kandydat, 4 baza, 2 PR #71) cztery FAIL przypadają na AWS i cztery PASS na Azure. Są dwie wersje obrazu wśród awarii; sam stan procesu także się różnił (D/folio i S/futex). Te wyniki nie identyfikują przyczyny w dostawcy ani interpreterze. Szczegóły per job w JSON. Historyczne hashe Chrome, rzeczywisty kernel, wolna pamięć i czasy pierwszych danych nie były raportowane przez oficjalną bramkę. [PR #71](https://github.com/luciferprosun/AIOA-spArkHAT/actions/runs/45665799283) · [Baza, próba 1](https://github.com/luciferprosun/AIOA-spArkHAT/actions/runs/45682246342/attempts/1) · [Baza, próba 2](https://github.com/luciferprosun/AIOA-spArkHAT/actions/runs/45682246342/attempts/2)

Kontrolowany przydział obu historycznych obrazów: **NOT_REPRODUCIBLE_WITH_AVAILABLE_RUNNERS**. Repozytorium zwróciło zero zarejestrowanych własnych runnerów. Etykieta standardowa wybiera rodzinę systemu. W pomiarach poniżej GitHub rzeczywiście przydzielił `20261116.133.1`; nie było możliwości zamówienia obu numerów rewizji w ustalonej kolejności. [Etykiety GitHub](https://docs.github.com/en/actions/reference/runners/github-hosted-runners) · [Polityka obrazów](https://github.com/actions/runner-images#image-releases)

Pierwszy eksperyment miał cztery zaplanowane próby szeregowe na jednej VM. Zachowano przypięte pakiety z kandydata, prywatny profil dla każdej próby, istniejący bwrap i 15 s od wysłania. Pomiar odczytu wykonano po `os.read`, pomiar dopasowania przed zwróceniem wyniku z `Pipe.call`. SHA-256 Chrome pobrano dopiero po zakończeniu prób. Proces zewnętrzny używa kolejno dwóch interpreterów, worker zawsze systemowego 3.12.3. Eksperyment wywołuje samą bramkę, bez poprzedzających jej pięciu bramek CI. Nie mierzono faktycznego zapełnienia cache stron. Stan „pierwszy start” dotyczy pierwszego uruchomienia Chrome przez ten job.

| Kolejność, źródło / rodzic | Pierwszy odczyt od wysłania | Dopasowana odpowiedź | Wynik całego testu |
|---|---:|---:|---|
| 1, baza / 3.11 | brak przed timeout | brak, 15,014 s elapsed | FAIL; 1 błąd, 0 skip |
| 2, HEAD / 3.12 | 151,53 ms | 151,59 ms | PASS |
| 3, baza / 3.12 | 156,37 ms | 156,44 ms | PASS |
| 4, HEAD / 3.11 | 163,04 ms | 163,11 ms | PASS |

Runner AWS, Ubuntu 24.04.5, `ubuntu24/20261116.133.1`, kernel `7.0.0-1014-aws`, 4 CPU, 14 GiB RAM dostępne, 88 GiB dysku wolne przed próbami. W pierwszym timeout proces żył, stan D, 1313 major faults, `folio_wait_bit_common`. Przed pierwszym startem PSI I/O full avg10 wynosiło 31,09%, a pamięci 0,00%. Wszystkie cztery próby używały `/opt/google/chrome/chrome`, pakietu `157.0.8103.78-1`, SHA-256 `91e519ce83eac12740d54398364583b3131116055eca863d0a240d6062e84053`. Cały diagnostyczny job ma **FAIL**. [Kod pomiaru](https://github.com/luciferprosun/AIOA-spArkHAT/blob/37fa7dde62b49b8c91a9efd972f33d8d884be94a/docs/unification/cloud-consolidation/rh06-ci/measure.py) · [Cztery próby](https://github.com/luciferprosun/AIOA-spArkHAT/actions/runs/45756967218/job/139697754340)

Piąta, z góry ograniczona próba na nowej VM miała odpowiedzieć, czy po przekroczeniu 15 s *ten sam* FD dostarczy rozpoznawalną odpowiedź przez następne 10 s. Obserwator wchodzi wyłącznie po odnotowaniu błędu i ponownie go zgłasza; nie wysyła nowych bajtów ani danych dostępu. Pierwszy start HEAD/3.12 na AWS, ten sam obraz, pakiet i digest Chrome, odpowiedział prawidłowo po 9,0553 s. Cały test PASS. Ścieżka obserwacji po błędzie była **NOT_RUN**. Potwierdza to, że na tym obrazie również pierwszy start może zdążyć w limicie. Brakuje czasu spóźnionej odpowiedzi z próby, która rzeczywiście przekroczyła limit. Nie ma dowodu na wadę parsera ani podstaw liczbowych dla nowego limitu. Utrzymanie obecnego deadline, brak retry i publikacja wyników to decyzja Cloud dla tego SHA. [Piąta próba](https://github.com/luciferprosun/AIOA-spArkHAT/actions/runs/45757247866/job/139698650439)

## RH-04 i RH-06

`test_redhat_rh04_native_task_gate.RedHatRH04Tests.test_git_plumbing_parent_replacement_is_rejected_before_lock_creation` wymaga faktycznej podmiany katalogu, odmowy `GIT_STORAGE_CHANGED`, pustych obu katalogów oraz braku plików lock. `test_git_plumbing_v3_ref_link_ack_cleans_both_git_locks` wymaga pustego ACK, zapisania dokładnej treści refa oraz usunięcia packed-refs.lock i blokady konkretnego refa. Imienne OK na bazie i HEAD na przypiętym hoście oraz osobne uruchomienia obu przypadków na obu checkoutach na Mint 22.2/Python 3.12.3 potwierdzają osiągnięcie asercji. [Testy HEAD](https://github.com/luciferprosun/AIOA-spArkHAT/blob/933be272d1dabe99dad59108fda8648018d93c50/tests/test_redhat_rh04_native_task_gate.py#L1015-L1105)

Broker otwiera siedem ustalonych plików (`/usr/bin/git` plus sześć pinów), sprawdza typ, rozmiar i hash bajtów odczytanych z FD przed zapieczętowaniem kopii. PATH nie wybiera Git. Na obecnym hoście wszystkie siedem SHA się zgadza. W prywatnej przestrzeni montowań zastąpiono tylko widok `/usr/bin/git` jego działającą kopią z jednym dopisanym bajtem. Zachowano oryginalny pin `eb54b535467e0975c1284d4c4d08eea779aeb248a5d34b02e2ee171382e22201`; zmieniony plik ma `1d48dde779d2154c9e6c5a9597bebfde3d8c02b9aabe51cff6d9af12b1461ecf`. Na obu drzewach odczytowa komenda dostała `WarrantError: GIT_RUNTIME_CHANGED`. Oba oryginalne testy w tym widoku miały na każdym drzewie 0 PASS, 1 FAIL i 1 ERROR: w pierwszym nie pasował oczekiwany `GIT_STORAGE_CHANGED`, w drugim nieobsłużony wyjątek zatrzymał wywołanie przed ACK. Źródłowy stos HEAD prowadzi przez test:1050 / test:1092, `_git_plumbing` w `sandbox_linux.py:1622` i `warrant.py:40`. Ten eksperyment daje rzeczywistą, kontrolowaną przyczynę obu symptomów; konkretny różny składnik w dawnym środowisku 105/107 pozostaje UNKNOWN. Nie uzasadnia to zmiany fixture ani pinów. [Skrypt reprodukcji](git-drift.sh) · [Walidacja runtime](https://github.com/luciferprosun/AIOA-spArkHAT/blob/933be272d1dabe99dad59108fda8648018d93c50/runtime/mission/sandbox_linux.py#L1600-L1627)

## Pakiet STOP/CAS dla niezależnej osoby oceniającej

| Przypadek | Ref i próby | Dziennik, rezerwacja i rozliczenie |
|---|---|---|
| Trwały STOP/revoke pierwszy (wymagany kontrakt do zatwierdzenia) | Stary ref lub brak; 0 linków | Przed START brak nowego START. Po START oryginalna intencja i rezerwacja UNKNOWN, outbox HELD do uwierzytelnionego rozstrzygnięcia. |
| Pierwsza legalna publikacja | Po ostatniej walidacji pojedynczy udany `os.link` tworzy ref. To punkt nieodwracalności, przed fsync katalogu. Konkurencyjny STOP może się utrwalić później według propozycji właściciela. | HELD do weryfikacji świadectwa i późniejszego podpisanego completion. Jedyna uprawniona transakcja Core rozlicza ten sam intent, task i rezerwację. |
| Awaria po linku, brak lub uszkodzenie dowodu | Maksymalnie jedna próba i 0 powtórnych CAS po restarcie | UNKNOWN / HELD; sam ref o zgodnym OID ani późniejszy fsync nie poświadczają wykonawcy ani jego wcześniejszej synchronizacji. |
| Trwałe świadectwo i completion, utrata ACK | Fixture obserwuje 1 link, 0 nowych CAS w recovery | Świeże wyzwanie i podpis innego procesu weryfikatora, jedna rewizja oryginalnej intencji, jedno rozliczenie. Kolejny reconcile daje ten sam wynik bez drugiej mutacji. |

Core nadal wyprowadza wiązanie z oryginalnej trwałej transakcji, skonsumowanego warrantu, rezerwacji i outbox. Broker sprawdza podpis Core oraz peer credentials, zużywa jedną próbę przed efektem i trzyma lokalną blokadę podczas finalnej walidacji i linku. Najważniejsza luka: między eksportem podpisanego grantu a linkiem niezależny zapis trwałego STOP/revoke w Core nie uczestniczy w tej blokadzie. Testy obejmują odmowę eksportu po revoke i oba porządki lokalnej blokady. Nie wykazują globalnego porządku obu UID. Status decyzji A o wspólnym sekwencerze i dopuszczalnym czasie oczekiwania to PENDING. [Broker](https://github.com/luciferprosun/AIOA-spArkHAT/blob/933be272d1dabe99dad59108fda8648018d93c50/runtime/red_hat/broker_service.py#L20-L117) · [Decyzja właściciela](https://github.com/luciferprosun/AIOA-spArkHAT/blob/933be272d1dabe99dad59108fda8648018d93c50/docs/architecture/RH06_STOP_CAS_OWNER_DECISION.md)

Local i operator kwalifikowanego hosta muszą wykazać rzeczywiste trzy tożsamości, ochronę klucza brokera przed Core, ochronę przed zapisem do sąsiedniego refa oraz podmianą przodka, tylko odczyt dla weryfikatora, trwały fence po restarcie i normalne Native apply → utracony ACK → cold recovery na przypiętym Noble. W fixture START powstaje syntetycznie, procesy mają ten sam UID. Dotychczasowe wyniki kwalifikacji cross-UID: NOT_RUN / BLOCKED_HOST. Produkcyjne Native wyłączone. Historyczne #69: UNKNOWN / HELD z zachowaną rezerwacją. [Macierz](https://github.com/luciferprosun/AIOA-spArkHAT/blob/933be272d1dabe99dad59108fda8648018d93c50/docs/architecture/RH06_QUALIFICATION_MATRIX.md)

## Formalne bramki i odtworzenie

Dla tego SHA trzy odczytowe analizy wewnętrzne pokryły logi Chrome, kontrolę Git i wymagania projektu. Formalne recenzje PR: 0, zatem brak zatwierdzonego SHA. Reguła klasyczna `main` zwróciła w tej sesji HTTP 200: strict status checks, egzekwowanie wobec administratorów, 0 wymaganych formalnych approvals, brak wymogu CODEOWNERS i last-push approval, odrzucanie przestarzałych recenzji. Endpoints efektywnych reguł dla main i listy rulesetów zwróciły puste listy. Brak śledzonego CODEOWNERS w standardowych lokalizacjach. Poprzednie 403 opisuje uprawnienia wcześniejszego klienta. Cztery domyślne analizatory CodeQL (actions, javascript-typescript, python, c-cpp) i check CodeQL przeszły. Osobny owner-gated `analyze` był SKIPPED. Cztery wymagane nazwy to `Installed packaging (3.11)`, `Installed packaging (3.12)`, `certify (3.11)`, `certify (3.12)`. Reguły projektu osobno przewidują kontrolę One-Core, pochodzenia i autoryzacji właściciela przed merge. W tej misji PR ma pozostać draftem. Decyzja o uporządkowaniu produkcyjnego STOP jest warunkiem podłączenia runtime; status CI jej nie rozstrzyga. [Ochrona](https://api.github.com/repos/luciferprosun/AIOA-spArkHAT/branches/main/protection) · [Reguły projektu](https://github.com/luciferprosun/AIOA-spArkHAT/blob/933be272d1dabe99dad59108fda8648018d93c50/docs/unification/cloud-consolidation/SECURITY_GATES.md)

Polecenia odczytu, w checkoutcie repozytorium. ID do podstawienia pochodzą z receipts.json.

```bash
gh pr view 73 --json isDraft,state,headRefOid,baseRefName,reviews,mergeStateStatus
gh pr checks 73 --required
gh api repos/luciferprosun/AIOA-spArkHAT/actions/runs/45750474198/attempts/2/jobs
gh api "repos/luciferprosun/AIOA-spArkHAT/actions/jobs/$job_id/logs" | rg 'RH06_CLOCK|trial_finished=|CHROME_COMMAND_UNKNOWN|^.* \{"tested_sha":'
gh api repos/luciferprosun/AIOA-spArkHAT/branches/main/protection
gh api repos/luciferprosun/AIOA-spArkHAT/rules/branches/main
gh api repos/luciferprosun/AIOA-spArkHAT/rulesets
```

Wykonanie lokalne na dokładnym HEAD dało **107 PASS, 0 FAIL, 0 ERROR, 0 SKIP** w 281,371 s. Kontrole źródeł (2062 pliki), One-Core i `git diff --check` zwróciły PASS. Oba dedykowane checkouty Cloud, bazy i HEAD, były po teście czyste. Polecenia dla czystego checkoutu kandydata z zależnościami repozytorium i pasującym zestawem Git:

```bash
export PYTHONPATH=.:tests
python -B -m unittest -v test_redhat_rh06_authenticated_boundary test_redhat_broker_protocol test_redhat_native_cas_broker test_redhat_core_adapter test_redhat_core_recovery test_redhat_rh04_native_task_gate test_native69_witness_fixture test_native_git_publication_boundary test_core_intent test_native_git_cold_controller test_nz13_native_coding_lifecycle
python -B tests/nz12_source_policy.py
python -B -m runtime.tools.nonzero_architecture --project-root .
git diff --check 853484d7...933be272
bash "$evidence_checkout/docs/unification/cloud-consolidation/rh06-ci/git-drift.sh" "$PWD"
```

Pełne warunki izolacji, wersje akcji i kolejność poleceń obu eksperymentów zapisane są w [workflow czterech prób](https://github.com/luciferprosun/AIOA-spArkHAT/blob/37fa7dde62b49b8c91a9efd972f33d8d884be94a/.github/workflows/rh06-cloud-comparison.yml) i [workflow pojedynczej obserwacji](https://github.com/luciferprosun/AIOA-spArkHAT/blob/1808df98d5ca90be24870d94bd319bc1e4991895/.github/workflows/rh06-cloud-comparison.yml). Skrypt przygotowania z przypiętego workflow uruchamiano wyłącznie na jednorazowych VM GitHub.
