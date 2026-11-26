# Bramka wycofania repozytorium NonZero


## Decyzja po #76, 26 listopada 2026

**HOLD — zachować oryginał, Render i historyczne UNKNOWN / HELD.** Odczyt przeprowadzono na kodzie `d2870f33bb740184f7c2a18a7ea8f90b070fbd64`, tree `569f5591b2be0ae34c81701a3a54ea46e018c411`. GitHub potwierdził repozytorium legacy ID `1342916553`, `archived=false`, zero forków i brak push po 10 września. Z 69 pozycji 23 pozostają `UNKNOWN_EXTERNAL`, siedem `PARTIAL` (#2, #3, #17, #18, #19, #41, #63), a #69 `SECURITY_BLOCKED`. [23 kontrakty z odtworzonymi importerami](EXTERNAL_CONTRACT_DECISIONS.md) · [Macierz](PARITY69_UPDATED.csv)

| Odbiór | Wynik |
|---|---|
| Lokalna pierwsza kopia | **PASS**. Na laptopie przywrócono bundle SHA-256 `84e5720c6cab3a8be59669a83396ed00018269be04e80e31bdc1e75d4828331e` do świeżego, prywatnego repozytorium bare. Wszystkie 13 nazw i OID, w tym `refs/pull/1/head`, są identyczne ze świeżym `ls-remote --refs`. Lista `OID SP REF LF` posortowana bajtowo ma SHA-256 `9cd19a7d2caa6c3bfc4bb88888e6928b3e642bd92b25442bac96863183f14c36`. `git bundle verify` i `git fsck --full --no-dangling` zakończyły się kodem 0. Odtworzono 179 commitów i 2674 osiągalne obiekty. |
| Druga niezależna lokalizacja | **BLOCKED_BACKUP**. Dwa dostępne, zgodne bajtowo pliki na laptopie leżą na jednym systemie plików. Historyczny katalog na `LSC_DATA3` nie jest zamontowany. Wykryty osobny dysk z etykietą `LSC_DATA` nie ma punktu montowania ani potwierdzonej tożsamości celu retencji. Poprzednie odtworzenie Cloud pozostaje dowodem testu. |
| Metadane GitHub | Prywatnie zachowano 38 projekcji JSON i sprawdzono ekstrakcję archiwum do osobnego katalogu oraz wszystkich 38 sum. SHA-256 archiwum `41965734d0155f3e84b144dd61f8dc40e775e82d2fc1ba8db9a9e587bab5ab37`, manifestu plików `6f27ca1686831c8c6bd7696ddab10da1b245cf32d98c9742b0b884d69151ab0c`. Zapis obejmuje jeden scalony PR, jego issue i dwa zdarzenia, brak komentarzy i recenzji, 20 deploymentów z ich statusami, 1 environment, 0 hooks dostępnych dla bieżącego właściciela (HTTP 200), 0 releases, workflow, runs i artefaktów. Pages 404, wiki git NOT_FOUND, ProjectsV2 odmowa z powodu braku `read:project`. To projekcje danych, bez tajnych ustawień i gwarancji odtworzenia tożsamości GitHub. |
| Render | Ostatni deployment `6378024487`: success, status `18168281817` o 18:06:08 UTC 10 września. Bieżący stan procesu, domen i odbiorców **UNKNOWN**. Brak skonfigurowanego dostępu CLI/API do płaszczyzny zarządzania Render. |
| Historyczny Native #69 | **UNKNOWN / HELD**, z zachowaną rezerwacją. Brakuje zredagowanego potwierdzenia miejsca retencji rzeczywistego journalu i materiału do weryfikacji. Kwalifikacja następnego START jest osobnym odbiorem. |

### Rekord do decyzji właściciela

1. **Nośnik i odtworzenie.** Wskaż faktyczny, odrębny, zarządzany nośnik/konto oraz okres retencji. Udostępnij istniejącą kopię do odczytu pod potwierdzonym punktem montowania albo najpierw zapisz tam zweryfikowany bundle i archiwum metadanych. Na tym nośniku wykonaj poniższe sprawdzenia. Zachowaj receipt identyfikujący operatora, czas UTC, publiczny identyfikator lokalizacji kopii, sumę, politykę dostępu i wynik. Pełne ścieżki oraz surowe dane przekazuje się prywatnie.
2. **Metadane spoza Git.** Właściciel repozytorium otwiera zakładki Wiki i Projects i zapisuje liczbę/identyfikatory aktywnych obiektów lub potwierdzoną pustą listę. Dla istniejących projektów wskazuje eksport i jego retencję. Właściciel zapisuje identyfikatory potrzebnych instalacji i polityk dostępu oraz sposób ponownego nadania ról. Nie przekazuje credential ani wartości ustawień tajnych.
3. **Render i odbiorcy.** Otwórz usługę `srv-dabtq00n74is738f147g` w istniejącym koncie, zapisz status, repo/ref, SHA aktywnego deploymentu, domeny, rollback i zanonimizowane zagregowane żądania za 30 dni lub faktyczne krótsze okno retencji. Dla każdego potwierdzonego odbiorcy wpisz kontakt właścicielski i kontrakt do tabeli. Brak ruchu w krótkim oknie nie potwierdza braku konsumentów. [Usługa w panelu](https://dashboard.render.com/web/srv-dabtq00n74is738f147g) · [Dokumentacja metryk Render](https://render.com/docs/service-metrics)
4. **Stan #69.** Opiekun Core potwierdza prywatne niezmienione identyfikatory środowiska, zapewnioną retencję oryginalnego journalu/HELD i materiału weryfikacyjnego, procedurę odtworzenia z zablokowanym redispatch oraz niezależność tej retencji od usunięcia legacy. Nie wymaga to odczytu historycznego klucza prywatnego. [Wyjątek historyczny](NATIVE69_HISTORICAL_EXCEPTION.md)
5. **Dyspozycja końcowa.** Rekomendacja teraz: `KEEP`. Po odbiorze powyższych pozycji właściciel wybiera jawnie `KEEP` albo `ARCHIVE`, wskazując repo ID, aktualny manifest refów, oba miejsca retencji, wynik odtworzeń, identyfikatory decyzji kontraktowych, wpływ na Render i #69, datę UTC i podpis. Trwałe usunięcie wymaga odrębnej dyspozycji `DELETE` z akceptacją utraty identyfikatorów GitHub. Brak zatwierdzonego okna lub brak jakiegokolwiek wymaganego dowodu utrzymuje HOLD.

Odtworzenie dla drugiej lokalizacji. `BUNDLE` ma wskazywać zweryfikowany plik na osobnym nośniku, a `OUT` nowe, nieistniejące miejsce na scratch. Przykład używa Bash:

```bash
set -euo pipefail
umask 077
: "${BUNDLE:?}" "${OUT:?}"
mkdir -- "$OUT"
printf '%s  %s\n' 84e5720c6cab3a8be59669a83396ed00018269be04e80e31bdc1e75d4828331e "$BUNDLE" | sha256sum -c -
git init --bare -q "$OUT/restored.git"
git -C "$OUT/restored.git" bundle verify "$BUNDLE"
git -C "$OUT/restored.git" fetch --no-tags "$BUNDLE" '+refs/*:refs/*'
git ls-remote --refs https://github.com/luciferprosun/AIOA-NonZero-CloudOps-Agent.git | awk '{print $1 " " $2}' | LC_ALL=C sort > "$OUT/advertised"
git -C "$OUT/restored.git" for-each-ref --format='%(objectname) %(refname)' | LC_ALL=C sort > "$OUT/restored"
cmp "$OUT/advertised" "$OUT/restored"
sha256sum "$OUT/restored"
git -C "$OUT/restored.git" fsck --full --no-dangling
```

## Historyczny odczyt po integracji d2fc4cb8

Stan `RETIREMENT_HOLD` przy kodzie `d2fc4cb88c1777e572c099c8082b93e6b7a6c0b1`. Dwie kopie odtworzono w różnych środowiskach: na laptopie i w odizolowanym workspace Cloud. Każde odtworzenie objęło 13 zgodnych refów, 179 commitów i 2674 osiągalne obiekty, fsck exit 0. Długoterminowa retencja Cloud i druga niezależna kopia pod trwałą kontrolą właściciela pozostają niepotwierdzone. Wszystkie 1312 osiągalnych blobów sprawdzono pod kątem wskaźników Git LFS v1. Wynik zero. Publiczny odczyt GitHuba pokazuje 1 PR, 0 issues, 0 releases i 0 przebiegów Actions. Uwierzytelniony odczyt .wiki.git zwrócił repository not found mimo włączonej flagi wiki. Zawartość wiki i Projects pozostaje niepotwierdzona. Ostatni z 20 zapisów Render to udane wdrożenie 6378024487 z 10 września 2026 r. Aktualny stan Render i jego odbiorcy pozostają UNKNOWN.

Niezależność kodu i pakowania jest zakresem integracji. Aktywność Render, rozliczenie konsumentów, retencja GitHub, odtwarzalność kopii i utrzymanie historycznej operacji UNKNOWN / HELD są oddzielnymi warunkami wycofania. Oryginał pozostaje źródłem historii. [Checkpoint](CHECKPOINT.json) · [Macierz 69](PARITY69_UPDATED.csv)

**Decyzja bieżąca: HOLD.** Oryginał `luciferprosun/AIOA-NonZero-CloudOps-Agent` pozostaje źródłem historii. Repozytorium wykonawcze to `luciferprosun/AIOA-spArkHAT`. Odczyt dotyczy main po #59 i zakresu badanego kandydata. Znaczenie statusów — PASS potwierdza cel w podanym zakresie, FAIL oznacza niespełniony warunek, UNKNOWN wymaga dalszego dowodu.

| Bramka | Status | Dowód lub warunek odbioru |
| --- | --- | --- |
| Jeden Core | PASS | One-Core i source policy na przypiętym main. Historyczny pakiet jest wykluczony z importów i dystrybucji. |
| Zależności w badanym kodzie i CI | PASS | Przeszukanie śledzonego runtime, konfiguracji pakowania, skryptów i workflow. Wystąpienia nazwy źródła dotyczą strażników i pochodzenia. Powtórzyć w finalnym SHA, w tym URL, nazwę pakietu i pin W7A. |
| Zewnętrzne wdrożenia i klienci | UNKNOWN | 23 kontrakty oczekują na ustalenie bieżącego odbiorcy. Sprawdzić deploymenty, prywatne integracje, importy, URL i wsparcie poza tym repozytorium.  Bieżący stan usługi, rollout, domenę, możliwość odtworzenia i ewentualne wymagania jury lub Devpost potwierdza właściciel. |
| Pozycje funkcjonalne | FAIL | Kandydat zamyka #16 i #53 w zakresie roli autoryzacyjnej. Siedem PARTIAL i historyczny #69 nadal wymagają odbioru. Użycie historycznego HTTPS #18 wymaga ustalonego odbiorcy, atomowego create-if-absent i atrybucji. |
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

## Ponowny odczyt Render po #61

Read-only odczyt GitHub pokazuje 20 rekordów, środowisko `21068474465` i najnowszy deployment `6378024487`, z ostatnim statusem success z 10 września 2026 r. Nie ma późniejszego dowodu runtime ani potwierdzenia aktywnych odbiorców. Stan bieżący to UNKNOWN.

**Jedna kontrola po stronie właściciela.** W panelu Render otwórz usługę `aioa-agents-for-humans-demo` (`srv-dabtq00n74is738f147g`), sprawdź stan usługi, źródło repo/ref i ostatni wdrożony SHA, domeny, podłączone integracje i zanonimizowaną aktywność z ostatnich 30 dni. Zapisz datę, te pola oraz potwierdzenie, czy któryś odbiorca zależy od usługi. Przekaż wynik bez sekretów i treści requestów.

Druga niezależna kopia pozostaje `BLOCKED_BACKUP`. Nośnik `LSC_DATA3` jest niedostępny w Cloud. Po udostępnieniu przywrócić bundle do nowego katalogu, porównać nazwy i OID wszystkich 13 refów oraz wykonać `git fsck --full --no-dangling`. [Native historyczny](NATIVE69_HISTORICAL_EXCEPTION.md) · [Kontrakty](EXTERNAL_CONTRACT_DECISIONS.md)

## Stan zweryfikowany po #62

PR #60 jest scalony. Ostatni wynik operatora Linux Mint jest przypięty do #59, a stan po fast-forward pozostaje do poświadczenia. Świeży odczyt GitHub nadal pokazuje 20 historycznych wdrożeń Render. Aktualny runtime i odbiorcy pozostają UNKNOWN. W śledzonym runtime, pakowaniu, workflow, skryptach i deploy nazwa starego repozytorium pojawia się w strażniku pochodzenia. Odtworzony pierwszy bundle zgadza się z 13 refami GitHuba i przeszedł fsck. Drugi nośnik i checkout Mint pozostają poza środowiskiem wykonawczym Cloud. Wycofanie ma HOLD. [Handoff](LINUX_SYNC_HANDOFF.md)
