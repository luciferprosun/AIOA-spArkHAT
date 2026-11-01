# P03 — macierz testów i dowodów, 2026-10-31

Końcowa regresja: **265/265 Python Meta, 7/7 Node, Core13/13, MCP99/99; 0 FAIL, 0 ERROR, 0 SKIP**. Python i Node liczone osobno, subtests nie są dodatkowymi testami. Baseline228 Meta +4 Node; przyrost37 Python +3 Node. LIVE Meta/publiczny Chrome/telefon nie są wliczane do PASS.

TARGET `/home/l/projects/AIOA-spArkHAT-META`. Prywatny `E=/home/l/projects/META_INTEGRATION_PRIVATE_20261031/P03_20261031T163047Z`. Wszystkie komendy Python z `PYTHONDONTWRITEBYTECODE=1`; logi, screenshoty i stany testowe pozostają prywatne. Hashe: [P03_EVIDENCE_INDEX_20261031.json](P03_EVIDENCE_INDEX_20261031.json).

| Zakres / poziom | Komenda | PASS | FAIL / SKIP | Dowód |
| --- | --- | ---: | --- | --- |
| Baseline P01/P02, OFFLINE_TESTED | `python3 -B -m unittest discover -s tests -p 'test_meta_*.py' -q` przed zmianami | 228 | 0 / 0 | `E/BASELINE_META.log` |
| Finalne Meta, OFFLINE_TESTED | ta sama komenda po poprawkach | 265 | 0 / 0 | `E/META_SEALED.log`, `SEALED_QA.json` |
| UI client, OFFLINE_TESTED | `node --test tests/meta_mission_ui.test.cjs` | 7 | 0 / 0 | `E/NODE_SEALED.log` |
| Core warrant, OFFLINE_TESTED | `python3 -B -m unittest discover -s tests -p 'test_core_warrant.py' -q` | 13 | 0 / 0 | `E/CORE_SEALED.log` |
| MCP, OFFLINE_TESTED | `python3 -B -m unittest discover -s tests -p 'test_mcp_*.py' -q` | 99 | 0 / 0 | `E/MCP_SEALED.log` |
| Legacy web, isolated/offline | poniższy harness, `test_webapp.py` | 7 | 0 / 0 | `E/LEGACY_WEB.log` |
| Routing boundary, isolated/offline | ten sam harness, `test_routing_boundary.py` | 6 | 0 / 0 | `E/ROUTING.log` |
| Nebius provider, isolated/offline | ten sam harness, `test_nebius_provider.py` | 15 | 0 / 0 | `E/NEBIUS_PROVIDER.log` |
| JS syntax | `node --check web/app.js` | exit0 | — | `E/JS_SEALED.log` |
| Whitespace | `git diff --check`, także cached | exit0 | — | `E/DIFF_SEALED.log`, końcowy check |
| Rzeczywisty CLI/HTTP fixture/restart | `python3 -B E/run_http_probe.py HTTP_SEALED` | PASS | — | `E/HTTP_SEALED/HTTP_E2E_PROOF.json` |
| Prawdziwy own Chrome, LOCAL_UI_BROWSER_TESTED | `NetworklessChromeReadDriver.capture_ui`, narrow/wide | 2 próby PASS | — | `E/CHROME_{NARROW,WIDE}_SEALED/CHROME_UI_PROOF.json` |
| Meta rzeczywisty provider response | Nie uruchomiono bez GO/Billing | **BLOCKED_EXTERNAL** | Nie jest skip testu | actual paid calls0 |
| Publiczny Chrome research / fizyczny Android | Nie uruchomiono | **BLOCKED_EXTERNAL / DEFERRED** | Nie jest skip testu | brak takich dowodów |

Po końcowym commicie wykonuje się wymagany check odpowiadającego fragmentu (P03 cases, provider fixtureV2 i Node) oraz osobny HTTP/restart na końcowym HEAD; komendy, counts i wynik są w prywatnym FINAL_VERIFICATION.json. Publiczny index wiąże opisany wcześniejszy snapshot kodu z jego dokładnymi working-tree seals; nie udaje SHA własnego przyszłego commitu.

## Nowe37 przypadków Python i rozbudowane7 Node

| Plik | Liczba | Co dowodzi / granica |
| --- | ---: | --- |
| `tests/test_meta_p03_receipts.py` | 17 | NOT_ATTEMPTED; durable scoped receipt; brak nowego spend; timeout/401/402/403/429/5xx; model mismatch; restart/inflight; ACK loss; late response; STOP i UNKNOWN hold; missing approval; corrupt usage; nowa sesja Core; extra confidential fields/bad cost; skoordynowana podmiana bindingu; A success→B failure/UNKNOWN→restart; non-USD przed kluczem/HTTP |
| `tests/test_meta_p03_native_host.py` | 6 | Brak owner binding=0 key/HTTP; exact native port do istniejącego managera/Core; brak podstawienia browser fixture za LIVE; payload mismatch; inny Core przy tym samym scope; STOP; single-active LIVE pending i restart bez wznowienia |
| `tests/test_meta_p03_chrome_process.py` | 11 | Public navigation deny before Popen; mount/env/network restrictions; cancel before launch; bounded output; timeout/STOP; własny child reaped; symlink denial; source drift także governor/cancellation/warrant/persistence; EOF+STOP; exited leader z potomkiem trzymającym pipe |
| `tests/test_meta_p03_web.py` | 3 | Addytywna uczciwa R6; approved intent bez native ownera nadal403; HTTP nie przyjmuje authority/budżetu |
| `tests/meta_mission_ui.test.cjs` | 7 łącznie | Dotychczasowe4 + exact native intent/one POST; UNKNOWN/LIVE pending bez fixture label; uczciwy native tekst i brak przedwczesnego consumed |

Native-shaped przypadki mają prawdziwe klasy CoreWarrantLedger/CoreDualGovernor/TransactionRunner, ale testowy backend, syntetyczny principal admission, credential i podmieniony HTTPS. Ich `live_verified` jest testem protokołu kodu, **nie META_API_LIVE_VERIFIED w tej sesji**. Nie kopiujemy syntetycznych LIVE receiptów do publicznych dowodów rzeczywistego wykonania.

Wszystkie wcześniejsze228 przypadków Meta pozostają w discovery. W `test_meta_model_api.py` zachowano18 dotychczasowych cases, zmieniając wyłącznie syntetyczny warrant builder na jawny operationV2/public-binding digest. Starszy warrantV1 nie uzyskuje automatycznie V2 authority. READ fixture/MCP/HTTP kontrakty P01/P02 pozostają zgodne.

## Wykonane end-to-end

HTTP: rzeczywisty subprocess istniejącego launchera i prywatny state-dir, `/status` → Preview → EXACT Run → evidence → replay409 → druga misja Run/STOP → kolejna pending → zamknięcie/restart → UNKNOWN. Stary session token403, ponowienie starej/pending409, żaden tool nie wznawia się. Własne oba procesy exit0. Token wyłącznie w RAM, nie w artefakcie.

Chrome: kernel network namespace różny od hosta, tylko loopback, brak tras/capabilities/HOME właściciela; odczyt istniejącego UI na własnym localhost. Własny profil0700, domyślny sandbox Chrome bez `--no-sandbox`, prawdziwy PNG/hash/visible-text hash. Preview/Run/evidence/STOP/scroll PASS. Obserwowane CSS viewports500×757 oraz1280×813; PNG390×844 i1280×900. **PNG390 nie certyfikuje390CSS ani Androida.** OS isolation nie zapewnia autoryzowanego publicznego egress; public navigate_read nadal odmawia.

## RED/GREEN i niezależny review

- `G1_RED/GREEN`, `G1_INTEGRITY_RED/GREEN`, `G2_RED/GREEN`, `G3_RED/GREEN`, `G4_NODE_RED/GREEN`, `G4_WEB_RED/GREEN` — nowe funkcje.
- Prywatny snapshot35 plików, range44bf162..6b75518: reviewer tylko czytał, niczego nie uruchamiał i nie dotknął TARGET. Verdict REQUEST CHANGES, 0 Critical/5 Important/2 Minor. Parent podniósł M1 (paid operation opisany jako free fixture) i M2 (waluta approval) do Important.
- `REVIEW_RECEIPT_RED.log`, `REVIEW_R3_PRECONDITION_RED.log`, `REVIEW_PROCESS_RED.log`, `REVIEW_UI_RED.log` → `REVIEW_RECEIPT_GREEN_FINAL.log`, `REVIEW_PROCESS_GREEN.log`, `REVIEW_UI_GREEN.log`. Zamknięte wszystkie7 w jednej rundzie, później pełne SEALED_QA265/7/Core13/MCP99. Brak drugiego niezależnego review final bytes; brak deferred minors.
- Początkowa próba Chrome z niewłaściwym przekazaniem service oraz próby po review z wyprzedzającym virtual-time zachowane jako failed/timeout artifacts. Zidentyfikowano błędy harnessu, nie ukryto wyniku. Namespace-local wall-clock barrier synchronizuje test z rzeczywistym fixture delay; nowy dowód po poprawce PASS, bez zmiany produkcyjnego API lub statusów.
- Ścisła walidacja UTC ujawniła niekanoniczny zapis `created_at`; poprawiono źródło zapisu na UTC Z i ponowiono regresję. Test R3 najpierw poprawił precondition, aby wywołanie B rzeczywiście doszło do kontrolowanej porażki, następnie dowiódł braku last receipt; log pierwotny również zachowany.

## Izolowany harness legacy

Uruchomiono kolejno z patternami `test_webapp.py`, `test_routing_boundary.py`, `test_nebius_provider.py`; bieżący routing boundary to6 cases, nie przedstawiamy historycznego14 jako aktualnego wyniku tej komendy.

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -B - <<'PY'
import os, unittest
from unittest.mock import patch
for name in tuple(os.environ):
    if any(part in name.upper() for part in ('API_KEY','TOKEN','SECRET')):
        os.environ.pop(name, None)
import runtime
import providers.config as config
import runtime.providers.config as meta_config
with patch.object(config,'API_FILE_CANDIDATES',()), patch.object(meta_config,'API_FILE_CANDIDATES',()):
    suite=unittest.defaultTestLoader.discover('tests',pattern='test_webapp.py')
    result=unittest.TextTestRunner(verbosity=1).run(suite)
raise SystemExit(0 if result.wasSuccessful() else 1)
PY
```

Nie wykonywano full-project/endurance GOLD72, certyfikacji Core M12, realnej płatnej inferencji, testu kont/Billing ani fizycznego telefonu. Skan sekretów to wzorce na jawnie zmienionych/staged plikach oraz source/code seal verification; nie odczytuje rzeczywistego klucza i nie porównuje z jego wartością lub fingerprintem.
