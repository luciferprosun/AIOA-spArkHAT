# Bramki bezpieczeństwa NonZero

## Native #69

**Stan `UNKNOWN / BLOCKED_SECURITY_REVIEW`.** W Core istnieje jedna ścieżka autoryzacji i rozliczenia. Historyczny wiersz 69 opisuje też niezależną weryfikację workspace W7A. Jego przypadek plikowy ma węższe założenia niż odzyskiwanie wykonawcy Native Git CAS.

1. Core wiąże intent z kapsułą, tożsamością celu, refem, oczekiwanym stanem i żądanym commitem. Warrant wiąże dokładny intent, podmiot, sesję, dzierżawę i ryzyko. `CoreIntentJournal` konsumuje warrant w tej samej transakcji, w której przechodzi rezerwacja do `UNKNOWN` i powstaje `HELD` w outboxie.
2. Native zapisuje stan przed wysłaniem do brokera. Broker sprawdza tożsamość repozytorium i zapisuje zaplanowane obiekty, a następnie wykonuje dokładny CAS. Dla zapisu refu stosuje prywatny plik tymczasowy, synchronizację pliku, wyłączne utworzenie i synchronizację katalogu.
3. Utrata potwierdzenia może nastąpić przed fizycznym CAS, po CAS lub po rozliczeniu. W tym samym procesie Core może odczytać wynik przez oryginalny zarejestrowany uchwyt i jego kwalifikowane dziecko. Po zimnym restarcie ten uchwyt nie istnieje. Odczyt repozytorium pokazuje stan i ciągłość celu, ale nie ustala, kto wykonał CAS.
4. W przypadku historycznym utrzymać `UNKNOWN`, nienaruszoną rezerwację i `HELD`. Operator może odczytać stan bez uprawnień do replay. Wygaśnięcie, nowa sesja, zgodny ref i reflog Git nie zwalniają rezerwacji.

Odniesienia w `main` to `runtime/mission/intent.py` (`_start_in_transaction`, `_load`, `reconcile`), `runtime/mission/warrant.py`, `runtime/mission/git_publish.py` (`_dispatch_local_patch`, `_complete_local_patch`), `runtime/mission/sandbox_linux.py` (`_git_publish_new`, `_git_plumbing`) i `runtime/mission/coding_tasks.py` (`_native_git_reconcile`). Istniejący producent `TERMINAL_CHILD_ACQUISITION` w `tests/nz13_native_coding_support.py` wykonuje fizyczny CAS i symuluje utratę potwierdzenia. Test fork NZ11 i nowy test dziennika wykonują prywatny Git w fixture. Zakres tego dowodu obejmuje trwałość i odmowę replay, a odbiór Native wymaga kwalifikowanego hosta i pełnego kontrolera.

### Warunek bezpiecznego przyszłego rozliczenia

Istniejący broker powinien dostarczyć uwierzytelnione świadectwo dopiero po fizycznym CAS i potwierdzonej trwałości, zanim wyśle ACK do wywołującego. Świadectwo musi obejmować oryginalną zarejestrowaną tożsamość brokera i jej zaufany klucz, digest intentu i warrantu, ID i digest rezerwacji, tożsamość fizyczną repozytorium, ref i poprzedni oraz docelowy OID. Weryfikator Core musi niezależnie sprawdzić podpis, powiązanie tożsamości z pierwotną rejestracją, ciągłość celu, dokładne pokwitowanie i brak konfliktu z dotychczasowym rozliczeniem. Samodzielny zapis świadectwa po CAS pozostawia okno awarii między oboma trwałymi zapisami. Dopóki brakuje dowodu dla tego okna, `UNKNOWN` pozostaje wynikiem. Przed dopuszczeniem automatycznego rozliczenia trzeba sprawdzić błędy i odrzucenia przy każdym przejściu, w tym brak lub powtórzenie świadectwa i próbę przeniesienia go na drugi ref lub repozytorium.

## Kontrakty historyczne

Macierz rozróżnia odtworzone źródło, fakty użycia Core i brak dowodu po stronie starego konsumenta. W7A dokumentuje własne demo i klientów loopback Bearer API. Zidentyfikowanie tych przypadków nie ustanawia bieżącej zależności zewnętrznej. Każdy odbiór wymaga właściciela konsumenta, wspieranej wersji lub refu, importu/URL i metody, zanonimizowanych żądań i odpowiedzi z błędami, wymagań dotyczących pól i normalizacji oraz testu porównawczego przez rzeczywiste wejście Core. Sprawdzić uprawnienia, STOP, wygasanie, restart, UNKNOWN i powtórzenie. Przypadki zewnętrzne wymagają oddzielnego celu i zgody. Dla #24 wartości W7A i ścieżki HTTP są niezgodne mimo aliasów żądań; adapter musi raportować rzeczywisty tryb i framework.

## Zgody na odbiory i scalanie

`LIVE_QUALIFICATION.json` zawiera cztery wnioski z polami do przypięcia. Każdy wniosek wymaga oddzielnej odpowiedzi `GO` z wypełnionymi wartościami i terminem. Przy C trzeba rozstrzygnąć znaczenie „jeden efekt”. Bieżący adapter jednej publikacji wykonuje cztery mutacje create-only (tree, commit, ref, draft PR). Jedna mutacja API wymaga innego, jawnie zatwierdzonego kontraktu. Produkcyjny AIOA jest niedopuszczalnym celem tego testu.

Do merge sprawdzić aktualny head PR-u i SHA bazy, cztery wymagane kontrole na aktualnym headzie, CodeQL, dowody pochodzenia i One-Core w dzienniku `certify`, oraz reguły ochrony i autoryzację właściciela. GitHub API zwraca `protected=true` i cztery wymagane statusy dla `main`. Pełny endpoint administracyjny ochrony zwraca HTTP 403 dla instalacji. Ten wynik pozostawia szczegóły wymaganych zatwierdzeń do weryfikacji przed merge.
