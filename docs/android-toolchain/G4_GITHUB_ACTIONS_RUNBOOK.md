# G4 — ręczny build GitHub, przygotowany do odbioru

**READY_FOR_OWNER_REVIEW / NOT_RUN.** Zdefiniowano workflow i sprawdzono jego
kontrakt offline. Nie uruchomiono Actions, Gradle ani instalacji SDK. Nie powstał
nowy APK. Nie ma podstaw do `GITHUB_ACTIONS_PASS`.

Pliki: `.github/workflows/android-manual-build.yml`, `scripts/android/ci_build.py`,
`tests/test_android_manual_workflow.py`. Profil CI jest odrębny od lokalnej
instalacji. Nie tworzy zgody dla LSC_DATA3, nie modyfikuje Core ani telefonu.

## Zanim właściciel uruchomi workflow

1. Przejrzeć dokładny commit nowej gałęzi `codex/android-toolchain-mobile-20261031`
   i różnicę względem bazy PR. Sprawdzić wszystkie odziedziczone zmiany, jeżeli
   zdalna baza jest starsza od lokalnego N1. Nie wybierać `main` jako ref buildu.
2. Zweryfikować uprawnienia, billing/limity Actions, widoczność repozytorium,
   dostęp do artefaktów i dopuszczalność przechowywania DEBUG APK. Repozytorium
   podczas inspekcji było publiczne. Wymóg logowania do pobrania artefaktu nie
   czyni go prywatnym dla właściciela. Retencja wynosi jeden dzień.
3. Sprawdzić [oficjalny obraz Ubuntu 24.04](https://github.com/actions/runner-images/blob/main/images/ubuntu/Ubuntu2404-Readme.md)
   oraz konkretny release obrazu. Zapisać jego dokładne `ImageVersion`, np.
   `YYYYMMDD.N.N`; przykład nie jest zatwierdzoną wersją. Mutable etykieta
   `ubuntu-24.04` nie jest niezmiennym obrazem. Skrypt odmówi przy różnicy wersji.
4. Potwierdzić prawo korzystania z już zaakceptowanych przez dostawcę obrazu
   licencji SDK. Skrypt nie zapisuje licencji, nie uruchamia `--licenses`, nie
   przesyła `yes`. Istniejący hash w `licenses/` sam nie dowodzi zgody prawnej.
5. Potwierdzić dostęp do oficjalnych repozytoriów zależności Gradle projektu
   oraz pobrań Gradle/Google. Ten profil ma świeży cache i rozwiązuje zależności
   online. Nie wykonuje wywołań modeli, publikacji ani instalacji na telefonie.
6. Oddzielnie autoryzować jeden konkretny run i dopiero wtedy ustawić trzy
   potwierdzenia wejściowe na `true`. Domyślnie wszystkie są `false`.

Ten dokument nie stanowi takiej autoryzacji. Nie uruchamiać workflow w ramach
obecnego zlecenia. Nie zmieniać ustawień repozytorium w celu obejścia blokady.

## Rejestracja i parametry

GitHub wymaga obecności pliku obsługującego `workflow_dispatch` na domyślnej
gałęzi, aby udostępnić ręczny trigger. Sam push tej gałęzi/draft PR może nie
zarejestrować workflow. Zgodnie z [dokumentacją zdarzeń GitHub](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#workflow_dispatch)
to osobny krok właściciela: przegląd i ewentualna późniejsza akceptacja
workflow na default branch. **Nie wykonano merge do `main`, zmiany default
branch, tymczasowego triggera push ani obejścia przez inny workflow.**

Po przyszłej rejestracji: wybrać ref `codex/android-toolchain-mobile-20261031`,
wpisać `expected_source_sha` równy jego pełnemu SHA i `expected_runner_image`
równy wcześniej przejrzanej wersji obrazu. Workflow używa dokładnego
`github.sha`, nie ref przekazanego przez tekst użytkownika. SHA jest ponownie
porównywany z czystym checkoutem i manifestem N1 przed buildem oraz po nim.
Zmiana nazwy gałęzi wymaga przeglądu stałej w YAML i skrypcie, nie flagi bypass.

## Wersje i granica zaufania

JDK Temurin **17.0.21+9** z przypiętego `actions/setup-java`; Gradle **8.13**
z istniejącego wrappera i opublikowanego SHA256; AGP **8.11.1**, Kotlin
**2.2.21**, compile/target **36**, min **26**, build-tools **35.0.0** — bez
zmiany plików aplikacji. Cmdline-tools **22.0** są instalowane w prywatnym
katalogu jednego runu z oficjalnego ZIP o przypiętym SHA256.

API36 revision2 i build-tools35 muszą już istnieć w oficjalnym obrazie SDK.
Skrypt sprawdza `source.properties`, obecność wymaganych plików, licencję,
liczy inventory SHA256 wszystkich plików tych dwóch pakietów i ponownie
porównuje je po buildzie. **To zaufanie do zweryfikowanego obrazu dostawcy,
nie niezależnie opublikowane SHA256 archiwum Google.** Brak pakietów, zmiana
rewizji, symlink albo drift kończą run. Fallback pobrania tych pakietów jest
zablokowany, dopóki katalog nie dostanie niezależnie zweryfikowanych silnych
sum. Nie wstawiono SHA1 w pole SHA256. Nie uruchamiamy automatycznego
uzupełniania SDK lub pobierania JDK przez Gradle.

Przypięte oficjalne akcje, tagi rozstrzygnięte przez GitHub API i kontrakty
`action.yml` przejrzane przy przygotowaniu:

| Akcja | Wersja referencyjna | Dokładny commit |
|---|---|---|
| actions/checkout | v4.2.2 | `11bd71901bbe5b1630ceea73d27597364c9af683` |
| actions/setup-java | v4.7.1 | `c5195efecf7bdfc987ee8bae7a71cb8b11521c00` |
| actions/upload-artifact | v4.6.2 | `ea165f8d65b6e75b540449e92b4886f43607fa02` |

Przegląd konfiguracji i pinów nie jest audytem każdej linii bundli upstream.
Pozostają zaufanie do dostawców oraz aktualność bezpieczeństwa tych wersji.
Nie dodano cache współdzielonego między runami, self-hosted runnera, PAT,
sekretów projektu ani dostępu do kluczy podpisujących właściciela.

## Przebieg jednego przyszłego runu

`workflow_dispatch` → kontrola potwierdzeń i dozwolonej gałęzi → checkout SHA
z `contents: read` i `persist-credentials: false` → JDK17 → weryfikacja
obrazu/źródła/SDK/licencji/wrappera → pobranie i sprawdzenie Gradle/cmdline-tools
→ `testDebugUnitTest lintDebug assembleDebug` z jednym workerem i JVM 1 GiB
→ odczyt rzeczywistych XML JUnit/lint → `aapt`/`apksigner` → SHA256 i ponowny
odczyt kopii APK → upload tylko APK i przefiltrowanego `APK_EVIDENCE.json`.

Katalog wyjściowy: `$RUNNER_TEMP/aioa-android-<run_id>-<run_attempt>/`.
DEBUG keystore pozostaje w tym runie i nie trafia do artefaktu. Pełne logi
procesów są zachowane na efemerycznym runnerze do diagnozy, nie przesyłane do
publicznego logu ani artefaktu. Po błędzie nie ma auto retry ani uploadu.
Status komunikowany jest kodem blokady, nie treścią środowiska czy tokenu.

Workflow ma limit 35 min; skrypt ogranicza build do 30 min, log do 8 MiB,
liczbę workerów do 1. Kolejka nie anuluje wcześniejszego runu. Anulowanie
przez GitHub kończy własny job; nie daje dowodu, że aplikacja działa na Xiaomi.

Wynik PASS wymaga rzeczywistego poprawnego runu, liczby testów z prawdziwych
`testcase`, braku błędów lint, właściwego pakietu/uprawnień, DEBUG podpisu,
hasha APK i tożsamego source SHA. Wówczas można oznaczyć **CI DEBUG build**
PASS. Nadal nie oznacza to Android E2E, release signing, kwalifikacji dysku,
działania Meta LIVE ani produkcyjnego owner admission.

Odtwarzalność: przypięto główne wersje i źródła oraz archiwa narzędzi.
Pełna odtwarzalność bajtowa zależności nie została udowodniona: N1 nie ma
kompletnego transitive dependency lock/verification metadata. Nie dodawano
go do klienta przy okazji zadania narzędziowego. Receipty uczciwie opisują
`ONLINE_VENDOR_REPOSITORIES_NOT_FULLY_HASH_LOCKED`.

Rollback: nie dispatchować; zamknąć draft PR bez merge. Po przyszłym runie
artefakt wygasa po jednym dniu; wcześniejsze usunięcie/zatrzymanie runu
pozostaje osobną czynnością właściciela. Nie usuwać nieznanych danych ani
nie cofać zmian w innych gałęziach.
