# AIOA Android tooling

Jedna lokalizacja narzędzi, jeden istniejący klient/Gradle wrapper. To narzędzia
utrzymaniowe użytkownika, bez powiązania z mobilnym Run/owner authority AIOA.
**Aktualnie G1 BLOCKED: nie instalowano niczego na LSC_DATA3 ani na telefonie.**

```sh
python3 -B scripts/android/toolchain_doctor.py --json
bash scripts/android/install_toolchain.sh --dry-run --source-sha EXACT_40_HEX_HEAD
bash scripts/android/build_apk.sh --source-sha EXACT_40_HEX_HEAD
```

Przy obecnych warunkach wszystkie kończą się exit2/BLOCKED bez mkdir/download/build.
Rzeczywista instalacja wymaga kwalifikacji G1 i czystego, dokładnego source SHA;
`--dry-run` nigdy nie wykonuje write probe. Licencje nie są automatycznie przyjmowane.
`env.sh` można source per command dopiero po pozytywnej kontroli istniejącego
toolchainu; nie zmienia HOME ani żadnego globalnego shell profile.

`toolchain.lock.json` zawiera wyłącznie publiczne stable URLs/wersje/hash/licencje
i czas pozyskania metadanych; archiwów nie pobrano. Piny: JDK17.0.21+9 x64 Linux,
Gradle8.13/wrapper SHA z N1, AGP8.11.1, Kotlin2.2.21, API36, BT35.0.0,
cmdline-tools22.0 (konkretny build15859902, nie zmienny „latest”). Oficjalny XML
ma już cmdline23.0; nie przepisano wersji po cichu.

**Null SHA256 dla platform/BT jest twardą blokadą lokalnego pozyskania.** Google
XML publikuje SHA1; tego ani samodzielnie policzonej SHA256 nie nazywamy zaufaną
opublikowaną SHA256. Nie obchodź bramki. SDK license record musi już istnieć
po rzeczywistym, osobnym działaniu właściciela w oficjalnym SDK managerze;
obserwacja pliku nie dowodzi samodzielnie prawnego przyjęcia warunków.
Narzędzia nie wykonują komendy przyjęcia licencji i nie zapisują jej hashy.

Po kwalifikacji sam instalator może etapowo zainstalować JDK/Gradle, a SDK
pozostawić BLOCKED_LICENSE/PUBLISHED_SHA256. Prawidłowe istniejące komponenty
są używane ponownie po hash check; obca instalacja nie jest nadpisywana.
Resume dotyczy jedynie `.part` znanego archiwum i końcowej SHA256, bez ślepego
retry. Corrupt bytes/staging zostają do diagnostyki. ZIP/TAR traversal, link escape,
urządzenia, duplikaty i bomb size są odrzucane. Bezpieczne wewnętrzne file aliases
TAR są materializowane, z uwzględnieniem ich rozmiaru w budżecie.

Gradle trafia do cache własnego wrappera według upstream URL layout, bez globalnego
Gradle. MD5/base36 służy **tylko nazwie katalogu zgodnej z PathAssembler**, nigdy
bezpieczeństwu; integralność to publisher SHA256 plus hashe zainstalowanych plików.
Przy każdym ponownym użyciu oczekiwane hashe są wyprowadzane z zachowanego
archiwum cache o zgodnej opublikowanej SHA256. Sąsiedni manifest nie jest
źródłem zaufania; podmiana binarium wraz z manifestem jest odrzucana. Brak lub
uszkodzenie archiwum blokuje weryfikację bez automatycznego pobrania. Osobny
limit manifestu komponentu wynosi16MiB; piny/raporty authority nadal64KiB.
Wrapper nie startuje przy brakującym/drift cache. Budowanie kieruje cache,
intermediates, temporary files, debug key i raporty pod zakwalifikowany root,
uruchamia jeden worker/no-daemon, kompilator Kotlin in-process, bez device install.
Gradle może użyć własnego jednorazowego procesu, który nie jest trwałym daemonem.
RAM preflight wymaga co najmniej1.5GiB dostępne; obecny host tego nie potwierdził.
Ignorowane pliki pod `clients/android`, w tym `local.properties`, blokują build;
nie kasujemy ich. Tak samo nieprzejrzane `gradle.properties`, `init.gradle[.kts]`
i zawartość `init.d/` we własnym Gradle user home. Zachować je i przenieść lub
odebrać osobno przed następną próbą. SIGTERM/SIGINT uruchamiają cleanup tylko
własnej grupy procesu, z przywróceniem handlerów. Launcher JVM korzysta z
`JDK_JAVA_OPTIONS`, obsługiwanego przez [Java17](https://docs.oracle.com/en/java/javase/17/docs/specs/man/java.html#using-the-jdk_java_options-launcher-environment-variable),
bez zmiany istniejącego launchera N1; nie polega na jego obsłudze JAVA_OPTS.

Verifier wymaga poprawnych rzeczywistych JUnit testcase,0fail/error/skip i lint,
package/version/SDK/permissions/debuggable, ważnej DEBUG signature i SHA APK.
Nie oznacza RELEASE, PHONE_TESTED ani zgodności podpisu aktualizacji starego APK.
Raw local logs zostają prywatnie w katalogu własnego buildu, bez publikacji.
Samodzielne `verify_apk.py` potwierdza metadane/podpis/hashe, lecz zwraca
`DEBUG_APK_VALID_SOURCE_UNBOUND`, `source_sha:null`, `source_binding:UNKNOWN`
i exit2. Aktualny checkout jest opisany osobno jako `inspected_checkout_sha`.
Ścieżka zawierająca SHA nie dowodzi pochodzenia APK. Wyłącznie zaufany proces
kontrolowanego buildu po sukcesie dopina `CONTROLLED_BUILD_PROCESS`, source SHA,
hash komendy/invocation, logu i raportów; nie jest to zewnętrzna atestacja SLSA.

```sh
python3 -B -m unittest discover -s tests -p 'test_android_*.py' -q
```

Testy używają własnych fixture/temporary dirs, w tym450 plików inventory,
fałszywego Java do przechwycenia wywołania launchera i osobnego procesu STOP.
Nie wykonują rzeczywistego JDK/Gradle. Kontrakt YAML wymaga istniejącego PyYAML;
niczego nie instalowano. Testy nie są testem
fizycznego HDD, JDK, Gradle czy telefonu. `bash -n` uruchomiono; ShellCheck brak,
nie zainstalowano go i nie ogłoszono jego wyniku PASS.

Źródła: [Gradle checksums](https://gradle.org/release-checksums/),
[PathAssembler8.13](https://github.com/gradle/gradle/blob/v8.13.0/platforms/core-runtime/wrapper-shared/src/main/java/org/gradle/wrapper/PathAssembler.java),
[Google downloads](https://developer.android.com/studio#command-tools),
[SDK manager](https://developer.android.com/tools/sdkmanager),
[Temurin API](https://api.adoptium.net/v3/assets/latest/17/hotspot?architecture=x64&image_type=jdk&os=linux).
