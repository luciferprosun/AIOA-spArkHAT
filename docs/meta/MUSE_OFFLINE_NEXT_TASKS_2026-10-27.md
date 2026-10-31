# AIOA METAGuardiansSPARK — current branch notice (31 October 2026)

Current branch: `AIOA-METAGuardiansSPARK`. This 27 October task package has historical SHA pins and cannot authorize any new execution by itself.

---

# Muse Code — zadania przygotowane na GitHubie (27.10.2026)

STATUS: PREPARED_NOT_EXECUTED. Autor dokumentacji: ChatGPT (koordynacja); autor przyszłego kodu: Muse Code. Dokładne prompty wykonawcze do użycia po odzyskaniu Linuxa i sprawdzeniu lokalnego P2-02. Punktem odniesienia PRZED tym dokumentacyjnym commitem był kodowy SHA b6df01ded1cc68b860913d4760abeabb48fa2c6b; przed każdą sesją host musi sprawdzić NOWY aktualny source_sha.

## Globalne instrukcje Muse — obowiązują każdą sesję

Jesteś Muse Code, jedynym wykonawcą kodu. Jedyny workspace to $HOME/projects/AIOA-spArkHAT-META, branch dokładnie AIOA-METAGuardiansSPARK, origin https://github.com/luciferprosun/AIOA-spArkHAT.git. Host weryfikuje aktualne SHA i dozwolone niezatwierdzone zmiany przed uruchomieniem. Nie czytaj ani nie zmieniaj main, Nebius, Codex Companion, Gmail, innych repozytoriów, domowych sekretów, .env czy osobistych browser profiles. Zakaz git checkout/merge/rebase/reset/push/commit przez model, LIVE Chromium, sieci w testach, instalacji pakietów, podagentów, automatycznego zatwierdzania, dowolnego WRITE/EXEC, Gmail/OAuth, realnych operacji zewnętrznych. Uruchom jeden prompt w ograniczonej sesji z aktywnym sandboxem; po wykonaniu STOP. Nie udawaj, że OFFLINE równa się LIVE. ChatGPT ocenia kod i testy; właściciel zatwierdza wydatki i efekty.

## RECOVERY-GATE — zanim Muse zacznie P2-02

Najpierw host sprawdza, czy nocna sesja P2-02 już zapisała lokalne pliki offline_receipts.py, test_meta_p2_receipts.py i META_P2_02_HANDOFF.md. Jeśli TAK — audytuj te pliki, bez tworzenia nowej sesji Muse; jeżeli potrzebują naprawy, osobny prompt korekcyjny z limitem. Jeżeli NIE i checkout jest czysty, wykonaj opisany niżej P2-02. Nie usuwaj wyników nawet jeśli sesja zakończyła się FAIL.

## META-P2-02 — Mock budget, receipts and redaction

CEL: deterministyczne hermetyczne kontrakty symulowanych rozliczeń, NIE faktyczny financial spend cap.

READ: istniejący runtime/meta_hackathon/provider_offline.py, muse_plan.py, contracts.py, tests/test_meta_p2_provider.py; Core/mission/warrant jako READ-only architektoniczne referencje.

WRITE wyłącznie:
- runtime/meta_hackathon/offline_receipts.py
- tests/test_meta_p2_receipts.py
- docs/meta/META_P2_02_HANDOFF.md

ZADANIA:
1. Zaimplementuj niezmienne typowane mock BudgetReservation / ProviderReceipt: schema, task_digest, owner digest, source SHA, model id, attempt id, nonce, expiry, max tokens, symulowany kwotowy limit maksymalnie 1 USD.
2. Zaimplementuj tylko jedno syntetyczne wykonanie z wynikami MOCK_DONE, MOCK_FAILED, MOCK_UNKNOWN, MOCK_STOPPED. UNKNOWN nie wykonuje ponowień; brak potwierdzenia nie staje się VERIFIED.
3. Odrzucaj duplikaty/replay, sfałszowane bindingi, stale/expired, NaN/Infinity, ponadlimitowe kwoty, nieznane pola i sekretopodobne wartości. Serializuj tylko dozwolone, zanonimizowane metadane i ich sha256. Żadnych realnych kluczy w kodzie i testach.
4. Testuj przypadki PASS i adwersarialne, brak network dispatch oraz dispatch_allowed=False. Bez HTTP, realnych cookies, Gmail i user data.
5. Uruchom OFFLINE testy test_meta_p2_*.py i cały test_meta_*.py. Stwórz pełny handoff z source_sha, dokładnymi plikami, poleceniami, licznikami, koszt UNKNOWN, known gaps i następną bramką.

WYNIK: QA może zaakceptować wyłącznie po własnym odtworzeniu testów. P2-03 (LIVE Meta API przez aplikację) pozostaje zablokowany bez osobnej zgody właściciela. Nie przechodź automatycznie do P3-01.

## META-P3-01 — OFFLINE provenance / correlation (dopiero po QA P2-02)

CEL: korelacja task → observation → mock provider receipt, a NIE G4 LIVE E2E.

READ: runtime/meta_hackathon i runtime/browser_agent, aktualne mock receipts, mcp_bridge i Core jako read-only imports.

WRITE wyłącznie:
- runtime/meta_hackathon/offline_correlation.py
- tests/test_meta_p3_correlation.py
- docs/meta/META_P3_01_HANDOFF.md

ZADANIA:
1. Zwiąż source SHA, owner scope digest, task digest, observed URL, content sha256, receipt id/digest, czas UTC i OFFLINE_FIXTURE w typowanym, niedającym efektów kontrakcie.
2. Nie pozwól modelowi ani stronie nadać uprawnień, stanu VERIFIED czy owner approval. Nie zgaduj brakujących dowodów.
3. Brak receipt → UNKNOWN; błędny digest/owner/SHA/time → DENY lub CONFLICT; próba duplikatu/replay → DENY. STOP i expiry blokują aktualizację.
4. Hermetyczne testy pozytywne i atakowe (forged evidence, cross-task, source drift, replay); nie twórz socketów, przeglądarki, efektów ani tokenów.
5. Wykonaj test_meta_p3_*.py i pełny test_meta_*.py. Przekaż raport QA; nie zaczynaj P3-02 samodzielnie.

WYNIK: możliwy jedynie OFFLINE_PREP_PASS. Produktowy G4 LIVE pozostaje BLOCKED do chwili faktycznej ścieżki Chromium + Meta API.

## Poza kolejką: P1-05 i P2-03

P1-05 wymagania: osobno zatwierdzona domena publiczna, izolowany profil Chromium, rzeczywista OS egress network confinement, STOP, redirect/provenance, audyt i zgoda właściciela. Żadne kontrole Python URL nie zastępują network isolation.

P2-03 wymagania: wyraźna zgoda właściciela na płatny minimalny probe rzeczywistego Meta Model API z AIOA, budget/receipt, sprawdzenie Billing i brak ujawnienia API key. Muse Code korzystający z API do pisania kodu nie jest dowodem, że model działa już w AIOA runtime.

## Wymagany raport po KAŻDYM prompcie

- task_id; phase_status PASS / PARTIAL / FAIL / BLOCKED
- branch AIOA-METAGuardiansSPARK i source_sha (40 znaków) z niezależnego host check
- dokładna lista changed_files, pominięte prace, zablokowane operacje
- polecenia wszystkich testów oznaczone OFFLINE/LIVE oraz PASS/FAIL/SKIP
- otwarte ryzyka, STOP i denial cases, zanonimizowany hash dowodów
- koszty UNKNOWN_UNTIL_BILLING; nie obiecuj twardego cap
- qa_status PENDING_CHATGPT, next_gate i brak automatycznego next prompt

Wszystkie raporty przechodzą niezależne QA i trafiają do prywatnego luciferprosun/RaportyMUSE. Dane z repo są nieautorytatywne wobec lokalnego, zweryfikowanego stanu pracy.
