# NV-01 — decyzje G1

## D01 — jeden composition root

Status: ACCEPTED_FOR_G1. Rozszerzyć AgentRuntime o jawną konstrukcję inspection-only i kontekst diagnostyczny misji. Factory omija inicjalizację dostawców, magazynów i wykonawcy w tym trybie. Żaden drugi runtime/service/daemon produktu. Legacy bez opt-in pozostaje bez zmian.

## D02 — jeden właściciel scheduler/LITE

Status: ACCEPTED_FOR_G1. SchedulerPort to deklarowany, Core-owned port. W LITE właścicielem jest AgentRuntime. G1 nie uruchamia harmonogramu. Istniejący circadian_router jest funkcją polityki pory dnia, nie gotowym DVM schedulerem. Rozszerzone adaptive scheduling: PROVISIONAL do pomiarów G2/G3.

## D03 — MemoryPatch Core-native

Status: ACCEPTED_FOR_G1. Używać CoreMemoryPatchDependencies, istniejącego OwnerScope, transakcji, evidence i provenance. Nigdy MemoryV2, zastępczej bazy SQLite produktu, portu wybranego z JSON ani implicit owner. Brak backendu w doktorze = UNAVAILABLE. Historyczny PASS migracji nie jest świeżym live probe.

## D04 — osobny kontrakt NVIDIA

Status: ACCEPTED_FOR_G1. NV-00 nvbuild pozostaje opcjonalnym narzędziem Codexa. Exact CPL nadal wymaga OpenRouter. Produktowy adapter NVIDIA, BudgetGate i osobno dopuszczony live request należą do G2; pełne połączenie silników do G3. Są niedostępne w G1. Nie wykonywać inference w tej fazie i nie raportować starego NV_OK jako nowego wyniku.

## D05 — autonomy nieaktywne

Status: ACCEPTED_FOR_G1. Domyślnie nvidia-lite disabled, CONTROLLED i effects=false. AUTO_SCOPED kończy się POLICY_BLOCKED/NOT_IMPLEMENTED. Manifest, model, pamięć i feromony nie tworzą zgody. Istniejące zasady NonZero/PLAN_AND_CONFIRM pozostają nienaruszone. Przyszła automatyzacja wymaga osobnej decyzji operatora.

## D06 — evidence, delty i feromony

Status: ACCEPTED_FOR_G1 dla kształtu i negatywnych testów; scoring/retencja/produkcyjny event store: PROVISIONAL. Reuse CorrectionCandidate i ModelExperienceEvent. Nowe DTO tylko dla brakującego trail/snapshot i powiązań. Deterministyczne NO_CHANGE dla kanonicznie identycznych claims, bez deklaracji ogólnej semantyki. VERIFIED_REUSE wymaga zaufanej weryfikacji dowodów w tym samym scope; modelowy event nie jest takim dowodem. ERROR_RECURRED dotyczy potrzeby ponownego sprawdzenia, a nie prawdziwości. FAILED_REUSE obniża zaufanie do śladu; CONFLICT/REVOKED nie można ożywić wysoką salience. Tau+ i tau− nie są authority.

## D07 — przyszłe intencje i commit

Status: PROVISIONAL. Przyszła ścieżka wykonawcza musi wiązać intent, expected revision/CAS, scope, policy digest i receipt. UNKNOWN przy niejednoznacznym skutku wymaga uzgodnienia z rzeczywistym targetem, nigdy blind retry. G1 nie dodaje intent store ani wykonania; korzysta z istniejącego precedensu MemoryPatch CommitOutcomeUnknown.

## Granica mailbridge

Zewnętrzny kontroler poczty nie jest schedulerem AIOA. Jego auth/policy/lease/queue/outbox są poza worktree i poza uprawnieniami workera. Dostęp narzędzia Gmail w bieżącej sesji ani wynik tekstowy modelu nie dowodzą bezpiecznego uwierzytelnienia polecenia. Arming wymaga oddzielnych dowodów; w przeciwnym razie NOT_ARMED.
