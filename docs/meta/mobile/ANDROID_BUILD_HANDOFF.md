# Deterministyczny build-handoff

Stan N1: **APK_BUILD_BLOCKED_TOOLCHAIN**. Brak kwalifikowanych JDK17, SDK36,
Gradle8.13 oraz compiler/cache zależności; nie uruchomiono Gradle, JVM ani lint.
Sprawdzono PATH i znane lokalizacje JDK/SDK/cache; nie twierdzimy, że dowolne
nieprzeszukane cache są puste. Wyliczenie metadanych ogólnych cache napotkało
niezwiązane katalogi bez uprawnień — nie eskalowano dostępu ani nie wykonywano
znalezionych binariów. Koszt inferencji zero, pobranych toolchainów zero.

Wejścia: `clients/android/ANDROID_BUILD_INPUT_MANIFEST.json` (SHA każdego pliku,
rozmiar, executable, wersje i komenda). Weryfikacja bez zmian plików:

```sh
python3 -B -m runtime.mobile_gateway.build_handoff --check
```

Wymagane: JDK17; SDK/compile/target36; build-tools35.0.0; min26; Gradle8.13;
AGP8.11.1; Kotlin2.2.21. Kombinacja Gradle/JDK/SDK jest zgodna z
[oficjalnym AGP8.11](https://developer.android.com/build/releases/agp-8-11-0-release-notes).
SHA Gradle8.13 ZIP `20f1b1176237254a6fc204d8434196fa11a4cfb387567519c61556e8710aed78`,
wrapper `81a82aaea5abcc8ff68b3dfcb58b3c3c429378efd98e7433460610fecd7ae45f`
sprawdzono względem [Gradle release checksums](https://gradle.org/release-checksums/).
Wrapper jest niezmienionym upstream artefaktem, licencja zachowana; nie jest to
cache Gradle, JDK ani gotowy APK. Własny launcher sprawdza hash JAR przed użyciem.

Na osobno przygotowanej i zweryfikowanej maszynie, po potwierdzeniu lokalnego cache
Gradle i zależności, z katalogu `clients/android`:

```sh
./gradlew --offline --no-daemon --max-workers=1 testDebugUnitTest lintDebug assembleDebug
```

**Nie uruchamiaj wrappera przy brakującym cache dystrybucji:** Gradle `--offline`
dotyczy rozwiązywania zależności, wrapper może wcześniej próbować pobrania ZIP.
Nic takiego nie uruchomiono w N1. Nie ustawiaj wspólnego HOME ani nie korzystaj z
niezweryfikowanych binariów innego projektu; stan buildu trzymaj poza Git.

Po sukcesie wymagane rzeczywiste dowody: logi testów JVM (10 przygotowanych przypadków),
lint i assemble; merged manifest z pakietem/versionCode/min/target i jedynym
INTERNET; `apksigner verify --verbose --print-certs` dla powstałego APK; SHA256 APK;
potwierdzenie zgodności podpisu aktualizacji. Nie publikuj pełnych danych certyfikatu
w publicznych logach bez sprawdzenia. Artefakt i logi pozostają prywatne poza repo.
APK nie jest automatycznie instalowany, release signing i fizyczne UI/E2E są odrębne.

Stary APK0.1.0 pozostaje na źródle Companion, SHA256
`43943d19196d26e3be93015d1d6f1cad87a49f94015978ce40afa7ccce4725c6`,
12592824 bajty. Nie skopiowano ani nie podmieniono go. Nie udowadnia on funkcji N1.
