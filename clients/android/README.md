# AIOA Companion — N1, źródła wersji 0.2.0-n1

Jeden pakiet `eu.sparkhat.aioa.companion`; nie nowy Core ani nowy provider.
Klient ma Preview, podpisany status/evidence i scoped STOP, bez Run/Approve/chat.
Kontrakt: `../../protocol/mobile_mission_v1.json`; host: istniejący
`runtime.webapp.WebRuntimeService` + `runtime.mobile_gateway.MobileGateway`.

**APK_BUILD_BLOCKED_TOOLCHAIN.** Sprawdzono źródła, nie wykonano kompilacji
Kotlin/JVM, Android lint ani testu urządzenia. Bez kwalifikowanego JDK17,
SDK36/build-tools35.0.0 i cache zależności nie uruchamiaj wrappera; samo `--offline`
nie powstrzymuje wrappera od próby pobrania brakującej dystrybucji Gradle.
Nie podmieniaj starego APK ani jego podpisu.

Po niezależnej weryfikacji kompletnego toolchainu/cache na maszynie budującej:

```sh
cd clients/android
./gradlew --offline --no-daemon --max-workers=1 testDebugUnitTest lintDebug assembleDebug
```

Dystrybucja: Gradle8.13, wrapper i distribution SHA w build-handoff oraz
`gradle/wrapper/gradle-wrapper.properties`. Kod nowy neutralny, pochodzenie w
`NOTICE.md`; starych projektowych źródeł bez ustalonej licencji nie kopiowano.

**REMOTE_DEPLOYMENT_BLOCKED.** Nie ma jeszcze natywnego adaptera kwalifikacji
TLS edge i produkcyjnego enrollment w tym checkoutcie; samo włączenie Tailscale
nie otwiera bramki. Android wymaga HTTPS/TLS1.3, systemowego CA/hostname,
oddzielnego TLS cert SPKI pin i niezależnego host identity SPKI, odrzuca profil
OFFLINE_FIXTURE. Nie włączaj obejścia, cleartext, automatycznych retry ani
fałszywego PINNED. Dokładne dalsze bramki: dokumentacja `docs/meta/mobile/`.

Odtwarzalna demonstracja zaimplementowanego hosta bez telefonu/sieci zewnętrznej:

```sh
python3 -B -m unittest discover -s tests -p test_meta_mobile_http.py -v
```

To rzeczywiste podpisane HTTP loopback:0 i istniejący fixture Core/receipts.
Nie jest to emulator Androida, fizyczny Xiaomi ani prawdziwe API Muse.
