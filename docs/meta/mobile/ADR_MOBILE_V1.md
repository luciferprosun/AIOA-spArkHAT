# MobileMissionV1 — N1 ADR

Jedyny właściciel misji/authority to istniejący AIOA MissionService/Core. Gateway jest adapterem transportowym w tym samym WebRuntimeService, bez nowego serwera głównego, bazy misji, model routera lub approval engine. Urządzenie może proponować, czytać własny task/evidence i złożyć scoped STOP. RUN/APPROVE/spend/chat/EXEC/GitHub write/owner pairing M12 pozostają disabled/501.

Źródłem kontraktu jest `protocol/mobile_mission_v1.json`. Neutralny kod nie kopiuje niezweryfikowanego licencyjnie projektu Companion/AgentLab. Zachowuje jego uzasadnione techniczne zasady: P-256/SPKI, ES256 z DER (nie JWT raw r||s), nonce/body hash/expiry, host proof przed ujawnieniem kodu/tokenu, brak retry. Android pozostaje jednym pakietem `eu.sparkhat.aioa.companion`.

## Granice i mapowanie

| Mobile path (prefix `/api/mobile/v1`) | Existing Core/Meta port | Authority |
| --- | --- | --- |
| GET status | MissionService.evidence_many + device-owned projection | ograniczony Core READ; bez cudzych tasków/receiptów |
| GET status/pages/task_id | MissionService.evidence_many, ≤16 records / existing Core transaction | signed cursor własnej sesji; wszystkie strony dostępne; bez dowolnych query |
| POST preview | MissionService.preview | tylko propozycja, domyślnie OFFLINE_FIXTURE; bez kosztu i efektu |
| GET proposals/id | existing scoped OPERATION transport pointer → Core evidence | niezależny readback po lost ACK, bez ponowienia POST |
| GET tasks/id, evidence/id | MissionService.evidence | dokładny device/session/source/task digest/scope/capsule |
| POST stop | MissionService.stop | tylko własny task z tej sesji i źródła; UNKNOWN nie zmienia się w STOPPED |
| RUN/APPROVE | brak mobilnego portu | lokalny operator zatwierdza exact fixture Run istniejącym Mission Control/Core |

Transport enrollment/session/nonce/proposal pointer i zredagowany audit są zapisywane w istniejących scoped Core OPERATION/AUDIT records. To tożsamość transportowa, bez uprawnień owner warrant. Jednorazowy marker jest utrwalany przed proposal/STOP; utrata ACK/crash oznacza UNKNOWN/READBACK_REQUIRED. Durable nonce/session revocation przetrwają rekonstrukcję adaptera. Model i podpis telefonu nie tworzą sealed owner principal.

Każda rewizja rekordu transportowego używa natywnego `append_domain_event`,
`OperationBinding`, łańcucha AuditEvent i OUTBOX w tej samej transakcji Core.
Nie ma drugiego formatu AUDIT ani automatycznej publikacji Core JSONL; OUTBOX
pozostaje PENDING do osobnej uprawnionej publikacji. Odtworzenie z nowym kluczem
hosta odrzuca stare kody/sesje przez trwale zapisany audience. Status zwraca do16
misji, jawny `next_cursor`, `history_truncated` i liczbę własnych misji; strony są
bieżącymi odczytami scope, nie wielostronicową transakcją snapshot.

Każda sesja wiąże publiczny klucz urządzenia, audience hosta, source SHA, capsule i owner scope. Kod enrollment ma TTL≤300s, jest wydawany wyłącznie przez lokalny operator port, związany z konkretnym nowym SPKI; ponowne jawne enrollment odwołuje poprzednią sesję tego urządzenia. Nie przenosi się danych AGM ani właścicielskiego Ed25519. Klucz hosta/urządzenia P-256 w fixture jest efemeryczny i nigdy nie oznacza PHONE_PAIRED.

## TLS, dowody i fail closed

Produkcja domyślnie REMOTE_DEPLOYMENT_BLOCKED. Host musi otrzymać z zaufanej kompozycji istniejącą tożsamość i niezależne świeże potwierdzenie HTTPS/TLS1.3/exact origin; zwykły nagłówek, env lub model nie wystarcza. Nie uruchamiamy publicznego listenera ani Tailscale Serve. Hermetyczny profil fixture działa tylko na nowym loopback0, z testowymi kluczami i jawnym OFFLINE_FIXTURE; release Android odrzuca ten profil oraz HTTP.

Android sprawdza systemowe TLS/hostname, osobny cert SPKI pin i fresh signed host identity proof z independently entered host SPKI przed wysłaniem jakiegokolwiek kodu/tokenu. Host proof wiąże capabilities/source i challenge. Signed observations wiążą response digest z request nonce, metodą/ścieżką, device/session/source/capsule; nie są uprawnieniami do wykonania efektów. Brak/zmiana źródła, zły podpis, revoked/expired session, stale result, replay, błędny task/receipt i brak dowodu dają odmowę/UNKNOWN, nie fake LIVE.

FRESH ma termin na zegarze monotonicznym, ograniczony zweryfikowanym dowodem
i ważnością sesji; wygasa w foreground bez automatycznego żądania. Utrata sesji
pozwala na jawny nowy enrollment, zachowując pending/UNKNOWN. Opaque pending ID
można po potwierdzeniu użytkownika zachować w lokalnej liście nierozliczonych ID:
to wyłącznie cache UI, bez zmiany Core, owner authority, retry lub oznaczenia
zadania jako zakończonego. Token, kod, polecenie i klucze nie są w tym cache.

Ekran i lifecycle klienta zachowują STALE/OFFLINE/UNKNOWN, bez automatycznego resend POST; po process death brak odziedziczonego tokenu. Bez SDK/JDK wyłącznie SOURCE_READY/STATIC_CHECK_PASS i build-handoff. Realny telefon, TLS_HOST_VERIFIED, APK_BUILT i ANDROID_E2E_VERIFIED wymagają osobnych rzeczywistych dowodów. Model Meta i publiczny Chrome pozostają poza autoryzacją sprintu.
