# Pierwszy APK — propozycja jednej próby DEBUG

Stan: **PENDING_OWNER_APPROVAL**. APK, JVM, lint i assemble: **NOT_RUN**.
Baza: `main` `2494ca438b1f834e8451e07e729eca57e535cda5`, z zachowaniem PR #29.
Dokładny HEAD, patch i ich hashe zamraża prywatny pakiet zgody przed publikacją.

## Przyczyna i granica decyzji

Przebieg [41331318973](https://github.com/luciferprosun/AIOA-spArkHAT/actions/runs/41331318973)
odmówił przed checkoutem: `BLOCKED_CI_IMAGE_METADATA_MISMATCH`.
Startup oraz natywny plik metadanych wskazywały `20261025.353.1`,
a `ImageVersion` podawał `20261026.354.1`. Pierwszy przebieg
[41322536413](https://github.com/luciferprosun/AIOA-spArkHAT/actions/runs/41322536413)
zatrzymał się na `BLOCKED_SYMLINK`; oba pakiety dowodów pozostają zachowane.

[actions/runner-images #15202](https://github.com/actions/runner-images/issues/15202)
opisuje tę samą parę wersji i osobny problem presji pamięci. Podczas odczytu zgłoszenie
było otwarte, bez komentarzy opiekunów. To niezależna obserwacja użytkownika;
nie jest potwierdzeniem równoważności obrazów ani bezpieczeństwa dostawcy.
Przyczyna rozbieżności pozostaje UNKNOWN.

## Minimalna zmiana istniejącego profilu

Workflow otrzymuje wybór `build_profile`, domyślnie **STRICT**, oraz osobny
`debug_environment_ack`, domyślnie **false**. Nie powstaje nowy builder,
serwer, runtime ani system kwalifikacji. Używany jest obecny `ci_build.py`.

STRICT zachowuje odmowę każdej rozbieżności, dotychczasowy pin
`20261026.354.1`, odczyt bez symlinków, kontrolę formatu i tożsamości pliku.
Profile CodeQL pozostają STRICT. Nie zmienia się `codeql-static.yml`.

DEBUG_TOOLCHAIN_V1 wymaga wszystkich istniejących bramek oraz osobnej zgody DEBUG:

- GitHub-hosted `ubuntu-24.04` / X64, właściciel `luciferprosun`, `main`,
  attempt 1, zgodne source SHA / workflow SHA / hash bajtów workflow,
  czysty checkout oraz odczyt aktualnego main przed i po buildzie.
- `ImageVersion` nadal dokładnie `20261026.354.1`; rzeczywiste metadane są
  odczytywane i publikowane w snapshot, bez nadpisywania tej zmiennej.
- Dopuszczony jest obraz zgodny z STRICT albo dokładna zaobserwowana para:
  metadata `20261025.353.1`, env `20261026.354.1`, SHA-256 pliku metadanych
  `6d35057ab003af4dc74998526957d7bde2e5526e1da06b4ed93201f6fa82e8ba`.
  Inny obraz, inna para lub inne bajty tej rozbieżnej metadata oznaczają odmowę.
- Snapshot przechodzi z kroku przed checkoutem przez GitHub step output do
  istniejącego preflight, invocation, receipt i failure JSON. Wyjątek pozostaje
  oznaczony `MISMATCH_ACCEPTED_DEBUG`; nie zostaje przemianowany na zgodność.
- SDK: istniejące API36 rev2 / build-tools35.0.0 / zaobserwowany wpis licencji,
  brak automatycznej akceptacji licencji lub pobierania SDK przez Gradle.
  Inwentarz musi odpowiadać SHA-256
  `9f81aed02ae39189e55282cd66a561969590f2c032a868beaa1afc7e3b51e793`
  z preflight pierwszego zatwierdzonego runu, a po buildzie pozostać niezmieniony.
- JDK17.0.21+9, Gradle8.13, cmdline-tools22.0: niezmienione przypięte archiwa,
  rozmiary, SHA-256, bezpieczne rozpakowanie i prywatne katalogi. Rzeczywiste
  java/javac/architektura/java.home pozostają wymagane przed Gradle.
- `contents: read`, checkout bez utrwalonych credentials, kuratorowane
  środowisko procesu bez kluczy; świeży signer DEBUG i niezależna weryfikacja kopii APK.
- DEBUG wymaga `enable_codeql=false`; nie uruchamia zadań z `security-events: write`.

Ryzyko odstępstwa: właściciel akceptuje ograniczony eksperyment na runnerze
o nierozstrzygniętej tożsamości tygodniowego obrazu. Hash metadata identyfikuje
zaobserwowany plik, nie atestuje hosta. Hash SDK wiąże dostarczone przez GitHub
bajty z pierwszym runem, nie zastępuje niezależnego SHA-256 archiwum wydawcy.
Pozostaje istniejące zaufanie do efemerycznej VM dostawcy i repozytoriów Maven;
transytywne zależności nie otrzymują pełnej nowej blokady hashy. APK z tej próby
nie uzyskuje certyfikacji produkcyjnej. Brak podstaw do akceptacji tego ryzyka
oznacza rezygnację z tego profilu i wybór osobno sprawdzonego buildera;
nie wolno poszerzać wyjątku ani powtarzać losowania runnera w pętli.

## Jedna zgoda na konkretny pakiet

Po lokalnym RED/GREEN i review właściciel otrzymuje exact patch, HEAD, base i hash workflow.
Zgoda ma obejmować publikację tej jednej gałęzi, jeden PR i merge dokładnego
patcha na wskazaną bazę po wymaganych kontrolach oraz **jeden** dispatch na
rzeczywisty odczytany merge SHA, z potwierdzeniem zgodności drzewa.
Zmiana main w międzyczasie wymaga oceny zakresu przed publikacją; nie jest
zgodą na automatyczne dokładanie innych zmian. Automatyczny istniejący CodeQL
PR/main pozostaje objęty pakietem, bez zmiany ustawień zabezpieczeń.

Sposób: jeden standardowy GitHub-hosted `ubuntu-24.04` job, maksymalnie
**35 minut** łącznie. Istniejący kontrolowany builder wykonuje w `clients/android`:

```text
./gradlew --no-daemon --max-workers=1 testDebugUnitTest lintDebug assembleDebug
```

Builder dodaje istniejące limity pamięci, prywatne katalogi, init script,
zakaz pobierania SDK/JDK przez Gradle i signer. Timeout samego Gradle: 1800 s.
Pierwsze rozwiązywanie zależności jest online. Przypięte trzy archiwa to
512411378 bajtów plus zależności z obecnych repozytoriów dostawców.
Brak płatnej inferencji, większych runnerów, płatnych usług i zmian budżetu.
Standardowy runner publicznego repo jest bezpłatny według
[GitHub Actions billing](https://docs.github.com/en/billing/concepts/product-billing/github-actions).
Nie zmienia się planu ani limitów płatności. Retencja artefaktu: jeden dzień.

Ekspozycja: publiczne repo i log Actions; tylko zweryfikowany DEBUG APK oraz
oczyszczony JSON, ewentualnie istniejący failure JSON. Keystore, raw build logs,
cache i sekrety nie są artefaktami. Maksymalny APK: 128 MiB. Właściciel ponownie
zatwierdza tę konkretną publikację; dotychczasowe warunki SDK pozostają zachowane.

CodeQL pozostaje w działającym default setup czterech grup i tygodniowym harmonogramie.
Nie następuje default→advanced, zmiana zmiennych repo ani rollback ustawień
po próbie. Kotlin CodeQL tej próby: NOT_RUN, niezależnie od wyniku APK.

## Odbiór i rollback

Po zgodzie: jeden trwały zapis intencji dispatch przed POST; przy niepewnym ACK
odczyt istniejącego runu, bez ponowienia. Pierwszy błąd kończy próbę.
Istniejący failure JSON zachowuje kod/etap/exit code, hashe logów i ograniczone
lokalizacje/kategorie kompilatora. Nierozpoznana diagnostyka pozostaje jawnie UNKNOWN.
Sukces wymaga rzeczywistych XML JUnit, lint, assemble, package/version/min/target,
apksigner, certyfikatu i SHA-256 zweryfikowanej kopii; potem pobrania i sprawdzenia artefaktu.
Dotychczasowy stary APK nie zastępuje tego wyniku.

Rollback kodu po przyszłej publikacji: osobny zwykły revert tej zmiany po ocenie
aktualnego main; zachować PR #29, oba stare runy i dowody nowej próby.
Przed publikacją patch pozostaje lokalny. STRICT można nadal wybrać jako domyślny.
Nie wykonuje się reset/clean ani cofania operatorowych plików.
Bez instalacji na Xiaomi, parowania, Core admission, Muse LIVE lub claim AGENT_READY.
