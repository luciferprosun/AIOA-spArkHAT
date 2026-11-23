# Bramka wycofania repozytorium NonZero

**Decyzja bieżąca: HOLD.** Oryginał `luciferprosun/AIOA-NonZero-CloudOps-Agent` pozostaje źródłem historii. Repozytorium wykonawcze to `luciferprosun/AIOA-spArkHAT`. Odczyt dotyczy main po #59 i zakresu badanego kandydata. Znaczenie statusów — PASS potwierdza cel w podanym zakresie, FAIL oznacza niespełniony warunek, UNKNOWN wymaga dalszego dowodu.

| Bramka | Status | Dowód lub warunek odbioru |
| --- | --- | --- |
| Jeden Core | PASS | One-Core i source policy na przypiętym main. Historyczny pakiet jest wykluczony z importów i dystrybucji. |
| Zależności w badanym kodzie i CI | PASS | Przeszukanie śledzonego runtime, konfiguracji pakowania, skryptów i workflow. Wystąpienia nazwy źródła dotyczą strażników i pochodzenia. Powtórzyć w finalnym SHA, w tym URL, nazwę pakietu i pin W7A. |
| Zewnętrzne wdrożenia i klienci | UNKNOWN | 23 kontrakty oczekują na ustalenie bieżącego odbiorcy. Sprawdzić deploymenty, prywatne integracje, importy, URL i wsparcie poza tym repozytorium.  Bieżący stan usługi, rollout, domenę, możliwość odtworzenia i ewentualne wymagania jury lub Devpost potwierdza właściciel. |
| Pozycje funkcjonalne | FAIL | Otwartych jest siedem PARTIAL i trzy SECURITY_BLOCKED. Odbiór musi wykazać normalne wejścia Core i rozliczyć cel wykluczeń #16 i #53. Użycie historycznego HTTPS #18 wymaga ustalonego odbiorcy, atomowego create-if-absent i atrybucji. |
| Pakowanie i uruchomienie bez legacy | PASS | Hosted packaging 3.11/3.12 buduje i uruchamia instalację z pojedynczego repozytorium. Objąć docelowy commit i deklarowane profile wdrożeń. |
| Licencja i pochodzenie | PASS | `runtime/nonzero_cloudops/LICENSE-NONZERO.txt`, polityka pochodzenia, inventory NZ12, piny W7A i Judge. Zachować prawa, noty, źródła blobów i świadectwa po finalnym scaleniu. |
| Cztery kwalifikacje środowiskowe | FAIL | Wszystkie LIVE mają wynik NOT_RUN. Dla każdego toru wymagany rzeczywisty wynik albo formalnie zatwierdzona zmiana zakresu. |
| Nierozstrzygnięte operacje | FAIL | Native #69 ma UNKNOWN, trwałą rezerwację i HELD. Zabezpieczyć dziennik, klucze weryfikacji, tożsamości i dowody bez replay. Odrębna decyzja o zachowaniu nierozstrzygnięcia wymaga dowodu, że wycofanie nie wpływa na ochronę operacji. |
| Pierwsza kopia Git | PASS | Bundle SHA-256 `84e5720c6cab3a8be59669a83396ed00018269be04e80e31bdc1e75d4828331e`. Przywrócenie wszystkich 13 reklamowanych refów do osobnego repozytorium i `git fsck --full --no-dangling`. Przed decyzją porównać z aktualną listą refów. |
| Druga niezależna kopia Git | UNKNOWN | `BLOCKED_BACKUP`. Na niezależnym nośniku zweryfikować sumę, odtworzyć do czystego katalogu, porównać listę refów i wykonać pełne fsck. |
| Dane poza historią Git | UNKNOWN | Osobno zinwentaryzować PR, issues, assets, wiki, LFS, releases i istotne artefakty CI. Zapisać uzgodniony zakres, retencję, kontrolę dostępu i próbę odtworzenia. |
| Rollback i dokumentacja użytkowników | UNKNOWN | Po odbiorze przypiąć instrukcje do finalnego SHA i sprawdzić wszystkie wejścia używane przez potwierdzonych konsumentów. Aktualizować odnośniki do pochodzenia po zatwierdzeniu ścieżki wycofania. |

Dla każdego niepotwierdzonego kontraktu wybrać jawnie utrzymanie dla wskazanego konsumenta albo zatwierdzone wycofanie ze wskazaniem okna i sposobu powiadomienia. [Macierz i kryteria](PARITY69_UPDATED.csv) · [Manifest LIVE](LIVE_QUALIFICATION.json) · [Bramki bezpieczeństwa](SECURITY_GATES.md)

## Wariant A — archiwizacja

Po odbiorze bramek udokumentować finalne refy obu repozytoriów oraz miejsce odtworzonych kopii i eksportów. Wyłączyć bieżące odwołania wdrożeń, zachować dostęp do dowodów i potwierdzić odtworzenie. Zebrać odrębną zgodę właściciela wskazującą repozytorium, jego identyfikator 1342916553, listę refów i archiwizację. Po autoryzowanej operacji sprawdzić stan archived, dostęp do historii oraz niezależność AIOA. Rollback obejmuje odarchiwizowanie przez właściciela i odtworzenie połączeń z zatwierdzonego spisu.

## Wariant B — trwałe usunięcie

Po dodatkowym odbiorze obu niezależnych kopii oraz uzgodnionego eksportu danych serwisu wykonać próbę odtworzenia repozytorium w prywatnej izolacji. Porównać refy, obiekty i najważniejsze artefakty. Właściciel potwierdza osobno dokładne repozytorium oraz trwałe usunięcie ze świadomością, że odtworzenie Git nie odtwarza z definicji tożsamości GitHub, uprawnień ani historycznych URL. Plan awaryjny odtwarza zachowane Git i eksporty we wskazanym miejscu.

## Spis odczytowy po #60

GitHub pokazuje 20 wdrożeń Render w środowisku `21068474465`. Najnowsze `6378024487` zakończyło się sukcesem 10 września 2026 r. dla commita `03d1c8f6a1d254c98c0b4e88fc93e25ea85ed4c7` z gałęzi `codex/portable-d1-d2-m1-overnight`. Metadane wskazują usługę `srv-dabtq00n74is738f147g`. Odczytany blueprint W7A wiąże tę nazwę usługi z innym refem. Najnowszy blueprint wdrożonego commita wskazuje tryb mock i wyłączony autodeploy. Odbiór wymaga potwierdzenia bieżącej konfiguracji, aktywności, odbiorców, domeny i możliwości odtworzenia z panelu właściciela. [Rekord wdrożenia](https://api.github.com/repos/luciferprosun/AIOA-NonZero-CloudOps-Agent/deployments/6378024487/statuses)

W widocznym API zidentyfikowano jeden scalony PR, #1, bez zwykłych issues, releases, Actions artifacts ani Pages. Flagi Wiki i Projects są włączone. Publiczny odczyt Git Wiki zwrócił brak repozytorium. Odczyt webhooków zwrócił HTTP 403. Na 179 commitach osiągalnych z reklamowanych refów brak trafień dokładnego nagłówka LFS i historii konfiguracji LFS lub submodule. Zakres Git ma osobny dowód odtworzenia. Zawartość Wiki i Projects, ustawienia dostępu, integracje, eksporty PR i deploymentów oraz retencja danych pozostają do zweryfikowania przed usunięciem. [Historyczny PR](https://github.com/luciferprosun/AIOA-NonZero-CloudOps-Agent/pull/1)

Scoped test po utracie procesu odtwarza Native SQLite, klucz i prywatny ref wyłącznie z fixture AIOA oraz odmawia replay bez odwołania do legacy. Produkcyjne miejsca przechowywania starszych intentów i kluczy wymagają potwierdzenia właściciela. Do tego czasu zachować całość stanu i kopii. [Opis testu](FIVE_PHASE_HANDOFF.md)
