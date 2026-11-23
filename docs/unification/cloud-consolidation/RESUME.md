# Wznowienie konsolidacji

Użyj tej samej rozmowy Cloud. Odczytaj aktualny `main`, gałąź `codex/nonzero-post59-evidence` oraz `CHECKPOINT.json`, `TASK_QUEUE.json` i `TEST_RESULTS.json`. PR-y #58 i #59 są scalone. Punktem odniesienia po #59 jest commit `914c9b1bf4dc7bf6ff14687d91560d9bcef1a5f6` i drzewo `f4238a014e210e46863a4f6e7abadc40bf71fa61`. Dalsze poprawki i izolowane fixture są opisane w [POST59_OFFLINE](POST59_OFFLINE.md). [CI po scaleniu #59](https://github.com/luciferprosun/AIOA-spArkHAT/actions/runs/45107463038)

- Pierwotny baseline zakończył próbę 2 run `45045595617` sukcesem. Wyniki po scaleniu są przypięte do aktualnego SHA w checkpointcie i opisie PR-u. [CI po scaleniu](https://github.com/luciferprosun/AIOA-spArkHAT/actions/runs/45083830703)
- W razie autoryzowanego rollbacku PR #59 utwórz osobną gałąź i przygotuj zwykły PR z odwróceniem `git revert -m 1 914c9b1bf4dc7bf6ff14687d91560d9bcef1a5f6`. Zachowaj dziennik, `UNKNOWN`, `HELD` i rezerwacje. Zweryfikuj aktualną bazę, drzewo i wymagany CI przed scaleniem.
- Dla Native #69 kolejny dowód to zimny restart pełnego kontrolera na kwalifikowanym hoście i wywołanie jego normalnych `reconcile` / `apply` bez oryginalnego uchwytu. Przy stanie `UNKNOWN` odczytaj zapis intentu, `HELD`, rezerwację i brak rekordu wyniku przez istniejący Core. `TERMINAL_CHILD_ACQUISITION` jest istniejącym producentem przypadku po CAS. Odbiór przyszłego świadectwa brokera jest oddzielnym zadaniem bezpieczeństwa.
- ID przekazane przez właściciela są już w macierzy. W przypadku potwierdzenia historycznego konsumenta przypnij jego kontrakt, porównaj zachowanie Core i dodaj tylko brakujący adapter. Przy późniejszym transferze lokalnego CSV najpierw zweryfikuj jego SHA-256 z checkpointu.
- Przed próbą LIVE wypełnij odpowiedni manifest, pozyskaj oddzielny `GO` i sprawdź nadal zgodny cel, zakres i termin.

## Linux Mint po zatwierdzeniu migracji

Sprawdź `git status --short --branch` oraz `git remote get-url origin`. Upewnij się, że `origin` wskazuje `luciferprosun/AIOA-spArkHAT`. Wykonaj `git fetch origin`. Jeżeli aktualny katalog ma zmiany, zachowaj je na bieżącej gałęzi i skorzystaj z drugiego worktree (`git worktree add --detach ../aioa-verified origin/main`). Przy czystym `main` użyj `git switch main` i `git merge --ff-only origin/main`. W razie rozbieżności zachowaj lokalne commity i przejrzyj `git log --left-right --oneline main...origin/main`. Porównaj wynik `git rev-parse HEAD HEAD^{tree}` z zatwierdzonym SHA i drzewem.
