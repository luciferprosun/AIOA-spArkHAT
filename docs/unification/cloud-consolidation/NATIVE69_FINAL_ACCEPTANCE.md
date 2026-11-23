# Native #69 — odbiór przyszłej ścieżki

| Warunek | Wynik | Dowód |
| --- | --- | --- |
| Awaria po fizycznej publikacji, restart SQLite, UNKNOWN, HELD, rezerwacja, brak replay | PASS w zakresie fixture | `test_native_git_cold_controller`, także z samego archiwum źródeł AIOA |
| STOP, wygaśnięcie warrantu, utrata ACK, drift, obcy wykonawca i równoczesny odczyt | PASS w zakresie fixture | `test_native_git_publication_boundary`, `test_nz25_intent_cold_read` |
| Pochodzenie przy identycznym refie | PASS w zakresie fixture | `test_native69_witness_fixture` publikuje realny ref przez deskryptor z procesu brokera. Wiąże oryginalny inode, wykonuje trwały zapis podpisanego świadectwa i weryfikuje odczyt bez ACK. Przy awarii przed świadectwem, obcym wykonawcy i historycznym refie wynik weryfikacji pozostaje ujemny. Obcy klucz i zmienione wiązania są odrzucane. |
| Pełne Native, izolacja i zaufana tożsamość przyszłego wykonawcy | UNKNOWN, `BLOCKED_HOST / BLOCKED_SECURITY_REVIEW` | Bieżący broker publikuje w procesie Core. Proces Git ma dostęp tylko do odczytu. Brak kwalifikowanego klucza wykonawcy, rejestracji, trwałego magazynu i chronionego protokołu przekazania jednej próby. |

Prototyp fixture używa syntetycznej rejestracji klucza, tego samego UID i przykładowych digestów powiązań. Produkcyjne świadectwo musi pochodzić od uprawnionego wykonawcy CAS kontrolującego otwarty deskryptor lub od niezależnego zaufanego obserwatora kernela. Musi wiązać wyzwanie, START, intent, zużyty warrant, rezerwację, tożsamość fizycznego repozytorium, oryginalny inode i wynik synchronizacji. Zapis create-only z fsync pliku i katalogu poprzedza ACK. Sam podpis procesu Core po obserwacji docelowego refu nie wystarcza.

Wariant odrębnego UID wymaga odebranej ścieżki przekazania deskryptora i niezależnego odczytu, ponieważ obecna ścieżka sprawdza zgodność UID katalogu i plików z procesem. Weryfikator przyjmuje wyłącznie zarejestrowaną tożsamość oraz dokładne powiązania już zapisanego START. Rozlicza istniejący intent najwyżej raz. Brak świadectwa w oknie po CAS i przed utrwaleniem zachowuje UNKNOWN i HELD bez ponownego CAS.

Na zakwalifikowanym hoście uruchomić pełny test producenta i konsumenta z [manifestu](NATIVE_HOST_QUALIFICATION.md), wykorzystując nowe tymczasowe repo, osobny zaufany klucz, broker z kontrolą deskryptora, rejestrowany nonce i odczyt świadectwa z nowego procesu. Wymagać odtworzenia wszystkich pięciu scenariuszy i odmów przy podstawieniu klucza oraz domeny, wykazania niezmienności rezerwacji w przypadkach ujemnych i jednorazowego rozliczenia w przypadku utraty ACK po świadectwie. Dopiero taki wynik kwalifikuje `NATIVE_FORWARD_PATH_VERIFIED`.

Stan bieżący to `BLOCKED_HOST / BLOCKED_SECURITY_REVIEW`. [Wyjątek historyczny](NATIVE69_HISTORICAL_EXCEPTION.md)
