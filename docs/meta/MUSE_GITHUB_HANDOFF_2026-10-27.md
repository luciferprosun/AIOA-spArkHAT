# AIOA METAGuardiansSPARK — current branch notice (31 October 2026)

Current canonical branch: `AIOA-METAGuardiansSPARK`. This 27 October handoff is historical; references to the legacy `meta` branch below remain untouched for provenance.

---

# AIOA spArkHAT META — handoff GitHub → Muse Code, 27 października 2026

STATUS: PREPARED_ONLY. To jest dokumentacja przygotowana przez ChatGPT w GitHubie, NIE implementacja ani raport wykonania Muse.

Kod znajduje się wyłącznie na branchu meta repozytorium luciferprosun/AIOA-spArkHAT. Przed zapisaniem tej dokumentacji potwierdzony kodowy commit to b6df01ded1cc68b860913d4760abeabb48fa2c6b (P2-01, 113/113 testów OFFLINE PASS). Późniejszy dokumentacyjny commit zmieni HEAD meta, więc przed uruchomieniem Muse trzeba przypiąć aktualne sprawdzone SHA.

## Co rzeczywiście osiągnęliśmy

- P0: Muse przygotował podział na siedem faz i 21 promptów; dokumentacja przeszła QA.
- P1-01 — P1-04: kontrakty, izolowany adapter fixture, STOP/timeout i testy wektorów sieciowych, wszystko OFFLINE; P1-04 QA PASS na SHA 22ca2e7869d903287ab5a53f831b6892b3db24dd.
- P2-01: offline provider-compatibility; obie metody generate oraz generate_exact są zablokowane w fixture. Kod nie potwierdza prawdziwego połączenia Meta API w aplikacji.
- P2-02: brak zatwierdzonego wyniku na GitHubie. Status lokalnej kopii Linux UNKNOWN: mogły zostać uncommitted pliki z nocnej sesji. Nie ponawiać na ślepo, nie nadpisywać.
- P1-05 Chromium LIVE, P2-03 Meta Model API LIVE, P5-03 Android E2E LIVE: BLOCKED do oddzielnych bramek i zgody właściciela.

## Nieprzekraczalne granice

Muse Code sam pisze i poprawia implementację oraz testy. ChatGPT przygotowuje instrukcje, audytuje, wykonuje niezależne testy, zatwierdza commity i archiwizuje raporty. Właściciel zatwierdza koszty, dostęp do prywatnych danych, wyjście do sieci i efekty. Brak zgody na zmianę main, gałęzi Nebius/Codex/Gmail, ich procesów lub checkoutów. Raporty pracy trzymamy w prywatnym luciferprosun/RaportyMUSE; bez kluczy i surowych transkryptów.

Przy niedostępnym Linuxie GitHub przechowuje dokumentację i kod. NIE wykonuje Muse Code automatycznie. Klucz do Meta API pozostał na Linuxie, nie należy go umieszczać w GitHub Actions czy repo, aby obejść niedostępność komputera.

## Recovery-first — kolejność po powrocie do PC

1. Przywrócić Desktop Commander Remote, sprawdzić ONLINE. Pracować tylko w osobnym katalogu $HOME/projects/AIOA-spArkHAT-META; NIE wykonywać żadnej komendy w aktywnym checkoutcie Codexa ani Nebiusa.
2. READ-ONLY: sprawdzić git branch --show-current, git status --porcelain --untracked-files=all, git rev-parse HEAD, git remote get-url origin i procesy Muse. Porównać lokalne SHA z aktualnym GitHub meta; nie zakładać, że stary pin b6df01d jest nadal HEAD.
3. Jeśli lokalny P2-02 ma zmiany niezatwierdzone, NIE wykonywać pull/reset/checkout. Najpierw zachować raporty i odczytać pliki tylko w dozwolonym zakresie. Zweryfikować testy offline, wykonać QA i dopiero po PASS zatwierdzić kod do meta. Przy FAIL wysłać Muse ograniczony prompt naprawczy, a wcześniejszy FAIL zachować w prywatnym repo.
4. Jeśli checkout jest CZYSTY i P2-02 nie istnieje, porównać GitHub meta z lokalnym SHA, sprawdzić dokumentacyjne różnice i dopiero wtedy synchronizować fast-forward WYŁĄCZNIE ten checkout. Zaktualizować pinned SHA launchera Muse do nowego faktycznie sprawdzonego HEAD.
5. Nie resetować ani nie podnosić limitów dawnych zadań overnight-limits.json lub meta-followup-20261027.json. Jeden proces Muse na raz; max kroki i czas, approval/sandbox włączone, bez subagentów i --yolo.
6. Kolejność dalszej implementacji: P2-02 OFFLINE mock receipts → QA PASS → P3-01 OFFLINE correlation/provenance. Nie uznawać G4 end-to-end za DONE bez LIVE G2 i G3.

## Kontrola offline przed QA

Przykładowe komendy przeznaczone WYŁĄCZNIE dla hosta Linux po wznowieniu bezpiecznego połączenia:

    repo="$HOME/projects/AIOA-spArkHAT-META"
    git -C "$repo" branch --show-current
    git -C "$repo" status --porcelain --untracked-files=all
    git -C "$repo" rev-parse HEAD
    git -C "$repo" remote get-url origin
    cd "$repo" && PYTHONDONTWRITEBYTECODE=1 python3 -B -m unittest discover -s tests -p 'test_meta_*.py' -q

Potrzebne wyniki: rzeczywiste pliki, diff, testy, source_sha, PASS/FAIL, raport i brak tajnych danych. Nie kopiować prywatnych logów Muse na publiczny branch.

## Bezpieczne decyzje właściciela

- Osobna zgoda na publiczną domenę testową i izolację sieciową OS przed Chromium LIVE.
- Osobna zgoda na model, minimalny koszt pojedynczego REAL Meta API probe i weryfikacja stanu Billing. Osobiste 20 EUR nie oznacza zgody na nieograniczone wywołania.
- Osobna zgoda na końcową demonstrację zewnętrzną i wysłanie projektu.
- Gmail draft-only pozostaje opcjonalny; SEND i OAuth nie są celem MVP.

DONE dla tego dokumentu = instrukcje przygotowane w GitHub, bez zmiany source/runtime. Dopiero Muse Code ma wykonać kod po powrocie do PC.
