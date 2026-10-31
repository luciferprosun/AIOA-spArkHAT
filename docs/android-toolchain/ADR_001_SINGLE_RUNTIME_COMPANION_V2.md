# ADR-001 — jeden Companion i jedna władza AIOA

Data zadania: 2026-10-31; wykonanie obejmuje również 2026-11-01.
Status: **PROPOSED**, do przyszłego odbioru właściciela.

Problem: N1 zawiera podpisany mobile port i klienta, lecz nie ma gotowego
produkcyjnego edge ani nowego APK. Rozszerzenie telefonu o kolejny agent,
approval database lub gateway ominęłoby istniejące Core i ślady UNKNOWN.

Decyzja: utrzymać `clients/android` w pakiecie
`eu.sparkhat.aioa.companion` i jeden `MobileClient`/przyszły typed repository.
Compose/ViewModel może później przejść z `mutableStateOf` na StateFlow,
bez zmiany źródła prawdy. Transport jest wyłącznie portem do istniejącego
`runtime.webapp` → `MobileGateway` → `MissionService` → `CoreAdmission`,
`CoreWarrantLedger` i native AUDIT/OUTBOX. Nie powstaje druga baza ani owner.

Telefon składa propozycje i żądanie STOP; natywny kanał ownera na Linuksie
zatwierdza dokładne operacje. Wybór modelu nie zmienia warrantu ani budżetu.
Coding worker i commit/push/draft PR będą oddzielnie ograniczonymi zdolnościami
Core, nie mobilnym wywołaniem dowolnej powłoki czy GitHub SDK.

Rozważone warianty: kopiowanie Companion/AgentLab Gateway tworzyłoby drugi
runtime i niejasną licencję; podłączenie telefonu bez host proof ujawniałoby
enrollment niewłaściwemu hostowi; zamiana fixture na LIVE flagą ukrywałaby
brak owner binding. Odrzucono je. Reużycie istniejących portów zachowuje
historyczny kod, certyfikacje i rozdział synthetic/native.

Konsekwencje: potrzebne kwalifikowany HTTPS edge, rzeczywisty owner admission,
podpisany build i osobny test telefonu. N1 nadal blokuje Run/approve/spend/WRITE.
Nie ma obietnicy, że sam build APK rozwiąże tę integrację. Liczba testów
offline nie stanowi certyfikacji M12; aktualny licznik jest w handoff.

Akceptacja przyszłego patcha: zgodne source/protocol digests, brak drugiego
runtime/ledgera, rzeczywisty podpisany readback, odmowy forged/stale/replay,
restart→UNKNOWN bez retry, scoped STOP i jawny provider. Zmiana zdolności
wymaga osobnej zgody i testów pozytywnych/negatywnych.

Rollback tej decyzji jest dokumentacyjny; obecne zadanie nie zmienia runtime.
Rollback przyszłej migracji UI musi zachować proposal IDs, terminalne receipts,
UNKNOWN i blokady zdolności. Nie wolno resetować ledgera dla wygody demo.

Pełny projekt i mapa dowodów: [ARCHITECTURE_AIOA_COMPANION_V2.md](ARCHITECTURE_AIOA_COMPANION_V2.md).
