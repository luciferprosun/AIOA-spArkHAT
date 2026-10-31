# AIOA spArkHAT — P02: uruchomienie jednej aplikacji

Profil sprawdzony 31.10.2026: **OFFLINE_TESTED**, 0 USD, fake Meta + fake browser. Nie jest to rzeczywista rozmowa z Muse API ani nawigacja Chrome.

## Jedna komenda

```bash
cd /home/l/projects/AIOA-spArkHAT-META && PYTHONDONTWRITEBYTECODE=1 python3 -B -m runtime.webapp --meta-offline --port 0
```

Serwer wypisze własny adres `http://127.0.0.1:<port>`. Port jest przydzielany dynamicznie; nie dotyka usług 4314/4315. Używa istniejącego webapp i `web/`, nie tworzy drugiej aplikacji. Stan profilu: prywatny `~/.local/state/aioa-meta-offline-v1` (0700), istniejący adapter Core records; nie wskazywać produkcyjnej bazy lub katalogu źródłowego. Druga instancja z tym samym katalogiem jest blokowana lease. Własny serwer zakończyć Ctrl+C.

## Pięć czynności operatora

1. Otwórz dokładnie adres wypisany w terminalu. W tej samej aplikacji wyświetli się panel **METAGuardiansSPARK**. To loopback; telefon nie połączy się z nim przez własne `127.0.0.1`. Nie otwierać publicznego portu/tunelu na potrzeby tej próby.
2. Sprawdź etykietę **OFFLINE FIXTURE**, model `muse-spark-1.3`, transport `mock`, budget 0 USD, Credit balance `unverified`, Spend permission `not granted`, Last API receipt `none`. Key configured jest tylko wynikiem kontroli metadanych.
3. Zostaw profil `OFFLINE_FIXTURE` i nieruchomy URL `https://docs.example.org/offline-fixture`; wpisz krótkie zadanie odczytu i wybierz **Preview**. Publiczna nazwa URL oznacza fixture; żadne DNS/HTTPS do tej strony nie jest wykonywane.
4. Sprawdź task ID, scope, source SHA, capsule i preview digest. Oddzielna akcja **Run** zatwierdza tylko pokazany fixture READ. Po wyniku wybierz odczyt evidence; oczekuj `OFFLINE_FIXTURE` / `OFFLINE_LINKED_UNVERIFIED`, zgodnych tool_call_id/hashów i `live_verified=false`.
5. Utwórz kolejne preview i użyj **STOP** przed Run lub bezpośrednio po Run. Oczekuj `STOPPED`; ponowne Run starego tasku jest odrzucane. Po utracie ACK odczytuj evidence; nie ponawiaj efektu. Restart pending daje `UNKNOWN`, bez wznowienia.

Kod UI ma responsywną kolumnę dla małych ekranów. Nie certyfikowano renderowania ani przewijania w prawdziwym Chrome/Androidzie. Companion jest opcjonalnym klientem przyszłego tego samego API; gateway/APK są bez zmian.

## API i granice

Wszystkie nowe API wymagają istniejącego lokalnego session tokena i kontroli Origin/Host. Token pobiera klient tej samej strony; nie kopiować go do raportów lub komend z publiczną historią. POST wymagają dokładnego intent:

| Metoda/path | Intent | Efekt P02 |
| --- | --- | --- |
| GET `/api/meta/status` | — | Diagnostyka i lista misji |
| POST `/api/meta/preview` | `meta-preview-v1` | Dokładne `instruction`, `mode`, `target_url`; host ustala scope/limity |
| POST `/api/meta/run` | `meta-run-fixture-v1` | Tylko `task_id`, `preview_digest`; osobna zgoda na fixture |
| POST `/api/meta/stop` | `meta-stop-v1` | Tylko `task_id`; własna misja |
| GET `/api/meta/evidence/<task_id>` | — | Scoped Core readback |

`LIVE` w preview pokazuje `LIVE_PENDING_AUTHORIZATION`. Run zwraca 403 `META_API_LIVE_BLOCKED_OWNER_GO`; nie ładuje klucza i nie wykonuje requestu. Lokalna sesja i syntetyczny owner profilu OFFLINE nie są zgodą na koszt lub native execution.

## Bezpłatna kontrola bramki smoke

```bash
cd /home/l/projects/AIOA-spArkHAT-META && PYTHONDONTWRITEBYTECODE=1 python3 -B -m runtime.webapp --meta-live-one-shot
```

Komenda **tylko raportuje blokadę**, `api_calls: 0` i wymagania. Nie zawiera wbudowanego `operator_approved=true` dla LIVE i nie staje się płatnym testem przez samą obecność klucza. Transport Meta jest zaimplementowany oraz testowany przez mock, ale CLI nie dostarcza rzeczywistego native host binding. Domyślne rozbrojenie jest celowe.

## Billing: czynności właściciela przed P03

Stan: `BILLING_OWNER_CHECK_REQUIRED`. Nie potwierdzono salda, kwoty 150 USD ani uprawnień pliku klucza do konkretnego API. Nie potrzeba przesyłać sekretu.

1. Zaloguj się osobiście do [Meta developer console](https://dev.meta.ai/) i wybierz projekt, do którego należy używany Meta Model API key. Potwierdź typ klucza i dostęp do `muse-spark-1.3`.
2. Sprawdź Billing/credits i limity wydatków w swoim projekcie. Zapisz potwierdzenie dostępności kredytu/limitów bez klucza, danych karty i innych prywatnych informacji. Salda nie da się wywnioskować z pliku.
3. Określ osobne GO: dokładny model `muse-spark-1.3`, maksymalny koszt USD, **1 request**, output/timeout i konkretny payload digest. Zaufany host musi utrwalić rzeczywiste Core admission, OWNER_APPROVAL, warrant oraz rezerwację powiązaną z tym requestem/source capsule/policy epoch. Wiadomość modelu, env flaga i samo kliknięcie lokalnego fixture Run nie wystarczają.

Przed takim GO P03 musi też zamknąć projekcję ostatniego rzeczywistego receipt z Core (R6). API-key metadata pozostają tylko exists/regular/owner/perms; w runtime loader działa dopiero po poprawnej walidacji authority. Żadnego wypisywania wartości, długości czy fingerprintu sekretu. Model cost jest rozliczany osobno od kosztu browser READ; estimate adaptera nie zastępuje Billing. Oficjalne [API](https://dev.meta.ai/docs/protocols/chat-completions) i [cennik](https://dev.meta.ai/docs/pricing-rate-limits).

## Osobna bramka Chrome LIVE

Obecny `ChromeReadAdapter` dopuszcza wyłącznie wstrzyknięty fixture driver. Nie ma włącznika pozwalającego ominąć `CHROME_LIVE_BLOCKED_CONTAINMENT`. Przed realnym surfowaniem trzeba mieć zatwierdzony driver i dowody izolacji profilu/DNS/egress, wyłączonych SW/WS/downloads/subresources/formularzy, owner-approved exact HTTPS origins i limitów jednej misji. Sprawdzenie URL przed nawigacją nie jest containment.

Nie korzystać z osobistego Chrome, istniejącego DevTools endpointu, cookies ani kont. Nie uruchamiać/pobierać Playwright lub Chrome jako ukrytej zależności. STOP może dotyczyć tylko własnego przyszłego dziecka, nigdy cudzych procesów. Browser LIVE i jego domeny wymagają osobnej zgody od Meta model/cost GO.

## Dowody i rollback

Zobacz [raport](migration/P02_INTEGRATION_REPORT_20261031.md), [macierz testów](../../reports/meta/P02_TEST_MATRIX_20261031.md), [JSON evidence](../../reports/meta/P02_EVIDENCE_INDEX_20261031.json). Pełne logi/review są w prywatnym root wskazanym w raporcie. Publiczny JSON zachowuje identyfikatory demonstracyjnego tasku, binding/hash i jawne etykiety fixture; nie zawiera tokena sesji ani prawdziwego API response.

Rollback dotyczy wyłącznie TARGET, po zatrzymaniu własnego serwera i sprawdzeniu `git status --porcelain --untracked-files=all`. Przy nieznanych zmianach zachować prywatną kopię i wstrzymać revert; nie stosować stash/reset/clean i nie kasować rekordów UNKNOWN. P01 i wszystkie źródła mają pozostać zachowane.

```bash
# Tylko przy czystym TARGET, bez aktywnego writera:
git revert --no-edit <SHA_commitu_zawierajacego_ten_runbook>
git revert --no-edit c0d535ac904ffafb3eec5fba9a0ac80bedba3482
git revert --no-edit 0c2ada5f554ce4e088c1afa22d4f679026b82511
```

SHA pierwszej komendy ustala `git log -1 --format=%H -- docs/meta/P02_MUSE_CHROME_RUNBOOK.md` przed rollbackiem. Revert tworzy nową historię; nie cofa niepewnego zewnętrznego efektu ani nie odtwarza zużytego warrantu. Jeśli Git zgłasza konflikt, zachować stan i rozwiązać tylko własne zmiany; brak automatycznego resetu.

Push nie został wykonany. Do osobnego zatwierdzenia właściciela: `git push origin AIOA-METAGuardiansSPARK`.
