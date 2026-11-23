# Odbiór pięciu faz po #60

Punkt odniesienia to scalony `main` `e071c339942525e8bd8759adafb565c5ad412ce9`, drzewo `f3f625a7f34f679638e0a3af3ebb395bb7fd9029`. Surowe źródła 69 pozycji pochodzą z W7A `392487849eddc7444f5159994b66b72e73f15934`. Macierz wiąże ten main z docelowymi blobami oraz z testami. Dodatkowy zakres offline w tym PR ma własny HEAD i własne wyniki. [Macierz](PARITY69_UPDATED.csv)

## Funkcje częściowe i kontrakty

| ID | Odbiór wykonany | Warunek dalszego odbioru |
| --- | --- | --- |
| 2 | Worker i zamknięty transport Codex, fixture protokołu bez inference | Przypięty model i endpoint, para klucz zadania/sesja, pojedyncze wywołanie i rozliczenie |
| 3 | WorkerMailbox, limity i zachowanie terminalne, fixture bez płatnych wywołań | Prawdziwy transport, rozliczenie HELD i odbiór wymaganych klientów W7A |
| 17 | READ Core odrzuca zduplikowane pola, liczby niefinitywne oraz błąd głębokości dekodowania i przyjmuje poprawne tablice oraz liczby skończone | Odbiór oficjalnego klienta. Pinned server v1.0.5 zwraca metadane jako tekst JSON i mały LICENSE jako osadzony zasób. Sprawdzić dokładny URI z commitem, długość, SHA-256 i Git blob. Odczyt `get_commit(include_diff=false)` nie zwraca drzewa. Drzewo potwierdzić niezależnie. |
| 18 | Prywatny fixture Git wykazał fast-forward obcego refu po wcześniejszym sprawdzeniu jego braku | Potwierdzić potrzebę historycznego HTTPS i wymagać atomowego create-if-absent, ograniczonego warrantu, niezależnej atrybucji i UNKNOWN po utracie ACK |
| 19 | Odczyt zwrotny GitHub wymaga jawnego `maintainer_can_modify=false`. Fixture odrzuca brak pola, true i wartość liczbową bez nowej mutacji. | Wyłączny zapis App w izolowanym repozytorium, kwalifikacja czterech mutacji oraz podpisany odczyt zwrotny |
| 41 | Repair Loop potwierdza STOP po zmianie stanu oraz termin po powrocie producenta przed uruchomieniem kolejnego wykonania. Fixture sprawdza brak otwarcia walidacji i sprzątanie. | Osobny odbiór prawdziwego workera i środowiska dla wymaganych profili |
| 63 | Przypięty Safe Launcher i regresje renderera | Pełna kwalifikacja G04 z Chrome, keeperem i izolacją |

Wszystkie 23 kontrakty nadal mają niepotwierdzonych odbiorców zewnętrznych. Macierz wskazuje obecne role Core, testy i indywidualne warunki zgodności. Najpierw ustalić właściciela kontraktu, wersję i rzeczywisty punkt wejścia oraz otrzymać przykładowe dane i odmowy. Właściciel podejmuje dla każdego kontraktu decyzję o odbiorze bieżącej implementacji, potrzebie adaptera lub formalnym wycofaniu. Zachować stan UNKNOWN dla nieustalonego zakresu. [Warunki 23 kontraktów](PARITY69_UPDATED.csv)

## Native #69

Dwuprocesowy test `test_native_git_cold_controller` używa NativeMobileComposition i trwałego SQLite, zapisuje START w Core, publikuje prywatny ref przez deskryptorowy mechanizm `_git_publish_new`, a następnie kończy producenta przez `os._exit(75)`. Konsument uruchamia się z nowym PID i instancją, otwiera tę samą bazę i klucz, po czym przez publiczne żądania kontrolera sprawdza odmowy `reconcile` i `apply`. Ref, rezerwacja, UNKNOWN i HELD pozostają zachowane. Syntetyczna kwalifikacja OS/TLS, fixture tożsamości celu i bezpośrednie wywołanie prymitywu ograniczają zakres. Pełna ścieżka przypiętego brokera z sandboxem i kontrolerem nadal wymaga izolowanego hosta.

Obecna publikacja działa wewnątrz procesu Core. Podpis hosta wystawiany po odczycie skutku sam nie ustala pierwotnego wykonawcy. Przyszły odbiór wymaga niezależnego klucza pierwotnie zarejestrowanego brokera, trwałego zapisu dowodu przed ACK, powiązania z konkretnym intentem i outboxem, trwałym CAS, fizycznym celem i stanem refu. Awaria w oknie między CAS a trwałym świadectwem pozostawia UNKNOWN i HELD bez replay. Dowód systemowy i przypadki błędne są warunkiem wdrożenia przyszłego protokołu. Historyczne #69 nadal ma stan `UNKNOWN / BLOCKED_SECURITY_REVIEW`. [Kwalifikacja hosta](NATIVE_HOST_QUALIFICATION.md)

## Decyzje i wznowienie

A–D mają osobne, nieuzupełnione zgody w manifeście. Archiwizacja i usunięcie są osobnymi decyzjami zależnymi od bramek wycofania. Następna synchronizacja operatora obejmuje już przyjęty zakres #60, wraz z jego rzeczywistym merge SHA/tree i kwalifikacją po scaleniu. Kolejny PR wymaga własnego odbioru i przypiętej zgody. [LIVE](LIVE_QUALIFICATION.json) · [Retirement](NONZERO_RETIREMENT_GATE.md) · [Linux Mint](LINUX_SYNC_HANDOFF.md) · [Wznowienie](RESUME.md)
