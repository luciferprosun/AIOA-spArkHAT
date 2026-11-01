# AIOA spArkHAT / METAGuardiansSPARK — uruchomienie P03

Profil domyślny: **OFFLINE_INTEGRATED**, model i browser fixture. Rzeczywisty Meta model/publiczny browser READ/telefon nie mają certyfikacji LIVE.

## Jedna sprawdzona komenda

```bash
cd /home/l/projects/AIOA-spArkHAT-META && PYTHONDONTWRITEBYTECODE=1 python3 -B -m runtime.webapp --meta-offline --port 0
```

Terminal wypisze `http://127.0.0.1:<port>`. Ten sam istniejący `runtime.webapp` obsługuje jeden `web/` Mission Control i Core. Nie otwiera portu publicznego, nie restartuje 4314/4315. Stan fixture: prywatny `~/.local/state/aioa-meta-offline-v1`, lease blokuje drugą instancję tego samego profilu. Zakończenie własnego serwera: Ctrl+C.

## Pięć działań operatora

1. Otwórz dokładny adres z terminala. Wejdź do METAGuardiansSPARK w tej samej aplikacji. Sprawdź etykietę `OFFLINE FIXTURE`, model `muse-spark-1.3`, transport `mock`. Telefonowy `127.0.0.1` wskazuje telefon, dlatego fizyczny Android wymaga osobnego, audytowanego transportu; nie otwierać tunelu.
2. Sprawdź R6: `NOT_ATTEMPTED`, ostatni rzeczywisty receipt `none`, Billing `UNVERIFIED`, credit `unverified`, Spend permission `not granted`. Key configured jest tylko metadanymi pliku, nie próbą API. Koszt modelu tej demonstracji: 0 USD.
3. Zostaw `OFFLINE_FIXTURE` i hostowy URL `https://docs.example.org/offline-fixture`, wpisz krótkie zadanie i wybierz Preview. Nazwa URL identyfikuje bundlowany dokument; aplikacja nie pobiera go z Internetu. Oceń dokładny task/source/capsule/correlation/preview digest.
4. Wybierz osobne **Approve exact fixture READ & run**. Odczytaj Evidence: `OFFLINE_FIXTURE`, `OFFLINE_LINKED_UNVERIFIED`, zgodny tool_call_id, warrant consumed i evidence digest; `live_verified=false`. To rzeczywisty przebieg Core nad fixture, bez odpowiedzi modelu Meta i bez publicznej nawigacji.
5. Utwórz kolejną misję i sprawdź STOP przed Run lub zaraz po Run. Utrata ACK oznacza GET readback, nigdy automatyczny drugi POST. Ponowienie zużytej misji daje 409. Pending po restarcie ma UNKNOWN i nie wznawia się. Przycisk Read evidence odświeża także diagnostykę receiptu.

## Co jest zaimplementowane dla Meta LIVE

Istniejący ProviderManager prowadzi dokładny `MetaPlanRequest` do domyślnie wyłączonego MetaModelProvider, bez fallbacku. Zaufany native host może dostarczyć **istniejące**, już autoryzowane `MetaLiveBinding` (CoreWarrantLedger, CoreDualGovernor, sealed principal, dokładny warrant/rezerwacja, source reader). Native-only port `MissionService.bind_live_request(task_id, request, binding)` nie wystawia authority ani nie tworzy rezerwacji: sprawdza i wiąże dostarczoną decyzję Core. Nie ma HTTP endpointu przyjmującego ownera, warrant, `operator_approved`, kwotę lub origin od modelu.

Po związaniu operator musi odczytać nowy dokładny preview digest. HTTP Run ma odrębny intent `meta-run-approved-v1`; dotychczasowy intent fixture zachowano dla P02. Modelowy JSON pozostaje ADVISORY_ONLY. Walidacja approval/source/capsule/nonce/expiry/epoch/reservation odbywa się przed odczytem klucza, a dispatch-commit/warrant consume i UNKNOWN budget hold przed HTTPS. Jeden request; nie ma retry po niepewnym wyniku.

Zredagowany attempt i receipt zapisują się w istniejącym scoped OPERATION/RECEIPT/CAS. Diagnostyka odczytuje i weryfikuje te rekordy; nie otwiera kolejnej bazy. COMPLETED oznacza poprawnie odczytaną i zapisaną odpowiedź modelu, nie prawo do kolejnego wydatku ani autoryzację browser READ. Nawet po odpowiedzi Meta misja pozostaje BLOCKED, dopóki brak osobno autoryzowanego, izolowanego READ; nie podstawia fake browsera jako LIVE.

Wymagany native kontrakt spend: `META_MODEL_PLAN_V2`, obejmujący także digest pokazywanego public binding/token/timeout bounds i walutę USD. Nie przenosić starych warrantów V1 do V2 automatycznie. R6 pokazuje ostatnią próbę i ostatni poprawny receipt osobno, więc późniejszy timeout/401 nie ukrywa wcześniejszego dowodu i nie nadaje prawa retry.

## Osobne GO Meta — jeszcze niewykonane

1. Właściciel osobiście sprawdza projekt, typ dostępu i saldo/limity w [Meta developer console](https://dev.meta.ai/). Nie wysyła klucza. Plik klucza nie dowodzi kredytów ani uprawnień. Bez niezależnego dowodu UI utrzymuje Billing UNVERIFIED, credits_confirmed=false i settled_cost=null; samo `billing_confirmed` w native konfiguracji jest deklaracją hosta, nie autorytatywnym odczytem salda.
2. Dostarcza rzeczywisty Core owner admission przez istniejący zaufany transport operatora. Domyślny `--meta-offline` zawiera jawnie syntetyczny owner i nie może pełnić tej roli. Host przygotowuje dokładny request i przedstawia jego digest, model `muse-spark-1.3`, limit kwoty do 0,05 USD, 1 próbę, output do 512 tokenów, timeout, task/source/capsule/policy epoch i nonce. Dopiero właściciel zatwierdza tę konkretną operację; istniejący governor rezerwuje dokładną kwotę i risk.
3. Po rzeczywistym admission/approval i potwierdzonym Billing host wiąże request przez native port. Operator uruchamia go raz. Niezależny readback porównuje request/attempt/correlation/model/usage/receipt z Core i oddzielnie rozlicza UNKNOWN budżetu. Brak ACK lub niepoprawny wynik nie daje prawa do retry. Prawdziwego salda i kosztu fakturowanego nie zastępuje lokalny estimate.

Bezpłatna inspekcja obecnej bramki:

```bash
cd /home/l/projects/AIOA-spArkHAT-META && PYTHONDONTWRITEBYTECODE=1 python3 -B -m runtime.webapp --meta-live-one-shot
```

Flaga zwraca blokadę i `api_calls: 0`; nie dostarcza native ownera, nie zatwierdza kosztu i sama nie uruchamia smoke. Nie ma komendy „włącz LIVE” przez env albo automatyczne `operator_approved=True`. Obecnie rzeczywisty owner binding i Billing są **BLOCKED_EXTERNAL**, więc nie ma podstaw do wykonania tego płatnego kroku. Oficjalny kontrakt: [Chat Completions](https://dev.meta.ai/docs/protocols/chat-completions), [ceny i limity](https://dev.meta.ai/docs/pricing-rate-limits).

## Chrome i lokalna kontrola UI

`chrome_process_read.py` uruchamia wyłącznie własny Chrome i istniejącą aplikację fixture w bwrap `--unshare-all`, z pustym HOME, bez owner secrets/profilu/host network, przy aktywnym sandboxie Chrome. Kernelowy brak tras/interfejsów poza loopback jest sprawdzany przed startem Chrome. Wykonane testy obejmują realne renderowanie, fixture Preview/Run/evidence/STOP, przewijanie i rzeczywisty PNG. Nie używano istniejącej sesji Chrome DevTools, `--no-sandbox`, instalacji ani uprzywilejowanych zmian hosta.

To `LOCAL_UI_BROWSER_TESTED`, nie publiczny Chrome research READ. Nowy driver odmawia `navigate_read` poza tą kontrolowaną próbą. Wyjście do Internetu wymaga osobno zatwierdzonego mechanizmu egress/DNS/redirect/subresource/WS/SW/download enforcement oraz exact HTTPS origin GO. Sam unshare-net daje brak sieci, nie kontrolowany dostęp do publicznych stron; nie wolno zastąpić go share-net lub osobistym profilem. Fizyczny Android i audytowany Companion transport pozostają DEFERRED: istniejące capabilities gateway deklarują tasks/chat/stop=false.

## Testy, dowody, zatrzymanie i rollback

Dokładne komendy/counts/ograniczenia: [macierz](../../reports/meta/P03_TEST_MATRIX_20261031.md), [evidence index](../../reports/meta/P03_EVIDENCE_INDEX_20261031.json), [raport](migration/P03_FINAL_MIGRATION_REPORT_20261031.md). Pełne logi, kopie i screenshoty są w prywatnym katalogu wskazanym w raporcie. Zwykły UI nie ładuje testowego `meta_p03_ui_probe.js`.

STOP dotyczy wyłącznie własnej misji. Ctrl+C zamyka własny serwer; supervisor testu Chrome zabija/reapuje tylko grupę procesu utworzoną przez siebie. STOP nie jest zwrotem pieniędzy i nie odwoła już wysłanego HTTPS. Nie kasować rekordów lub UNKNOWN, by uzyskać kolejny Run.

Rollback przy czystym TARGET, bez aktywnego writera i po zachowaniu nowych danych:

```bash
git revert --no-edit <SHA_koncowego_commitu_P03_z_tym_runbookiem>
git revert --no-edit 6b7551826aebe805558b4a10e61b717e36196e20
git revert --no-edit 937bf0b151394b4fbc4d9b24260703f3a4bd7dcf
```

Pierwszy SHA ustala `git log -1 --format=%H -- docs/meta/P03_FINAL_RUNBOOK.md`. Przy obcych zmianach zachować prywatne kopie/diff/untracked i wstrzymać revert; bez reset/clean/stash. Rollback nie cofa zużytej authority, zewnętrznego efektu ani audytu. P01/P02 i chronione źródła pozostają zachowane.

Push nie jest autoryzowany przez P03 i nie został wykonany. Dopiero po świeżej zgodzie właściciela: `git push origin AIOA-METAGuardiansSPARK`.
