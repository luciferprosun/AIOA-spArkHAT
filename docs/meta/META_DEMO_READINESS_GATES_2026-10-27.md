# AIOA METAGuardiansSPARK — branch migration update, 31 October 2026

Current canonical branch: `AIOA-METAGuardiansSPARK`. OFFLINE/LIVE evidence statements remain unchanged.

---

# AIOA METAGuardiansSPARK — status dowodów demo, 27.10.2026

STATUS: audyt dokumentacyjny GitHub-only wykonany przez ChatGPT. Brak nowego kodu, brak kontaktu z Linuxem, brak wywołań Muse w tej operacji.

## Minimalne działające demo — krytyczna ścieżka

Android zleca publiczny READ → Muse model proponuje plan → AIOA Core sprawdza właściciela, scope, STOP i możliwości → izolowany Chromium odczytuje wyłącznie allowlisted public docs → obserwacja i receipt z provenance wracają do Androida → operator widzi status i STOP.

Ta sekwencja to CEL, nie obecny stan.

## Macierz bramek

| Gate | Potwierdzony dowód | Czego brak |
| --- | --- | --- |
| G0/G1 | 7 faz / 21 promptów; kontrakty offline QA | — |
| G2 | P1-01…P1-04 QA, multicast fix, 99 testów offline | Chromium LIVE, OS/process egress, profile isolation, redirect chain, owner URL GO |
| G3 | Muse Code kodował; provider_offline.py QA, 113 testów offline | realne wywołanie modelu przez runtime AIOA, rzeczywisty provider receipt, potwierdzony Billing |
| G4 | szczegółowy prompt P3-01 przygotowany | pełna korelacja/obserwacja LIVE |
| G5 | istniejące Core/warrant jako referencja | test owner approval w rzeczywistym przepływie bez WRITE |
| G6 | plan operatora Android | prawdziwe status + STOP + evidence E2E |
| G7 | opcjonalny Gmail draft-only | SKIP dopuszczalny |
| G8/G9 | plan na 2–3 min demo i finalne zgłoszenie | nagranie, dowody, jawne zatwierdzenie uploadu |

## Zasady dowodowe

1. Każdy wynik LIVE musi zawierać rzeczywistą datę UTC, source_sha, model id, task_digest, observed URL, receipt digest, środowisko i niezależny readback.
2. Adnotacja OFFLINE_FIXTURE, symulowany budżet i testy unittest nie są dowodem prawdziwej przeglądarki, live Meta API, actual cost ani autoryzacji.
3. Osobno trzeba przetestować STOP, timeout, cross-origin redirects, multicast/localhost/metadata IP, source drift, forged owner, prompt injection, niezgodny screenshot i replay.
4. Brak dowodów musi pozostać UNKNOWN, nigdy VERIFIED/DONE.
5. Nie wrzucać do publicznego repo kluczy, cookies, surowych logów, prywatnych zrzutów, tokenów ani pełnych historii modeli.
6. Realny właścicielski GO na domenę i koszt/efekt potrzebny przed live; limit osobistych 20 EUR nie jest wymuszonym billing cap.
7. Ostateczny deadline 4 listopada 21:00 ET pochodzi z dotychczasowej roadmapy i musi zostać ponownie sprawdzony u organizatora przed submission.

## Decyzja zakresu

Priorytet to mały, działający pionowy przepływ z rzeczywistym Muse + Chromium + AIOA + STOP, nie liczba modułów. Gmail/OAuth/automatyczny SEND oraz ogólny desktop EXEC są poza MVP. Jeśli brakuje LIVE gate, publikować tylko uczciwie opisane offline evidence, bez nazwania go działającym browser agentem.

Autorzy: Muse Code pisze kod; ChatGPT QA, dokumentację i sprawdza testy. Ten plik nie jest artefaktem kodowania Muse i nie oznacza zatwierdzonej fazy.
