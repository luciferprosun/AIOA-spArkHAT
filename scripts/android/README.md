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
Wrapper nie startuje przy brakującym/drift cache. Budowanie kieruje cache,
intermediates, temporary files, debug key i raporty pod zakwalifikowany root,
uruchamia jeden worker/no-daemon, kompilator Kotlin in-process, bez device install.
Gradle może użyć własnego jednorazowego procesu, który nie jest trwałym daemonem.
RAM preflight wymaga co najmniej1.5GiB dostępne; obecny host tego nie potwierdził.

Verifier wymaga poprawnych rzeczywistych JUnit testcase,0fail/error/skip i lint,
package/version/SDK/permissions/debuggable, ważnej DEBUG signature i SHA APK.
Nie oznacza RELEASE, PHONE_TESTED ani zgodności podpisu aktualizacji starego APK.
Raw local logs zostają prywatnie w katalogu własnego buildu, bez publikacji.

```sh
python3 -B -m unittest discover -s tests -p 'test_android_*.py' -q
```

Testy używają małych własnych fixture/temporary dirs i blokad; nie są testem
fizycznego HDD, JDK, Gradle czy telefonu. `bash -n` uruchomiono; ShellCheck brak,
nie zainstalowano go i nie ogłoszono jego wyniku PASS.

Źródła: [Gradle checksums](https://gradle.org/release-checksums/),
[PathAssembler8.13](https://github.com/gradle/gradle/blob/v8.13.0/platforms/core-runtime/wrapper-shared/src/main/java/org/gradle/wrapper/PathAssembler.java),
[Google downloads](https://developer.android.com/studio#command-tools),
[SDK manager](https://developer.android.com/tools/sdkmanager),
[Temurin API](https://api.adoptium.net/v3/assets/latest/17/hotspot?architecture=x64&image_type=jdk&os=linux).
