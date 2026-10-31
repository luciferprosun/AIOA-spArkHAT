# AIOA spArkHAT — METAGuardiansSPARK

## Pochodzenie źródeł 26–31.10.2026, migracja P01

AIOA jest istniejącym produktem. Ta migracja przenosi neutralny kontrakt
narzędzi i składa istniejące porty Core oraz adaptery offline. Nowy model,
nowy Core, drugi approval engine lub drugi interfejs nie zostały uruchomione.
Nowe zmiany migracyjne wykonał Codex 31.10.2026. Nie przypisujemy tych zmian
ani wcześniejszego kodu wywołaniu Muse bez takiego dowodu.

| Element | Zweryfikowane pochodzenie | Użycie w Meta |
| --- | --- | --- |
| CoreAdmission, warrant ledger, transaction port, MCP, pamięć/provenance | Istniejąca historia AIOA, obecna już w bazie target `0741d37db0630233b4e7212f6f3af6320106c792` | Importowane bez zmiany semantyki; brak drugiego Core lub bazy |
| strict_json, checked, ToolCall, ToolMessage | AIOA/Nebius/Nemotron, dirty working tree `feature/nebius-nemotron-integration-20261028`, HEAD `6e9dd8ebc1dcb2c03345d9dc7d30895013751cd5`; plik tool_calling.py był untracked | Neutralny podzbiór przeniesiony do `runtime/providers/tool_calling.py`; AST czterech definicji zgodny ze snapshotem working tree |
| read_contracts/public_read/local_zero/native_read i bridges | Inżynieria AIOA/Nebius z października, w tym niezatwierdzone w Git zmiany; zależności Nebius/WorkspaceStore/prototype | Zachowane w źródle i wybranym prywatnym snapshocie; natywny READ START/ServiceGuard nadal DEFER/BLOCKED |
| BrowserTaskV1, read_fixture, OfflineTaskState, OfflineReceiptLedger, OfflineCorrelationLedger | Zastane moduły Meta w bazie target `0741d37` | Ponownie użyte bez zmian kontraktów; dowody jawnie syntetyczne/offline |
| mission_runner_offline.py i test_meta_mvp_runner.py | Zastane untracked pliki w target; dokładne hashe poniżej | Zachowane bajtowo, objęte QA i lokalnym checkpointem. Nagłówek „Muse-authored” jest zastaną deklaracją; P01 nie ustala tożsamości modelu, który je napisał |
| mission_read_offline.py i test_meta_migration_read.py | Nowa adaptacja P01, Codex, 31.10.2026 | Wąska kompozycja Core warrant → bounded fixture READ → correlation → odpowiedź tool o tym samym call_id |
| Nemotron CLI, Token Factory/budżety, Git WRITE, sandbox, cloud, GOLD72 | Oddzielne wcześniejsze ścieżki AIOA/Nebius/Nemotron | Nie aktywowano i nie przedstawiono jako Meta |

Hashe zachowanych plików target:

- `runtime/meta_hackathon/mission_runner_offline.py`:
  `1e7dd58ebcf22cbe0e84f2b467e43492cea2cb8952de917c94f45320fdfc363a`.
- `tests/test_meta_mvp_runner.py`:
  `765d1639d57d48fd5cbf8c28b30ac15382b8858d71732c462f2915fcb88da66f`.

Pełne hashe wybranych dirty source bytes oraz decyzje PORT/REUSE/DEFER są w
[IMPORT_LEDGER_20261031.md](IMPORT_LEDGER_20261031.md). HEAD źródła nie jest
zastępstwem dla tych hashy.

## Historyczne dowody a bieżąca weryfikacja

Oryginalny raport operatora:
[AIOA_RAPORT_DLA_ARCHITEKTA_20261030.md](/home/l/Downloads/AIOA_RAPORT_DLA_ARCHITEKTA_20261030.md),
data oryginału 30.10.2026. Jest to lokalny materiał źródłowy; nie skopiowano
go do publicznego drzewa. P01 nie weryfikuje autorstwa raportu niezależnie od
zastanych metadanych.

Raport opisuje dwa historyczne bounded READ roundtripy Nebius/Nemotron.
Nie uruchamiano ich ponownie. Nie są dowodem działania Muse, Chromium Meta,
Android ani bieżącej dostępności modelu lub salda. Identyfikator prywatnego
snapshotu w raporcie to `500f0f3a9e211800aaf810656a87a97d03cec098`.
Nie znaleziono tego obiektu w lokalnych object stores wskazanego source
ani target. Dostępność osobnego bundle pozostaje UNKNOWN; nie kopiowano,
nie materializowano i nie publikowano całego prywatnego snapshotu.

Bieżące P01 potwierdza tylko testy OFFLINE oraz zgodność zachowanych bajtów.
Demo ma syntetyczny source SHA `1111111111111111111111111111111111111111`,
nie SHA bieżącego checkoutu. Receipt modelu ma charakter MOCK przy koszcie
0.00 USD. Zużycie warrantu oznacza jednorazowe użycie ledgera; jego
effect_verified=false nie zostało zamienione na dowód LIVE.

## Co nie zostało przeniesione

Nie kopiowano .env, kluczy, cookie/OAuth, profili przeglądarki, prywatnych baz,
prompt histories, pełnych reports/agent24h, nagrań, screenshotów ani bundle.
Nie zmieniano oryginalnych raportów, licencji, namespace, dat ani historii Git.
Repozytorium i gałąź zachowują swoje nazwy. Dla nowych dokumentów obowiązuje
produkt AIOA spArkHAT z podtytułem METAGuardiansSPARK.
