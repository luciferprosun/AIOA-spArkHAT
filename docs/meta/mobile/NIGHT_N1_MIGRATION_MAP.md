# N1 — dokładne pochodzenie i granice migracji

TARGET: `/home/l/projects/AIOA-spArkHAT-META`, branch `AIOA-METAGuardiansSPARK`.
Baseline `7387d823f38d1bc4ca964788ae11441d29b6ae6e`.
Źródła czytano bez zapisu; pełne 76 wybranych SHA plików:
[`N0_SOURCE_MANIFEST.json`](N0_SOURCE_MANIFEST.json).

| Źródło / commit | TARGET | Sposób użycia / licencja | Dowód |
| --- | --- | --- | --- |
| Companion `protocol/CONTRACT.md`, `9cf6c567b40bc87385fb90e9143b0fb170889b2a` | `protocol/mobile_mission_v1.json`, `runtime/mobile_gateway/wire.py` | **Adapted facts / neutral implementation**, brak ustalonej licencji kodu projektu; bez kopiowania raw source; nowy namespace MobileMissionV1 | Python wire7, public DER vector |
| Companion signed host proof/enrollment/auth kontrakty, ten sam SHA | `runtime/mobile_gateway/service.py` | Neutralny P256/DER/SPKI, prebound code TTL≤300, session TTL600, nonce/CAS; transport w istniejących Core records, bez źródłowego SQLite | testy gateway/HTTP; 51 źródłowych testów w prywatnej kopii |
| AgentLab `AgentLabClient.kt`, `RemoteTransport.kt`, `AgentLabScreen.kt`; `fb8642f108aea7db5db7a0b1446d4145f4167991` | `clients/android/app/src/main/java/eu/sparkhat/aioa/companion/` | **Neutral source** zgodne z ideą podpisanego klienta, jeden istniejący pakiet, bez importu nieustalonej licencyjnie implementacji, bez nowego app/Core | Python SOURCE10, Node SOURCE3, Kotlin JVM10 przygotowane, NOT_RUN |
| Companion `android/gradle/wrapper/gradle-wrapper.jar` | `clients/android/gradle/wrapper/gradle-wrapper.jar` | Jedyny **Imported** artefakt: niezmieniony upstream Gradle8.13, niezależnie zgodny z oficjalnym SHA, dołączona oryginalna licencja Apache2 | wrapper SHA `81a82aaea5abcc8ff68b3dfcb58b3c3c429378efd98e7433460610fecd7ae45f` |
| Companion Android build facts (SDK36/Gradle8.13/JDK17) | `clients/android/*.kts`, wrapper properties i build manifest | Nowe neutralne pliki; wersja pakietu0.2.0-n1/code2; zgodność toolchainu sprawdzona z upstream AGP | `ANDROID_BUILD_INPUT_MANIFEST.json`; build NOT_RUN |
| Własny publiczny wektor testowy N1 `tests/fixtures/mobile_wire_vector.json` | `clients/android/app/src/test/resources/mobile_wire_vector.json` | Niezależnie wygenerowany P256 SPKI/DER signature, private key odrzucony; standardowy zasób JVM zamiast importu całego drzewa fixtures | dokładna zgodność JSON, hash zasobu objęty build manifestem |
| Istniejący TARGET `runtime/meta_hackathon/mission_service.py`, `runtime/core_admission.py`, `runtime/mission/warrant.py`, persistence ports | Wywołania z `service.py`; tylko MissionService dostaje bounded `evidence_many` | **Reused directly**, MIT; jeden Core, runner, OPERATION/AUDIT/warrant/receipt; sesja mobilna nie tworzy warrantu | rzeczywisty fixture Core run/consume/readback, Core13 PASS, batch READ2 |
| Istniejący TARGET `runtime/memory_patch/audit.py` i `persistence/idempotency.py` | Bezpośrednie wywołanie `append_domain_event` / `OperationBinding` przy każdej rewizji transportu | **Reused**, bez zmian tych modułów; natywny audit/outbox zamiast konkurencyjnego payloadu | mieszany native/mobile/native chain, require_record_audit i storage reopen |
| Istniejący TARGET `runtime/webapp.py` | Ten sam plik, opcjonalny `mobile_gateway=` i zamknięte trasy | **Adapted**, MIT; ten sam listener/serwis, oddzielna auth podpisem zamiast sesji loopback UI | lokalne signed HTTP i denial CSRF/CORS/headers |
| Istniejący TARGET `runtime/meta_hackathon/runtime_adapter.py` | Ten sam source capsule, poszerzony o mobile/contract/Android | **Adapted**, MIT; brak drugiej kompozycji providerów/authority | test zmiany bytes kapsuły |
| Istniejący TARGET `runtime/browser_agent/chrome_process_read.py` | Read-only bind wyłącznie wskazanych plików source capsule z `protocol`/`clients`, bez całych drzew/cache/APK | Zgodność poszerzonej kapsuły; symlink odmowa przed bind; bez publicznego READ | mount construction2 + source seal2; public calls0 |
| Tailscale metadane i oficjalne instrukcje | `runtime/mobile_gateway/doctor.py`, setup PL | **New passive adapter**, tylko booleans; opcjonalne owner-produced JSON, bez subprocess/zmian sieci | doctor3; real passive ports; peer/TLS UNKNOWN |
| Nebius/Nemotron, M12, GOLD72, LSC | Brak docelowej migracji | **Deferred / read-only protected**; brak portu, restartu, importu baz/sekretów | niezmieniony Nebius HEAD/status; źródłowe hashe |
| Stary APK Companion0.1.0 | Brak kopii i podmiany | **Preserved**; nie potwierdza N1 | SHA `43943d19196d26e3be93015d1d6f1cad87a49f94015978ce40afa7ccce4725c6` |

Każdy nowy plik/rozmiar/hash Androida jest w
`clients/android/ANDROID_BUILD_INPUT_MANIFEST.json`; nie wprowadzono zależności
Pythona ani instalacji. Python `cryptography` już był dostępny. Zadeklarowane
zależności Android nie zostały pobrane; notices i ograniczenia w `clients/android/NOTICE.md`.

## Co pozostało do wykonania

Produkcja wymaga osobnego natywnego adaptera qualified TLS edge do jednego
WebRuntimeService, bezpiecznego host identity provisioning i realnego owner
admission w istniejącym Core; to nie jest tylko ustawienie adresu lub flaga.
N1 nie wydaje produkcyjnego kodu, nie otwiera publicznego listenera i nie używa
syntetycznego operatora jako realnego ownera. Brak kompletnego toolchainu oznacza
NOT_RUN dla kompilacji/JVM/lint, brak podpisanego nowego APK i Android E2E.
Osobne bramki: release signing, Xiaomi, LTE, revocation na telefonie, owner M12,
Meta LIVE/Billing, Chrome egress i produkcyjne approvals.

## Rollback

Nie ma migracji bazy produkcyjnej, usług ani source worktree. Wyłącz opcjonalne
`mobile_gateway` w kompozycji; zwykły launch `python3 -m runtime.webapp --meta-offline`
nie tworzy go automatycznie. Zachowaj dowody i prywatne fixture state poza repo;
nie kasuj operator state. W przyszłości można wykonać lokalne `git revert`
wyłącznie commitów N1 po sprawdzeniu czystego TARGET i aktualnego HEAD, w odwrotnej
kolejności, z testami regresji; nie uruchomiono rollbacku, reset/clean ani push.
Stare klienty, APK i historie pozostają na źródłach, bez destrukcyjnej konsolidacji.
