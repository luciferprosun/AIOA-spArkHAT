# P02 — macierz dowodów, 2026-10-31

Wszystkie wykonane próby: **OFFLINE_TESTED**, zero kosztów Meta/Nebius i zero prawdziwych uruchomień Chrome. PASS dotyczy podanego zakresu. `META_API_LIVE_VERIFIED` i `LOCAL_CHROME_TESTED`: brak.

Prywatny root `E=/home/l/projects/META_INTEGRATION_PRIVATE_20261031/20261031T143446Z` (0700). Logi nie są publikowane do Git. Hashy logów i końcowych plików szukaj w [evidence index](P02_EVIDENCE_INDEX_20261031.json). Polecenia wykonywano z `/home/l/projects/AIOA-spArkHAT-META`, z `PYTHONDONTWRITEBYTECODE=1`.

| Próba | Komenda / harness | PASS | FAIL | SKIP | Artefakt |
| --- | --- | ---: | ---: | ---: | --- |
| P01 baseline | `python3 -B -m unittest discover -s tests -p 'test_meta_*.py' -q` przed zmianami | 186 | 0 | 0 | `E/BASELINE_META.log` |
| Meta po review/fix | ta sama komenda, final bytes | 228 | 0 | 0 | `E/META_FINAL.log`, `FINAL_QA.json` |
| UI client | `node --test tests/meta_mission_ui.test.cjs` | 4 | 0 | 0 | `E/NODE_FINAL.log` |
| Core warrants | `python3 -B -m unittest discover -s tests -p 'test_core_warrant.py' -q` | 13 | 0 | 0 | `E/CORE_WARRANT.log` |
| Istniejący MCP | `python3 -B -m unittest discover -s tests -p 'test_mcp_*.py' -q` | 99 | 0 | 0 | `E/MCP.log` |
| Legacy web | poniższy izolowany harness: `test_webapp.py` | 7 | 0 | 0 | `E/LEGACY_WEB_ISOLATED.log` |
| Routing boundary | ten sam harness: `test_routing_boundary.py` | 14 | 0 | 0 | `E/ROUTING_ISOLATED.log` |
| Nebius provider | ten sam harness: `test_nebius_provider.py` | 15 | 0 | 0 | `E/NEBIUS_PROVIDER_ISOLATED.log` |
| JS parser | `node --check web/app.js` | exit 0 | — | — | `E/JS_SYNTAX.log` |
| Whitespace diff | `git diff --check`, także staged | exit 0 | — | — | `E/DIFF_CHECK.log` |
| Rzeczywisty lokalny CLI/HTTP | prywatny `E/run_app_probe.py`, własny subprocess/port, publiczne fixture dane | exit 0 | — | — | `E/APP_PROOF.json`, `APP_LIFECYCLE.json` |
| Zachowanie źródeł | read-only HEAD/branch/status i 54 SHA-256 z ledgera P01 | zgodne | 0 | — | `E/PRESERVATION_CHECK.json` |
| Skan sekretów | jawnie zmienione pliki + staged bytes, wzorce kluczy/PEM, bez odczytu rzeczywistego sekretu | 0 trafień | — | — | `E/SECRET_SCAN_CODE.json`, końcowy scan |

228 zawiera całe wcześniejsze 186. Przyrost 42: provider 18, browser 5, mission service 13, web 6. Testy Node są osobną liczbą, nie wliczamy ich do Python. Liczba subtests nie jest przedstawiana jako dodatkowe testy.

## Scenariusze i powiązania

| Grupa | Istotne cases | Źródło / ograniczenie |
| --- | --- | --- |
| Provider 18 | model/usage/tool_call_id; DISABLED przed key/HTTP; forged write/approval/URL; niepoprawny JSON/finish_reason/duplicate calls; 401/403/402/429/503 redacted i bez retry; budget/STOP/timeout; prywatny key loader; brak fallbacku; niezależny input/output limit | `tests/test_meta_model_api.py`; wszystkie odpowiedzi i klucze syntetyczne |
| Provider native-shaped | rzeczywiste testowe Core/warrant/governor; UNKNOWN budget hold przed HTTP; replay; brak zapisanego approval → 0 key reads; expiry/model/source/capsule drift; escaped synthetic key nie trafia do receipt | Ten sam plik; HTTPS i loader podmienione, **nie dowód LIVE** |
| Browser 5 | prywatny usuwany profil; content/screenshot hash; URL/scheme/IDNA/private IP; redirect/DNS/subresource/download/SW odmowa; LIVE bez containment odrzucone przed driverem; STOP i brak write surface | `tests/test_meta_chrome_read.py`; claimed DNS z fake drivera, nie rzeczywista izolacja sieci |
| Mission 13 | jedna kompozycja; brak owner/forged tenant; source/preview drift; jedna aktywna i jeden Run; STOP przed/w trakcie; brak receipt → UNKNOWN; restart bez wznowienia; LIVE pending bez call; brak raw instruction; approval ACK unknown; 1100 obcych rekordów; creation order | `tests/test_meta_mission_service.py`; prawdziwe klasy Core, jawnie fixture assignment |
| Web 6 | session/Origin/intent/extra-field odmowa; preview/run/evidence ten sam Core; brak owner override; LIVE 403/no spend; STOP/replay; zamknięte legacy effects | `tests/test_meta_web.py`; loopback HTTP, bez zewnętrznej sieci |
| UI 4 | jeden POST; poll GET; mock nigdy LIVE; lost ACK → readback bez retry; STOP exact task; reload/adopt bez Run | `tests/meta_mission_ui.test.cjs`; test klienta Node, bez DOM/Chrome |
| Dotychczasowe P01/P3 | contracts, authority, correlation/receipts, injection, MCP offline, replay i bounded mission read | istniejące `test_meta_*.py`, zachowane wszystkie 186 |
| CLI proof | rzeczywiste uruchomienie `--meta-offline`, HTML/JS, session w RAM, exact Run/evidence, receipt binding, replay 409, drugi task STOPPED, exit 0 | Publiczna projekcja w evidence index; brak rzeczywistego Muse/Chrome |

## Izolacja legacy suite i zachowane błędy harnessu

Pierwsze wywołania zachowane jako `LEGACY_WEB.log`, `ROUTING.log`, `NEBIUS_PROVIDER.log` nie były zielone: importy `main/providers` zależały od kanonicznego bootstrapa, a routing test zakładał brak skonfigurowanego klucza. Wczesny legacy discovery mógł załadować istniejącą konfigurację providerów do procesu testowego; wartości nie wypisano i nie wykonano API call. Następne wywołania świadomie wyłączyły discovery prywatnych env. Nowy profil `meta_only=True` w ogóle go nie uruchamia. Nie odczytywano wartości Meta API key.

Powtarzalny harness (wybierz dokładnie jeden wzorzec z tabeli):

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -B - <<'PY'
import os
import unittest
from unittest.mock import patch
import runtime  # istniejący bootstrap repozytorium
import providers.config as config

for name in tuple(os.environ):
    if any(part in name.upper() for part in ('API_KEY', 'TOKEN', 'SECRET')):
        os.environ.pop(name, None)  # wyłącznie bieżący proces testowy
with patch.object(config, 'API_FILE_CANDIDATES', ()):
    suite = unittest.defaultTestLoader.discover('tests', pattern='test_webapp.py')
    result = unittest.TextTestRunner(verbosity=1).run(suite)
raise SystemExit(0 if result.wasSuccessful() else 1)
PY
```

Nie ma deklaracji pełnej regresji całego AIOA ani certyfikacji historycznego Core M12. Nie wykonywano kosztownych/efektowych suites, realnego Meta API, fizycznego Androida ani przeglądarki.

## Review i TDD

Logi RED/GREEN zachowano prywatnie: `PROVIDER_*`, `BROWSER_*`, `MISSION_*`, `WEB_*`, następnie `REVIEW_PROVIDER_RED/GREEN.log` i `REVIEW_MISSION_RED/GREEN.log`. Review kopii sprzed poprawek: 4 Important + 2 Minor, bez Critical. Główny wykonawca podniósł R5 do Important i zamknął R1–R5 jedną rundą TDD; później 228 + 4 PASS. R6 Minor (projekcja ostatniego rzeczywistego LIVE receipt/Billing w diagnostyce) świadomie DEFER przed włączeniem LIVE w P03. Nie uzyskano drugiego niezależnego review końcowych bytes. Wcześniejszy APP_PROOF zastąpiono próbą po fixach, zawierającą `provider_receipt.binding`.
