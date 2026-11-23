# Native #69 — wyjątek historyczny

Historyczny skutek ma status `UNKNOWN / BLOCKED_SECURITY_REVIEW`. Zgodny ref nie wskazuje pierwotnego wykonawcy. Nie ma potwierdzonego pierwotnego świadectwa dla tej operacji.

| Bramka | Stan | Dowód |
| --- | --- | --- |
| Zachowanie UNKNOWN, HELD i rezerwacji po restarcie | PASS w zakresie fixture | Powtórzenie testu realnego SQLite i fizycznego refu z samego archiwum źródła AIOA. Kontroler przyjmuje nową instancję, rozpoznaje dotychczasowy klucz i odmawia apply oraz reconcile. |
| Niezależność implementacji od repozytorium legacy | PASS w zakresie badanego pakietu i fixture | One-Core, packaging na dokładnym main, uruchomienie ze źródeł AIOA bez metadanych Git i bez źródeł legacy w ścieżce importu. |
| Rzeczywista historyczna rezerwacja, outbox oraz klucze | UNKNOWN | Brak dostarczonego zanonimizowanego spisu rzeczywistych rekordów, ich lokalizacji i próby odtworzenia. |
| Oryginalna atrybucja | UNKNOWN | Brak niezależnego trwałego świadectwa pierwotnego wykonawcy. |

Aby zapisać `HISTORICAL_CAS_UNKNOWN_CONTAINED`, operator przedstawia wyłącznie zanonimizowane metadane odczytu z istniejącego Core i dowód odtworzenia do izolowanego katalogu. Protokół obejmuje zanonimizowane identyfikatory oraz digests intentu, warrantu, rezerwacji i HELD, ścieżkę retencji zaszyfrowanej kopii, odcisk publicznego klucza i wyniki odmowy replay przed i po restarcie. Ustalić, że odtworzenie nie czyta starego repozytorium ani związanej usługi. Nie eksportować klucza prywatnego, sekretów i treści wrażliwej. Dokumentować ograniczenia dostępu i odtwarzania. Przy braku dowodu utrzymać rezerwację, UNKNOWN i HELD.
