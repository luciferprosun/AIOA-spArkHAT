# Cosmic Master — kontrakty, stany i granice

Stan kodu: kontynuacja `4960ba2`, 2026-11-03. Ten dokument opisuje istniejące porty, a nie zgodę na ich uruchomienie. Fakty z testów i wdrożenia są w `CODEX_COSMIC_FINAL_IMPLEMENTATION.md`.

## Jedna kompozycja

`CosmicApp → MissionViewModel → MobileClient → MobileGateway → MissionService → Core/TransactionRunner/ServiceGuard`.

Linux: ten sam `web/index.html` pod `/devices`, istniejące `mobile_devices.js` i `mobile_devices_dom.js`, `WebRuntimeService.mobile_operator_request → NativeMobileComposition.operator_request`. Nie dodano backendu, journala, providera, bazy ani frontendu. Wąski adapter HTTP dopuszcza dodatkowo istniejące odczytowe `op=status`, po istniejącym bootstrapie z prywatnego socketu. Core nadal ponownie sprawdza realnego operatora, source/capsule, ważność, UID i dokładne pola operacji.

## Kontrakty

W tabeli v1 oznacza `/api/mobile/v1`, v2 `/api/mobile/v2`. Nazwy akcji i walidacja pochodzą z `runtime/mobile_gateway/wire.py`, `service.py`, `pairing.py`, `views_v2.py`; nie dodano trasy wykonania.

| Port / dokładny payload | Policy i dowód | Zainstalowany profil Native | Istniejący profil testowy offline |
|---|---|---|---|
| GET v1/capabilities, X-AIOA-Challenge | ECDSA, challenge, origin/audience, SPKI, SHA capabilities, source/capsule, expiry | Status/parowanie; run/approve/chat/spend/native_execute/github_write/install=false | OFFLINE_FIXTURE, remote deployment zablokowany |
| POST v1/pairing/begin, podpisany invite + request_id + device_name w podpisanej ramce urządzenia | TLS1.3/pin, podpis urządzenia, nonce, audience/source/capsule, limit i expiry | Rzeczywiste oczekujące żądanie; dokładna zgoda pozostaje na Linuxie | Nie jest produkcyjnym parowaniem telefonu |
| POST v1/pairing/status i /pairing/complete, request_id w podpisanej ramce | Powiązanie klucza/request digest, SAS, expiry, pojedyncze complete; niepewne complete bez retry | Zapisane urządzenie i ograniczona sesja statusu | Nie wolno przemianować na LIVE |
| POST v1/session/challenge (device_id), /session/reconnect (device_id, challenge_id, challenge_nonce) | Zapisane zatwierdzenie, jednorazowe wyzwanie, źródło, expiry/revocation, podpis telefonu | Obecna ścieżka reconnect, bez nowego QR przy zachowanym zaufaniu | Osobne testy syntetyczne |
| GET v1/status i /status/pages/{meta-id} | Bearer w nagłówku, podpis ramki i odpowiedzi, nonce, session/device, source/capsule/scope; max16 misji i128 indeksów | Rzeczywisty podpisany odczyt; brak podłączonego Workera i misji tego profilu | Pełne projekcje misji dokumentowych; status fixture jawny |
| POST v1/preview {proposal_id,instruction,mode:OFFLINE_FIXTURE,target_url:stały fixture}; GET /proposals/{id}; GET /evidence/{meta-id} | Zapis opaque ID przed jedynym POST, powiązanie session/device i task digest; UNKNOWN wymaga GET | 501 / capability=false, jawnie niedostępne | Istniejąca propozycja i dowody; telefon nie uruchamia ani nie zatwierdza |
| POST v1/stop {task_id} | Scope zadania i istniejący MissionService.stop; UI wymaga świeżej dokładnej obserwacji wybranego payloadu | Niedostępne, brak Workera | Istniejący STOP; UNKNOWN pozostaje UNKNOWN |
| GET v2/status, /tasks/{agent-id}, /providers, /proposals/{id} | Scope przed lookup; digest/source/capsule; pełna typed MissionViewV2; lista to tylko podsumowania | 501; brak worker/provider adapter w tym profilu | Istniejące obserwacje SensorBridge/Git i katalog; nie uprawnienie LIVE |
| POST v2/propose {schema:aioa.agent-proposal.v2,request_id,provider_id:meta_model_api,recipe_id:sensorbridge-v1} | Jeden pending ID, idempotency, Core READ, późniejsza oddzielna zgoda hosta | Niedostępne | Zachowana istniejąca propozycja SensorBridge + testy + README |
| POST v2/propose z recipe_id:git-commit-v1 i source_task_id | Powiązanie źródłowej misji, receipt lokalnego readback, SANDBOX_EXEC; approval na hostcie | Niedostępne | Zachowany lokalny podgląd Git; brak zdalnego push/PR z telefonu |
| POST v2/stop {task_id} | Dokładny wybrany payload, świeżość, Core; telefon nie zyskuje owner authority | Niedostępne | Istniejący STOP agenta |
| POST v1/session/revoke {} | Istniejące odwołanie sesji; brak automatycznego ponownego uzyskania uprawnienia | Dostępne dla swojej sesji | Testowy kontrakt zachowany |
| Prywatny socket, op=console → jednorazowy POST /devices | Kernel SO_PEERCRED, prawdziwy PolicyKit, lokalna aktywna sesja,30s ticket; brak tokenu w URL/argv | Otwiera ten sam panel z pamięciowym nagłówkiem CSRF | Test przeglądarki używa syntetycznej autoryzacji, nie dowodzi realnego ownera |
| POST /api/native-operator {op:pairing_list / pairing_invite / pairing_approve / pairing_revoke} z dokładnymi polami | Istniejący owner grant, origin, nagłówek CSRF; approve wymaga request_id + request_digest + SAS | Rzeczywiste zarządzanie urządzeniami przez właściciela | Nigdy automatyczne zatwierdzenie |
| POST /api/native-operator {op:status} | Ten sam grant; exact payload ponownie sprawdzany przez istniejący Core; tylko READ | Publiczny profil/tożsamość i do8 zapisanych podpisów/sesji; bez tokenów/kluczy prywatnych | Testowe dane jawnie oznaczone w harnessie |
| Czat, wybór providera, run/approve, install, GitHub WRITE | Brak kontraktu w Native; capability=false /501; selekcja modelu nie może tworzyć zgody | BLOCKED_NATIVE_PROFILE; to brak integracji tego profilu, nie brak budżetu | UI nie udaje działającej funkcji; brak nowych tras |

Odpowiedź mobilna wiąże metodę/ścieżkę, nonce, session_id/device_id, audience, source_sha, capsule_digest, owner_scope_digest, data_sha256, issued_at/expires_at i podpis hosta. Limity istniejącego wire: request16KiB, response64KiB, głębokość16, brak floatów i zduplikowanych kluczy. Błąd ramki lub nieznany efekt nie uruchamia ponowienia.

## Świeżość i wybór misji

`Freshness` opisuje transport. Nowe `TaskReadbacks` przechowuje hash całego zweryfikowanego payloadu, jego monotoniczną granicę ważności i czas hosta. Każda nowa operacja unieważnia stare deadline. Katalog, lista agentów, błąd, utrata sesji lub background nie odświeżają zaznaczonej misji. `RequestedTask(id,type)` zachowuje intencję wyboru po błędzie. Szczegóły, STOP i podgląd Git wymagają tego samego wybranego ID i payloadu; retry dotyczy dokładnie tego ID. Nieudany wybór B nie przełącza kontrolek na wcześniejsze A.

MissionCard rozróżnia pending/running/succeeded/failed/stopped/revoked/disabled/unknown i oznacza dane historyczne. SUCCEEDED wymaga istniejącego receipt; sam napis lub obecność pliku nie potwierdza wykonania. Nie ma fikcyjnego procentu: liczba kroków pochodzi z odczytanej tablicy, nieznana praca ma wskaźnik nieokreślony. `OFFLINE_FIXTURE` nie staje się LIVE.

## Ekrany i komponenty

Pełny inwentarz17ramek Figmy,12plansz Canvy i projektu MagicPath pozostaje w `COSMIC_DESIGN_INTEGRATION_READINESS.md` oraz `COSMIC_SOURCE_INVENTORY.json`. Odczyty MCP ponowiono dla Master. Canva: ID znalezione na koncie DAHZ2xNq8Ig,12stron; nierozwiązany skrót /d/ nie jest dowodem tożsamości ID. MagicPath468340598617829376 / ready-flood-7620 to UX, nie gotowy Kotlin ani LIVE.

| Ekrany źródłowe | Android | Linux |
|---|---|---|
| Home, Chat, Missions, Critical, GitHub, Approvals, Details, Activity, Providers | CosmicMissionPages.kt, wspólne CosmicComponents.kt | Istniejące sekcje data-cosmic-page w index.html i mobile_devices_dom.js |
| Devices, Pairing, Recovery, Settings | CosmicScreen.kt; te same callbacki MissionViewModel i MobileClient | Istniejący /devices i kanał operatora; urządzenia/zgody, publiczna tożsamość, odczyt historii |
| Foundations / Semantic States / Navigation | cosmic.tokens.json → cosmic_colors.xml; CosmicTheme, CosmicScaffold/TopBar/BottomNav/StatusChip | cosmic_tokens.css, styles.css, semantyczne sekcje i fokus |

Wspólne komponenty: CosmicScaffold/TopBar/BottomNav, StatusChip, MissionCard, ChatBubble, ApprovalCard, ReceiptPanel, ConnectionBanner, LoadingState, ErrorState, ProviderPicker, STOPButton. ProviderPicker pozostaje read-only, gdy kontrakt nie daje możliwości wyboru. ChatBubble prezentuje wyłącznie wyraźnie oznaczony niewysłany szkic; nie produkuje odpowiedzi.

`SaveableStateHolder` zachowuje destination i publiczne szkice/scroll/rozwinięcie artefaktów przy nawigacji/rotacji; ViewModel zachowuje pamięciową historię do32 zdarzeń metadata. Nie zapisuje bearerów, kodów enrollment ani prywatnych kluczy. UNKNOWN IDs pozostają w istniejących PendingHints i wymagają osobnego potwierdzenia dla dokładnego rodzaju/ID. Handoff zmienia tylko lokalną wskazówkę, nigdy Core UNKNOWN.

Przy klawiaturze pasek górny i dolny zwijają się; w krótkim oknie zostaje kompaktowe menu wszystkich tras. Back najpierw obsługuje IME. Dynamicznego font scale nie ograniczono; cele48dp, przewijane strony i treść dialogów, semantyka zaznaczonej nawigacji i SAS. Bez dekoracyjnych animacji i pobierania fontów w runtime. Muted z Master to #AAB7D2; lokalne Space Grotesk/Manrope/IBM Plex Mono zachowują dołączoną OFL i wcześniejsze przypięte pochodzenie.

## Build i wdrożenie

Wersja pozostaje4 /0.3.1-cosmic, applicationId eu.sparkhat.aioa.companion. Manifest ma51 dokładnych wejść; nowe cztery pliki produkcyjne są częścią istniejącego source seal. Żadna zmiana prezentacji nie wydaje nowego warrantu.

GitHub Actions Android to ręczny workflow wyłącznie dla main, z exact SHA, przyjętym profilem obrazu i owner ACK. Nie osłabiono go, nie uruchamiano z gałęzi ani nie scalano main. Repo jest publiczne; istniejące skany PR używają standardowych runnerów, które [GitHub dokumentuje jako bezpłatne dla publicznych repozytoriów](https://docs.github.com/en/actions/concepts/billing-and-usage). Nie zakupiono zasobów. Lista nazw repo Actions secrets była pusta; istniejący CI generował efemeryczny debug signer, co nie wystarcza do zgodnej aktualizacji.

Bez pierwotnego podpisu75a539bc1cc1cf9ca9cde7fddf32f8dc82ceaee3fd2c8831d9e32a7a14ab6404 i zakwalifikowanego pełnego toolchainu obowiązuje ANDROID_UPDATE_BLOCKED. Testy samodzielnego JVM kompilują rzeczywistą logikę, ale wygenerowane numery R służą wyłącznie unit testom; to nie kompilacja Compose, Android lint, assembleDebug ani test fizycznego Xiaomi. Nie instalowano SDK/emulatora, nie kasowano danych telefonu. Dopuszczalne kolejne opcje to odnalezienie istniejącego mechanizmu podpisu albo oddzielny pakiet testowy po decyzji właściciela; żadnej nie wykonano automatycznie.
