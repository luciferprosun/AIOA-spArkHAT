# Dowody po przekazaniu audytu Linux

Commit `fd941800cd96517b466cfde9398a7972f55c01a4` i `tests/test_nz29_native_attribution_boundary.py` nie są dostępne w obecnych refach GitHub ani w pełnym klonie Cloud. Porównanie opiera się na scenariuszach z przekazania. Linuksowy checkout z odłączonym HEAD na `7b5fd205` jest wyłącznie punktem odniesienia. `LINUX_SYNC_HANDOFF.md` należy sporządzić po odbiorze GitHub i ustaleniu końcowego `main`.

| Scenariusz | Istniejące pokrycie i uzupełnienie |
| --- | --- |
| Utrata ACK i wyłącznie oryginalny uchwyt | `nz13_native_coding_acceptance.NativeOwnedAcceptance.test_git_lost_physical_ack_reconciles_exact_owned_history_without_resend` na `main`. Restart po fizycznym CAS przy istniejącym rekordzie jest w `test_populated_restart_reads_declared_linux_and_git_history`. Nowy test `test_public_native_reconcile_requires_original_lifecycle_before_git` sprawdza odmowę kontrolera Native w nowym cyklu życia przed odczytem Git. |
| Zgodny ref, obcy wykonawca, zmiana lub brak refu | `test_nz25_intent_cold_read.ColdIntentReadTests.test_cold_git_intent_has_no_replay_or_writer_proof_from_ref` na wcześniejszym headzie PR #58. Sprawdza prywatne repozytorium Git i cztery przypadki przerwania. |
| Współbieżny odczyt | `nz13_native_coding_acceptance.NativeOwnedAcceptance.test_git_reconciliation_scope_ownership_denials_and_lost_verified_ack` sprawdza odmowę drugiego uzgodnienia przy aktywnym dziecku. Teraz `test_cold_git_intent_has_no_replay_or_writer_proof_from_ref` uruchamia też dwa procesy odczytu po CAS. Oba utrzymują odmowę i nietknięty stan. Scenariusz pełnego Native wymaga kwalifikowanego hosta. |
| UNKNOWN, rezerwacja, HELD, blokada replay | `test_nz25_intent_cold_read.ColdIntentReadTests.test_restart_without_verifier_keeps_held_intent_read_only` jest na `main`. Gitowy przypadek na PR #58 sprawdza również stan zapisany przed i po odczycie. |
| Brak uprawnień do rozpoczęcia nowej pracy | `test_nz11_review_controller.ReviewControllerTests.test_unresolved_core_intent_blocks_admission_without_an_unknown_task` obejmuje ogólny intent na `main`. Nowy scenariusz PR-u uruchamia publiczne `start` po zimnym otwarciu dziennika Git CAS i sprawdza `QUEUED`, odmowę i zero wejść do fabryki workera. `test_nz13_coding_backend_binding` obejmuje osobną odmowę uruchomienia niegotowego modelu. |

## Kwalifikacja offline A–D

- **A.** Walidator Native READ odrzuca sztucznie dołączoną tożsamość MCP, flagę LIVE i przypisanie uprawnień READ dowodowi. Transport oficjalnego klienta nadal wymaga odbioru.
- **B.** `CodexWorker` wydaje jawne `NOT_CERTIFIED` bez kandydata i uprawnień. Testy wiązania polityki Core oraz G07 sprawdzają granice budżetów na fixture.
- **C.** Preflight zapisu stosuje tę samą regułę braku workflow co publiczny odczyt bazy i odmawia przed POST. Kolizja współbieżnego utworzenia refu skutkuje brakiem dalszych mutacji. Historyczny Git HTTPS używa zwykłego push i wymaga oddzielnej kwalifikacji z atomowym create-if-absent. Używany obecnie REST nie zapewnia jednego zewnętrznego zapisu dla pełnej publikacji.
- **D.** Przygotowanie renderera odrzuca wiszący symlink w miejscu scratch przed kopiowaniem lokalnego runtime. Odbiór hosta, Chrome, keepera i sesji pozostaje zależny od osobnego celu.

Zakres i pola zgody pozostają w [manifeście LIVE](LIVE_QUALIFICATION.json). Żaden fixture nie wykonuje kwalifikacji LIVE. Wyniki na aktualnym headzie PR-u są w [Draft PR #58](https://github.com/luciferprosun/AIOA-spArkHAT/pull/58).
