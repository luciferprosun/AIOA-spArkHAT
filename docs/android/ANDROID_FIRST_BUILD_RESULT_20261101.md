# Pierwsza rzeczywista próba Android — wynik i lokalna naprawa

Status wykonanej próby: **BUILD_FAILED_REAL / APK_NOT_BUILT**.
Nie uruchomiono kompilacji Kotlin, testów JVM, lint ani assemble. Nie ma APK, certu ani wyniku E2E.

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

Testy kandydata:89/89 PASS,92 subtests. Niezależny review nowego zakresu
`087937c…444ca36` przez `/root/review_android_first_ci_repair_20261101`
(GPT-6 Astra max, read-only):0Critical/0Important/1Minor; kod gotowy do merge,
bez certyfikacji wykonania. Reviewer sprawdził zapisane wyniki, nie uruchamiał
suite ani CI. Nie było serii napraw po tym review, bo nie znalazł blokera.

Minor M2 odroczony: setup-java pozostaje dodatkową zależnością joba APK,
choć builder korzysta z prywatnego JDK. Może być kolejnym punktem awarii lub
pobrać drugi JDK przy braku cache. Usunięcie go z CodeQL wymaga osobnego
sprawdzenia potrzeb init; nie rozszerzamy teraz zakresu o porządkowanie.
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

Decyzje naprawy: istniejący SHA-bound importer zamiast podążania za cache
(koszt:193.6MB transferu JDK na kwalifikowanym runnerze); metadata/env muszą
być spójne przed checkout (koszt: następna próba może ponownie odmówić przed
narzędziami); zachowanie main i nowej lokalnej gałęzi (koszt: zmiana nie trafi
na serwer przed nowym exact-source GO). Nie rozstrzygnięto przyczyny
historycznej rozbieżności obrazów ani dostępności przyszłej VM/archiwum.

## Kontynuacja po AIOA_APK_Update_2026-11-01.pdf — R4/R5/R6

Aktualizacja operatora jest doprecyzowaniem tej samej naprawy. Wykorzystujemy
wcześniejszy odbiór A22 i ten sam reviewer; nie tworzymy kolejnego audytu.
Jedna dodatkowa próba jest zatwierdzona i nadal niewykorzystana w chwili
tego checkpointu. Zgody SDK, ekspozycji i wskazanej migracji CodeQL pozostają
zapisane; zmiany poniżej mieszczą się w doprecyzowanym zakresie CI/helperów.

- R4: ten sam prywatny JDK jest sprawdzany przez rzeczywiste java -version z właściwościami java.home/os.arch oraz javac -version przed Gradle. Błędny compiler/arch/home odmawia. Usunięto oba zbędne setup-java; nie ma drugiego pozyskania Android JDK. Po śledzonej kompilacji JAVA_HOME/PATH analizującego kroku CodeQL wskazuje ten sam prywatny katalog. Sam silnik CodeQL pozostaje przypiętym osobnym narzędziem z własnym runtime dostawcy.
- R5: bounded snapshot metadata_version/declared_version/SHA jest wypisywany także przed odmową przy konflikcie. Bootstrap nadal poprzedza checkout, nie nadpisuje ImageVersion i nie zmienia pina.
- R6: JSON zachowuje natywny kod BLOCKED_SYMLINK także przy braku root/logów, etap i zamkniętą rolę ścieżki, dostępny exit code oraz jawne NOT_RUN dla nieosiągniętych etapów. Diagnostyczne adnotacje nie tworzą uprawnień ani nowego journala. Raport rozróżnia IMAGE_CHECK, JDK_PREPARE, SDK_CHECK, GRADLE_BOOTSTRAP, JVM_TESTS, LINT, ASSEMBLE, SIGNATURE_VERIFY, ARTIFACT_UPLOAD i CODEQL. Upload jest NOT_RUN w momencie generowania pliku; jego rzeczywisty wynik wymaga późniejszego readbacku joba/artefaktu.

Testy R4/R6: RED7przypadków(2fail/6errors), następnie96/96PASS,
94subtests. To nadal testy offline. Rzeczywisty JVM/APK jest celem następnej
zatwierdzonej pojedynczej próby, a nie wynikiem tego checkpointu.

Ten sam reviewer ocenił wyłącznie delta R4/R5/R6:0Critical/1Important,
werdykt With fixes. I1 dotyczył błędnego etapu dla JUnit/lint we wspólnym
weryfikatorze i dla compileDebugKotlin w celu CodeQL. Autor zamknął go
regresjami przez execute i failure JSON: RED2przypadki/3fail → GREEN98/98,
96subtests. Brak ponownego pełnego audytu; źródła Core/Android bez zmian.

## Kontynuacja 2026-11-02 — pierwsza próba zatwierdzonego DEBUG

Właściciel zatwierdził pakiet 5d3b29a i rozszerzył zgodę na uzasadnione
naprawy oraz kolejne próby do ukończenia obecnego etapu, każda do35min,
wyłącznie z zasobami bez dodatkowych opłat. Nie zmienia to authority agenta.
PR30 po dodaniu brakującego testowego PyYAML6.0.3 przeszedł pełne regresje
Core/Python3.11 i3.12: po2554 testy(5 dozwolonych pominięć) oraz105 native
regressions bez pominięć. Pakowanie i cztery analizy CodeQL także przeszły.

Merge/source: c5c5d18703fb551e0dc96a1b16915bc0eb2d68d4.
Run41382329699 / job125075620948: rzeczywisty IMAGE_CHECK, checkout
i preflight SDK przeszły; zachowano MISMATCH_ACCEPTED_DEBUG i inwentarz9f81….
Przy przygotowaniu JDK nastąpił BLOCKED_COMPONENT_DRIFT, przed java/javac
i Gradle. JVM/lint/assemble/APK pozostają NOT_RUN/NONE. Failure artifact
13112764805 pobrano i niezależnie sprawdzono ZIP SHA-256:
8609c2589e933a47344cbe531361caeea36be1df40b1cb7efa3f1b47044e9801.

Przyczyna: tree_manifest sortował obiekty Path według części ścieżki,
a archive_inventory sortował pełne względne ciągi. Dla katalogów modułów
o wspólnym prefiksie kolejność się różniła mimo zgodnych plików. Oficjalne
archiwum JDK193594705B zweryfikowano SHA-2568b9b611d…fe8711 i odczytano
bez wykonywania kodu:454 pliki; pierwsza różnica przy indeksie160 to
legal/java.management/ADDITIONAL_LICENSE_INFO wobec
legal/java.management.rmi/ADDITIONAL_LICENSE_INFO. To porządek tablicy,
nie dowód zmiany archiwum lub usunięcia granicy integralności.

Minimalna naprawa: archive_inventory sortuje względne PurePosixPath,
tak samo jak istniejący tree_manifest. Sam tree_manifest i serializacja SDK
pozostają bez zmian; zachowujemy dokładny zatwierdzony pin9f81….
Pozostają wszystkie porównania SHA, bajtów,
bitów wykonania, całego zbioru plików oraz zakaz symlinków na dysku.
Regresja rzeczywistego acquire na małym archiwum z legal/java.xml oraz
legal/java.xml.crypto daje RED1failure/0errors → GREEN1; podmieniony plik
nadal odmawia. Osobny golden-vector SDK wykazał RED dla zmiany globalnego
porządku i chroni zgodność istniejącego pina. Zestaw Android:112 testów
/121subtests,0fail/errors/skips.
To testy offline i analiza prawdziwego archiwum, nadal nie wykonanie JVM/APK.
Prawdziwe archiwum wypakowano także w prywatnym katalogu diagnostycznym:
454 pliki mają zgodne SHA/bajty/bity wykonania; stara kolejność świadectwa
nie pasuje, poprawiona pasuje. Nie wykonano kodu JDK ani zmiany systemowego PATH.
Następna próba będzie oparta na tej konkretnej poprawce i aktualnym merge.
Ustawienia CodeQL pozostają default/cztery grupy/weekly, bez migracji.

## Kontynuacja 2026-11-02 — poprawny SDK22 i komunikat dostawcy

PR31 po niezależnym review bez uwag i pełnym CI scalono jako
f8e3d3c13bf41d21af9c89d43ee3182fb9b18dca. Run41385237119 /
job125084502168 przeszedł JDK_PREPARE, w tym rzeczywiste java/javac.
Zatrzymał się na SDK_CHECK/BLOCKED_CI_SDKMANAGER_VERSION. Native SDK
pozostał zgodny z pinem9f81…; manager zwrócił exit0. Failure artifact
13115002400/1141B zweryfikowano ZIP SHA-256:
7f94467f735815c3a141fcc36b0d68ec8434d35e5bce9b654947570332f0c171.

Oficjalne cmdline-tools22 pobrano ze zgodnym SHA-2564e4c464f…eedf583
i odtworzono samo sdkmanager --version w prywatnym katalogu. Wynik22.0
poprzedzają trzy stałe linie ostrzeżenia SDKMANAGER_DEPRECATED. Po
normalizacji wyłącznie ścieżki JDK_JAVA_OPTIONS do tej z CI odtworzone
534B mają identyczny hash jak rzeczywisty sdkmanager-version.log:
ad42222c9e519d3ea28028192b1f18e91b6dea90a5a1a83c6524a028632da329.
Normalizacja to dowód pochodny z replay, nie kolejny rzeczywisty run CI.

Parser dopuszcza ten jeden dokładny blok informacyjny przypiętego narzędzia,
nadal wymaga pojedynczej wersji22.0 i odmawia błędnych/zmienionych ostrzeżeń,
dodatkowych błędów, innej lub powtórzonej wersji. Ostrzeżenie zachowuje
jawny kod w logu i BUILD_INVOCATION. Nie zmieniono toolchainu, SDK,
SHA archiwów, profilu STRICT, pina9f81…, ustawień CodeQL ani klienta Android.
Nie uruchomiono sugerowanej w komunikacie migracji do Android CLI.

Regresja rzeczywistego formatu: RED1failure/0errors → GREEN1 oraz cztery
odmowy zmienionego wyjścia; pełny właściwy zestaw:113 testów/125subtests.
JVM testy aplikacji, lint, assemble i APK nadal NOT_RUN/NONE.

## Kontynuacja 2026-11-02 — rzeczywisty Gradle i kontrakt manifestu APK

PR32 po pełnym CI i niezależnym review scalono jako
b98d9afe5eceb336eb1fab81f51c9b0baab9a071. Rzeczywisty run
41387925783 / job125092781691 wykonał Gradle testDebugUnitTest,
lintDebug i assembleDebug z kodem0. Zatrzymał się później przy
SIGNATURE_VERIFY/BLOCKED_APK_CONTRACT. APK nie zostało opublikowane.
Failure artifact13116571414/1350B ma ZIP SHA-256
a543fa57c709fb9f897cd39255da7887b4885d07cef88fd4799baa60ea2c6a30.
Trwały raport ma JVM_TESTS/LINT/ASSEMBLE=PASS i build.log4000B,
SHA-256c061c1e7a339bf6e04c91abd3de2c439bd46878215b50163404d58f1ab10c3da.
Liczba przypadków JUnit i wyniki inspekcji podpisu nie zostały dotąd odebrane;
nie zastępujemy ich statusem procesu Gradle.

Dotychczasowa kontrola dopuszczała wyłącznie INTERNET. Oficjalny
[manifest AndroidX Core](https://android.googlesource.com/platform/prebuilts/sdk/+/5c762fb2f6235bbe5d006d3a26063a8e921354b4/current/androidx/manifests/androidx.core_core/AndroidManifest.xml)
dodaje app-scoped DYNAMIC_RECEIVER_NOT_EXPORTED_PERMISSION z poziomem signature.
Potwierdzono też manifest oficjalnego AAR core1.15.0 wymaganego bezpośrednio
przez ui-android1.9.0. SHA-256 AAR:
432b85a1974076e14b487ece4a28c59a84f1b9efc3fc8be72cd7f05d32055e51.
To dowód z zależności i uzasadniona przyczyna do sprawdzenia w kolejnym APK,
nie odzyskany manifest poprzedniego runu ani dokładny resolved graph.

Minimalna zmiana weryfikatora dopuszcza dodatkowo tylko dokładną nazwę
eu.sparkhat.aioa.companion.DYNAMIC_RECEIVER_NOT_EXPORTED_PERMISSION.
Osobny odczyt aapt xmltree z tego samego APK wymaga pojedynczej deklaracji
na poziomie manifestu z dokładnym protectionLevel=signature, bez innych flag.
Inny pakiet, normal/dangerous/privileged, duplikat, brak lub zagnieżdżona
deklaracja odmawiają. Dodatkowe uprawnienia, w tym READ_SMS, nadal odmawiają.
Nie usuwamy ochrony AndroidX ani nie zmieniamy manifestu aplikacji.
Jawny signature_permissions trafia do evidence i ponownej kontroli kopii.
Osobne kody IDENTITY/SDK/PERMISSIONS/RECEIVER_PERMISSION zawężają przyszły
błąd bez publikowania surowego wyjścia narzędzia.

Testy najpierw wykazały odmowę poprawnego formatu; finalny zestaw offline:
115 testów/134subtests,0fail/errors/skips. To weryfikacja parsera i kontraktów,
nie nowa kompilacja. Profil STRICT, zaakceptowany wyjątek DEBUG, pin SDK9f81…,
workflow28c879ca…, toolchain i ustawienia CodeQL pozostają bez zmian.
Kolejny run musi niezależnie potwierdzić rzeczywisty manifest, JUnit, lint,
podpis i powiązanie APK ze źródłem, zanim artefakt będzie dostępny.
