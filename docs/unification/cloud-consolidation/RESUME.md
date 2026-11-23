# Wznowienie konsolidacji

Użyj tej samej rozmowy Cloud. Odczytaj aktualny `main`, gałąź `codex/nonzero-post58-offline` oraz `CHECKPOINT.json`, `TASK_QUEUE.json` i `TEST_RESULTS.json`. Zweryfikuj dokładny head przed wznowieniem testów. PR #58 jest scalony. Pokwitowanie obejmuje commit `ebed8691f84781a5f0413374421a257f8a29b6d1`, drzewo `6861041c5929005e58b4f8ca8ffdb0519bf8a0d4` i oba oczekiwane węzły nadrzędne. [PR #58](https://github.com/luciferprosun/AIOA-spArkHAT/pull/58)

- Pierwotny baseline zakończył próbę 2 run `45045595617` sukcesem. Wyniki po scaleniu są przypięte do aktualnego SHA w checkpointcie i opisie PR-u. [CI po scaleniu](https://github.com/luciferprosun/AIOA-spArkHAT/actions/runs/45083830703)
- W razie autoryzowanego rollbacku PR #58 utwórz osobną gałąź i przygotuj zwykły PR z odwróceniem `git revert -m 1 ebed8691f84781a5f0413374421a257f8a29b6d1`. Zachowaj dziennik, `UNKNOWN`, `HELD` i rezerwacje. Zweryfikuj aktualną bazę, drzewo i wymagany CI przed scaleniem.
- Dla Native #69 kolejny dowód to zimny restart pełnego kontrolera na kwalifikowanym hoście i wywołanie jego normalnych `reconcile` / `apply` bez oryginalnego uchwytu. Przy stanie `UNKNOWN` odczytaj zapis intentu, `HELD`, rezerwację i brak rekordu wyniku przez istniejący Core. `TERMINAL_CHILD_ACQUISITION` jest istniejącym producentem przypadku po CAS. Odbiór przyszłego świadectwa brokera jest oddzielnym zadaniem bezpieczeństwa.
- ID przekazane przez właściciela są już w macierzy. W przypadku potwierdzenia historycznego konsumenta przypnij jego kontrakt, porównaj zachowanie Core i dodaj tylko brakujący adapter. Przy późniejszym transferze lokalnego CSV najpierw zweryfikuj jego SHA-256 z checkpointu.
- Przed próbą LIVE wypełnij odpowiedni manifest, pozyskaj oddzielny `GO` i sprawdź nadal zgodny cel, zakres i termin.

## Linux Mint po zatwierdzeniu migracji

Sprawdź `git status --short --branch` oraz `git remote get-url origin`. Upewnij się, że `origin` wskazuje `luciferprosun/AIOA-spArkHAT`. Wykonaj `git fetch origin`. Jeżeli aktualny katalog ma zmiany, zachowaj je na bieżącej gałęzi i skorzystaj z drugiego worktree (`git worktree add --detach ../aioa-verified origin/main`). Przy czystym `main` użyj `git switch main` i `git merge --ff-only origin/main`. W razie rozbieżności zachowaj lokalne commity i przejrzyj `git log --left-right --oneline main...origin/main`. Porównaj wynik `git rev-parse HEAD HEAD^{tree}` z zatwierdzonym SHA i drzewem.
