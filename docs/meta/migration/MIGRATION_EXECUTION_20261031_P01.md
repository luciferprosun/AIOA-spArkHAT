# AIOA spArkHAT — METAGuardiansSPARK

## Wykonanie migracji P01 — 2026-10-31

**PASS dla zakresu OFFLINE P01. Native READ/Meta LIVE/Chromium LIVE pozostają
niegotowe. NOT PUSHED — AWAITING OWNER APPROVAL.**

Target: `/home/l/projects/AIOA-spArkHAT-META`, remote
`https://github.com/luciferprosun/AIOA-spArkHAT.git`, gałąź
`AIOA-METAGuardiansSPARK`. Baza: `0741d37db0630233b4e7212f6f3af6320106c792`.
Lokalny commit kodu i testów: `5d0c62d883a231d7057a94842beb32fc2c532bb3`.
Dokumentacja jest osobnym kolejnym lokalnym commitem. Nie zmieniono nazw repo,
gałęzi, licencji ani wcześniejszej historii.

Repo nie miało skonfigurowanej tożsamości autora. Pierwszy commit odmówił
utworzenia; HEAD pozostał bez zmian. Użyto jawnej technicznej tożsamości
`Codex <codex@localhost>` wyłącznie przez opcje konkretnej komendy Git.
Nie zmieniano konfiguracji globalnej/użytkownika i nie podszywano się pod ownera.

## Zachowane źródła

Prywatny katalog poza repozytoriami:
`/home/l/projects/META_MIGRATION_PRIVATE_20261031/20261031T134840Z`.
Zawiera plan/progress, początkowe gałęzie/HEAD/remotes bez credentiali/statusy,
wybrane 44 pliki źródłowe z hashami, 10 dodatkowych hashy, wyniki testów,
przegląd i kopie dwóch plików zastanych. Uprawnienia katalogu 0700.

Main source: branch `feature/nebius-nemotron-integration-20261028`, HEAD
`6e9dd8ebc1dcb2c03345d9dc7d30895013751cd5`; początkowo 24 modified +
199 untracked, więcej niż w historycznym opisie promptu. Każdy kandydat ma osobny SHA-256 faktycznych bajtów i
status w IMPORT_LEDGER. Nie wykonano add/stash/reset/clean/checkout/commit
lub testów w tym źródle.

Pozostałe źródła, wyłącznie READ-ONLY:

- Companion: `codex/final-connect-20261023`,
  `9cf6c567b40bc87385fb90e9143b0fb170889b2a`.
- Nemotron CLI: `feature/codex-nemotron-final-20261028`,
  `5e0e80d51ae1b75583f37ef04e377c533b7d280f`, zastane zmiany zachowane.
- Nebius phase2: `codex/nebius-token-factory-prep-20261005`,
  `d01f70bd0cd9c9a4cce80943c7ce7b9ce2757cc2`.

`mission_runner_offline.py` i `test_meta_mvp_runner.py` przetrwały bajtowo,
z hashami opisanymi w SOURCE_PROVENANCE. Były untracked; checkpoint objął
ich dokładną, zastaną treść po QA. Nie poprawiano ich oznaczeń autorstwa ani
nie łączono ich syntetycznego ownera z autentyczną zgodą LIVE.

## Faktycznie wykonana adaptacja

1. `runtime/providers/tool_calling.py`: neutralne strict_json, checked,
   ToolCall i ToolMessage ze źródła AIOA/Nebius. Zgodność AST czterech
   definicji sprawdzono niezależnie względem prywatnych dirty bytes.
   Nebius-specific ToolExactRequest i ToolProviderResult nie zostały skopiowane.
2. `runtime/meta_hackathon/mission_read_offline.py`: wąska funkcja
   run_read_once, przyjmująca już skonfigurowany CoreWarrantLedger i sealed
   Core principals. Korzysta z istniejących BrowserTaskV1/parse_muse_plan,
   OfflineTaskState, read_fixture oraz OfflineCorrelationLedger.
3. `tests/meta_migration_support.py` i `tests/test_meta_migration_read.py`:
   jawny operator fixture, istniejący durable transaction test port, zerowy
   koszt mock i 18 testów nowej ścieżki. Kod produkcyjny nie tworzy fixture
   ownera, backendu ani zgody.

Dokładna operacja wiąże owner/task/source, cel i revision, call_id, bajty
argumentów, tool schema, SHA treści oraz czas początkowy. Istniejący warrant
sprawdza uprawnienia, zgodę, expiry i one-use nonce. Użyto 0 USD i LOW risk,
bez dodatniej fikcyjnej rezerwacji. Zużycie warrantu oznacza wyłącznie
consumption record. Native START/ServiceGuard/FS/browser dispatch nie zachodzi.

Wynik zawiera bounded JSON tool response o właściwym call_id, task/source/
content SHA i evidence digest. Treść obserwacji pozostaje danymi; nie jest
zwracana w publicznym JSON ani interpretowana jako zgoda. STOP przed odczytem
blokuje read; brak receipt, utrata ACK i błąd po consumption dają UNKNOWN.
Nie ma automatycznego ponowienia niepewnej operacji. Replay używa tej samej
istniejącej bariery Core, także po odtworzeniu runnera/ledgera.

## Testy i odtworzenie

Polecenia wykonano z target checkout, bez instalacji i paid inference.

| Polecenie (z prefiksem PYTHONDONTWRITEBYTECODE=1 python3 -B) | Wynik |
| --- | --- |
| `-m unittest discover -s tests -p 'test_meta_*.py' -q` przed zmianą | 168 PASS |
| `-m unittest discover -s tests -p 'test_meta_migration_read.py' -q` RED | 18 oczekiwanych FAIL: brak migrowanej ścieżki/kodeka |
| `-m unittest discover -s tests -p 'test_meta_migration_read.py' -v` GREEN | 18 PASS |
| `-m unittest discover -s tests -p 'test_meta_*.py' -q` po adaptacji i na końcu | 186 PASS |
| `-m unittest discover -s tests -p 'test_core_warrant.py' -q` | 13 PASS |
| `-m unittest discover -s tests -p 'test_mcp_*.py' -q` | 99 PASS |
| `PYTHONPATH=tests python3 -B -m meta_migration_support` | JSON OFFLINE_LINKED_UNVERIFIED |
| `git diff --check` oraz `git diff --cached --check` | PASS |

Grupa 18 jest już częścią 186; nie sumujemy jej ponownie. Niezależny reviewer
samodzielnie uruchomił 18 testów migracyjnych: PASS, 0 Critical/Important.
Jedna Minor pozostaje: test utraty ACK nie ma bezpośredniej asercji zera
wywołań read_fixture; sprawdza UNKNOWN, brak tool result, consumption i
replay denial. Kod kończy się przed read. Review dotyczy kodu; dokumentację
i końcowy staging zweryfikował wykonawca. Dodatkowe main/run_demo w pomocy
testowej zostało sprawdzone wykonaniem demo po tym przeglądzie.

```bash
cd /home/l/projects/AIOA-spArkHAT-META
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=tests python3 -B -m meta_migration_support
PYTHONDONTWRITEBYTECODE=1 python3 -B -m unittest discover -s tests -p 'test_meta_*.py' -q
```

Demo: wyłącznie syntetyczny operator, trwały port TEST w TemporaryDirectory,
source SHA `1111111111111111111111111111111111111111`, koszt mock 0.00 USD.
Zwraca environment=OFFLINE_FIXTURE, verified=false, dispatch_allowed=false.
Nie jest CLI nowej aplikacji, nie otwiera serwera i nie korzysta z modelu.
Zastany runner można nadal uruchomić przez
`python3 -B -m runtime.meta_hackathon.mission_runner_offline --demo`.

Nie uruchamiano całej historycznej suite Core/packaging/Node ani testów
w źródłowych worktree; nie ma nowej certyfikacji całego systemu. Zmiana nie
modyfikuje Core. Wykonano pełny wymagany zestaw Meta i powiązane warrant/MCP.
Nie instalowano brakujących zależności. Brak pominięć w uruchomionych grupach.

## Kontrola danych i granice

Przed stagingiem przejrzano kod, snapshot/provenance oraz zawartość indexu.
Skan podejrzanych credentiali dał 0 trafień; Python 3.11 AST PASS. Exact path
staging objął sześć plików kodu/testów oraz osobno trzy dokumenty migracji.
Pełne logi, diff i review pozostały prywatne.

Nie przeniesiono prywatnych baz, sekretów, .env, promptów, bundli, profili
Chrome, screenshotów, filmów lub pełnych raportów agent24h. Services/GOLD72,
montowania, Android deployment, źródłowy Nemotron CLI i konfiguracja Codex–Muse
pozostały poza zmianą. Nie używano kluczy, nie uruchamiano LIVE ani serwera
publicznego. Nie było push, merge, rebase, force ani zmian w main.

## Pozostałe kroki P02/03

1. `runtime/webapp.py` + `web/app.js/index.html/styles.css`: dopiąć nowy
   adapter do istniejącego interfejsu po ustaleniu portu backendu. Źródłowe
   ui_v2/frontend-v2 wymagają adaptacji; brak ich odpowiedników w target.
2. `runtime/providers/config.py` i wspólny kodek: dopasować prawdziwy provider
   Meta do istniejącego routera; nie przenosić Nebius ToolExactRequest przez
   podmianę nazwy. Native approval/ServiceGuard READ pozostaje osobną bramką.
3. Companion `gateway/server.py`, `gateway/wire.py`, `gateway/native.py`:
   najpierw kontrakty offline status/STOP, istniejący ES256 i revocation;
   capabilities obecnie tasks/chat/stop=false. Brak E2E Android.

Meta API LIVE, izolowany Chromium LIVE, E2E Android, rzeczywiste koszty, film
demo i submission pozostają niewykonane/niezweryfikowane. Wymagają dalszych
etapów i dokładnych zgód tam, gdzie operator zastrzegł skutki zewnętrzne.
P01 nie stanowi autoryzacji natywnego wykonania.

## Rollback i push

Nie resetować ani nie czyścić source/target i nie odtwarzać starych baz.
Przed rollbackiem zachować bieżące zmiany operatora oraz sprawdzić dwie
prywatne kopie plików zastanych. Odwrócić tylko lokalny commit dokumentacji
i `5d0c62d883a231d7057a94842beb32fc2c532bb3` poprzez git revert, po wskazaniu
ich dokładnych SHA z końcowego raportu. Ponieważ commit kodu obejmuje również
dwa wcześniej untracked pliki, po revert przywrócić je z prywatnych kopii
tylko jeśli ich brakuje i potwierdzić zapisane SHA-256; nie nadpisywać nowszej
pracy. Bez tego przywrócenia rollback usunąłby wartościowe pliki zastane.

Proponowane polecenie po osobnej zgodzie operatora:

```bash
git push origin AIOA-METAGuardiansSPARK
```

Aktualnie: **NOT PUSHED — AWAITING OWNER APPROVAL**.
