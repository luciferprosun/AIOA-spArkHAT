# Pierwsza rzeczywista próba Android — wynik i lokalna naprawa

Status wykonanej próby: **BUILD_FAILED_REAL / APK_NOT_BUILT**.
Nie uruchomiono Kotlin/JVM/lint/assemble. Nie ma APK, certu ani wyniku E2E.

## Wykonana zgoda właściciela

- [PR28](https://github.com/luciferprosun/AIOA-spArkHAT/pull/28),15 zatwierdzonych plików,9 commitów, head `1a4e5f5e54aef7c2e25ef4759ca8f0c59e444482`.
- Merge main: `087937c16dc907fef14feb83daadbb93747e9e1d`, tree `c81639b0d7ec61a708ca0f9576330afe3b489b9c`, identyczne z reviewowanym head. Rodzice: ad5ae304 i1a4e5f5.
- Automatyczny CodeQL PR41321888795 i main41322133403: SUCCESS czterech grup.
- Jawna migracja default→advanced i profil advanced-v1 wykonane z odczytem stanu.
- Dokładnie jeden POST workflow_dispatch, attempt1, actor luciferprosun, exact merge SHA; [run41322536413](https://github.com/luciferprosun/AIOA-spArkHAT/actions/runs/41322536413).
- Run FAILED w debug-apk/job124895617839. Kroki źródła/SDK/workflow/env-image/JDKsetup przeszły; helper zatrzymał przygotowanie narzędzi kodem BLOCKED_SYMLINK.
- APK upload pominięty; Kotlin i reusable SAST pominięte, bo zależą od debug-apk.
- Filtrowany failure JSON opublikowany jako artifact13089748516,625B, SHA256 ZIP `82895f2ed90b7cd167edc40d659312b5a1aaf242622820de829ea1c747c4f7e8`. Pobrany i niezależnie sprawdzony hash; dane wiążą ten sam run/source/workflow. JSON nie deklaruje APK/sukcesu i nie zawiera raw logu.
- Warunkowy rollback wykonany: advanced variable usunięty, default configured, default/remote/standard, cztery grupy i schedule weekly przywrócone. [Walidacja41322922197](https://github.com/luciferprosun/AIOA-spArkHAT/actions/runs/41322922197): SUCCESS.
- Nie było drugiego dispatch, rerun, model API, instalacji na telefonie/hostcie ani zmiany usług/Tailscale/WD.

## Przyczyna i brakujące dowody

Publiczny instalator [obrazu runnera](https://github.com/actions/runner-images/blob/ubuntu24/20261026.354/images/ubuntu/scripts/build/install-java-tools.sh#L38)
tworzy symlink `Java_Temurin-Hotspot_jdk/VERSION/x64` do `/usr/lib/jvm/temurin-17-jdk-amd64`.
Przypięty [setup-java](https://github.com/actions/setup-java/blob/b843ebf9b913146b38da2eaa7aeddf76074ae1ad/src/distributions/base-installer.ts#L182)
preferuje tool-cache. Helper żądał safe_path(JAVA_HOME), więc ta kompozycja
jest niezgodna z polityką bez symlinków. Lokalny test odtwarza ten sam
BLOCKED_SYMLINK na tym wywołaniu. Właściwa ścieżka błędu nie została
zapisana w pierwotnym failure JSON; źródło przyczyny wskazują kod dostawcy,
JAVAHOME z logu i reprodukcja, a nie nowy odczyt usuniętego runnera.

Druga obserwacja: startup log opisuje obraz20261025.353.1, natomiast
ImageVersion zaakceptowane przez preflight ma20261026.354.1. Nie rozstrzygamy
tej sprzeczności przez zmianę tekstowego inputu ani nie nazywamy obrazu
niezależnie zakwalifikowanym. Faktyczne nowe środowisko pozostaje UNKNOWN.
Oficjalny [producent imagedata](https://github.com/actions/runner-images/blob/ubuntu24/20261026.354/images/ubuntu/scripts/build/configure-image-data.sh)
publikuje Runner Image/Version w `/imagegeneration/imagedata.json`.

## Kandydat lokalnej poprawki — NIE OPUBLIKOWANY

Gałąź: `codex/android-pinned-jdk-repair-20261101`, baza dokładnie087937c.
Nie zmienia Core, klienta Android, podpisów, protokołów ani uprawnień CI.

1. Istniejący `ci_build.acquire` pobiera na przyszłym kwalifikowanym runnerze JDK17.0.21+9 z istniejącego toolchain.lock: SHA256 `8b9b611d917e3dfd8419d3566b5949226f69b052fed7e109c1368add1dfe8711`. Własny root/jdk-17 zamiast podążania za cache symlinkiem. Po buildzie ponowny component_check, w evidence jawne archive SHA. Zakaz symlinków zostaje.
2. Bootstrap wszystkich trzech jobów sprawdza przed checkoutem root-owned regularny imagedata.json, bez symlinków i group/world write, bounded read/race, dokładny obraz/wersję oraz zgodność z ImageVersion. Rozbieżność kończy job przed pobieraniem JDK/SDK. Nie zmieniono pina20261026.354.1.
3. Syntetyczne offline testy odtwarzają cached JDK symlink i konflikt25/26, sprawdzają publisher SHA, katalog JDK, zły/duplicated metadata, rzeczywiste O_NOFOLLOW i umieszczenie bootstrap przed checkoutem. Nie wykonują Java ani pobrania JDK.

JDK ma193594705B; przyszły run pobierze ten przypięty plik zamiast ufać
cache obrazu. To dodatkowy transfer standardowego runnera, bez zmiany
budżetu modeli. Samo przejście testów offline nie potwierdza dostępności
archiwum, nowej kompilacji ani zgodności metadanych przyszłego obrazu.

Testy kandydata:89/89 PASS,92 subtests. Review nowego zakresu: PENDING.
Dokładny końcowy head/tree/hash patcha i review zapisujemy prywatnie;
nie wpisujemy do tego pliku jego własnego przyszłego commitu.

Pierwotna zgoda obejmowała jeden dispatch — został wykorzystany. Nowy
head nie jest objęty zgodą na publikację/merge, a następna próba wymaga
nowej jawnej zgody tylko na nowy zakres/źródło i dodatkowy dispatch.
Wcześniejsza akceptacja niezmienionych warunków SDK/ekspozycji pozostaje
zapisana; nie jest nową zgodą na liczbę wywołań.

Kolejna próba może zatrzymać się na konflikcie metadanych jeszcze przed
narzędziami. Taki wynik pozostaje BLOCKED_RUNNER_QUALIFICATION, nigdy PASS.
Do odbioru nadal potrzeba realnych JVM/lint/assemble, aapt/apksigner/hash,
jednego powiązanego receipt oraz osobnego odbioru Kotlin CodeQL/API readback.
Telefon/produkcja/Muse LIVE pozostają osobnymi zadaniami.
