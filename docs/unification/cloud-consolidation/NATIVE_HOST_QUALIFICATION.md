# Kwalifikacja hosta Native #69

**Stan hosta Cloud: BLOCKED_HOST.** Odczyt 23 listopada 2026 r. w kontenerze Debian 13.7 x86_64 wykazał cgroup v2 tylko do odczytu, PID 1 `tail`, niedostępny systemd użytkownika i brak dedykowanej grupy użytkownika. `unshare --user --map-root-user --net true` odmówił zapisu mapy UID, a próba minimalnego bubblewrap z osobną siecią otrzymała `Operation not permitted`. Dostępny Chromium oraz wersje Git, bubblewrap i libc różnią się od przypiętego profilu. Podstawowe fixture i odczyty offline działają w Cloud. Pełnego ponownego uruchomienia kontrolera ani G04 nie kwalifikowano.

## Dane wejściowe do kwalifikacji

| Pole | Kryterium |
| --- | --- |
| Host | Jednorazowa maszyna x86_64 z przypiętym obrazem Ubuntu 24.04 Noble i jądrem, potwierdzoną tożsamością uruchomienia, UID/GID, AppArmor, cgroup v2 oraz delegowaną usługą systemd użytkownika |
| Zależności | Wersje, Git i skróty binariów oraz bibliotek zgodne z profilem `nonzero-pr.yml` i snapshotem APT 20261027; digest zamkniętego runtime z `snapshot_python_runtime` |
| Sieć | Kwalifikacja pakietów przed próbą. Faza testu w izolowanej przestrzeni sieciowej, bez egress, z dowodem wyłączenia. Środowisko bez tokenów, produkcyjnych kluczy i lokalnych danych właściciela |
| Procesy | Potwierdzone różne PID i instancje admission producenta i konsumenta, wyłączna grupa cgroup, możliwość zatrzymania i sprzątania potomków |
| Stan | Świeży scratch 0700, odizolowany journal i ledger, brak współdzielonych refów, repo testowe i snapshot źródeł przypięte SHA oraz tree |
| Dodatkowe G04 | Przypięty keeper i jego tożsamość, Google Chrome i skróty zamkniętych zależności, filtr i profil sandbox, przypięta recepta, obserwacje DOM, konsoli i PNG. Chrome dotyczy G04 |
| Pokwitowanie | Prywatne miejsce dowodów, limit rozmiaru, skróty logów, przypięty ref, oczekiwany OID, identyfikatory intentu, warrantu, rezerwacji, HELD i wyniku |

## Odbiór po uruchomieniu dwóch procesów

Przygotować nadzorcę dla `tests/nz12_ci_host.sh` i `tests/nz12_source_runner.py`. Wcześniejszy hosted certify wykazał działanie podstawowych bramek Native Git na runnerze Noble. Dedykowana sekwencja dwóch procesów wymaga pełnego wejścia opisanego niżej.

1. Zbudować manifest runtime przez `snapshot_python_runtime(..., include_git=True)`, ustawić ograniczone odczyty bez podążania za linkiem i wyłączny trwały zapis w prywatnym katalogu.
2. W procesie producenta użyć etapu `TERMINAL_CHILD_ACQUISITION_PRODUCE` i `NativeOwnedAcceptance.test_produce_terminal_child_acquisition_history_for_new_process`. Po zakończeniu procesu zachować i sprawdzić SHA-256 handoffu `nz13.native-owned-restart-handoff.v1` i obrazu stanu przed restartem.
3. Uruchomić drugi proces przez `NativeRestartFixture`, otworzyć utrwalony stan z nową instancją admission, wykonać `test_populated_restart_reads_declared_linux_and_git_history` i rozszerzyć odbiór o normalne `reconcile` i `apply`. Potwierdzić `UNKNOWN`, aktywną rezerwację, niezmienione `HELD` i brak ponownego wywołania CAS lub modelu.
4. Powtórzyć kontrolowane warianty utraty ACK, braku refu, obcego zgodnego refu, driftu, STOP, wygaśnięcia warrantu i współbieżnego odczytu. Sprawdzić podpisy istniejących dowodów i brak artefaktu, który mógłby poświadczyć błędnego wykonawcę.

Dla przyszłego świadectwa należy związać pierwotnego brokera, klucz powiązany z jego zarejestrowaną tożsamością, intent, warrant, rezerwację, tożsamość repozytorium, ref, poprzedni i docelowy OID oraz potwierdzony trwały skutek. Awaria między CAS a utrwaleniem świadectwa zachowuje UNKNOWN. Żaden wynik kwalifikacji nie uzupełnia historycznego dowodu dla #69. [Bramki bezpieczeństwa](SECURITY_GATES.md)
