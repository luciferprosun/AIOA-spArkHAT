# Wznowienie konsolidacji

Użyj tej samej rozmowy Cloud. Odczytaj aktualny `main`, gałąź `codex/nonzero-cloud-consolidation-20261122`, Draft PR (jeżeli istnieje) oraz `CHECKPOINT.json`, `TASK_QUEUE.json` i `TEST_RESULTS.json`. Zweryfikuj dokładny head przed wznowieniem testów. Kontynuuj od pierwszej gotowej pozycji bez ponawiania PR #52–57 i próby 2 CI.

- Baseline zakończył próbę 2 run `45045595617` sukcesem. Zweryfikuj stan na nowym headzie PR-u. Brak upoważnienia na kolejne ponowienie tego runu.
- Dla Native #69 kolejny dowód to zimny restart pełnego kontrolera na kwalifikowanym hoście i wywołanie jego normalnych `reconcile` / `apply` bez oryginalnego uchwytu. Przy stanie `UNKNOWN` odczytaj zapis intentu, `HELD`, rezerwację i brak rekordu wyniku przez istniejący Core. `TERMINAL_CHILD_ACQUISITION` jest istniejącym producentem przypadku po CAS. Odbiór przyszłego świadectwa brokera jest oddzielnym zadaniem bezpieczeństwa.
- W przypadku potwierdzenia historycznego konsumenta przypnij jego kontrakt, porównaj zachowanie Core i dodaj tylko brakujący adapter. W razie odzyskania poprzedniej macierzy porównaj ID z bieżącą klasyfikacją i zapisz różnice.
- Przed próbą LIVE wypełnij odpowiedni manifest, pozyskaj oddzielny `GO` i sprawdź nadal zgodny cel, zakres i termin.

## Linux Mint po zatwierdzeniu migracji

Sprawdź `git status --short --branch` oraz `git remote get-url origin`. Upewnij się, że `origin` wskazuje `luciferprosun/AIOA-spArkHAT`. Wykonaj `git fetch origin`. Jeżeli aktualny katalog ma zmiany, zachowaj je na bieżącej gałęzi i skorzystaj z drugiego worktree (`git worktree add --detach ../aioa-verified origin/main`). Przy czystym `main` użyj `git switch main` i `git merge --ff-only origin/main`. W razie rozbieżności zachowaj lokalne commity i przejrzyj `git log --left-right --oneline main...origin/main`. Porównaj wynik `git rev-parse HEAD HEAD^{tree}` z zatwierdzonym SHA i drzewem.
