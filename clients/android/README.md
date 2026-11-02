# AIOA Companion — N1, źródła wersji 0.2.0-n1

Jeden pakiet `eu.sparkhat.aioa.companion`; nie nowy Core ani nowy provider.
Klient ma Preview, podpisany status/evidence i scoped STOP, bez Run/Approve/chat.
Kontrakt: `../../protocol/mobile_mission_v1.json`; host: istniejący
`runtime.webapp.WebRuntimeService` + `runtime.mobile_gateway.MobileGateway`.

Integracja ONE AIOA dodaje wersjonowany `/api/mobile/v2` w tej samej aplikacji:
typed agent proposal, kroki, pliki/SHA, diff, testy, plan zależności, lokalny
Git preview, receipt, STOP i UNKNOWN/readback. Kontrakt v1 zachowano.
Run/Approve/Install/GitHub-write/Meta-spend pozostają false; telefon proponuje
i obserwuje, host zatwierdza konkretny lokalny profil fixture. Podpisane testy
Pythona nie są wykonaniem kodu Kotlin. Nowy `AgentMissionViewTest.kt` pozostaje
NOT_RUN razem z JVM/lint/APK, do osobnego zakwalifikowanego builda.

Po utracie sesji nierozliczony agent proposal pozostaje związany ze starą
sesją; nowe enrollment nie daje dostępu do jego danych. W panelu Agent workspace
użyj jawnego „Keep agent ID for the host operator”, potwierdź zachowanie ID
i przekaż widoczny identyfikator operatorowi hosta do rozliczenia. Dopiero
synchroniczny zapis ID usuwa lokalną blokadę nowej propozycji; błąd zapisu lub
limit 128 zachowanych ID utrzymuje blokadę. To nie ponawia starego POST,
nie wysyła STOP/approval i nie zmienia Core UNKNOWN. Nowa propozycja ma nowe ID
i nadal wymaga świeżej sesji oraz osobnego zatwierdzenia na hoście.

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

## Cosmic pairing (version 0.3.0, code 3)

Home → **Connect my AIOA** opens the official Google Code Scanner, restricted to QR.
It needs Google Play services; first use may download its scanner module. This app
requests no CAMERA permission. If unavailable or cancelled, paste the complete
signed JSON envelope from the trusted Linux display. Optional `aioa://pair#…`
links contain unpadded base64url of exactly that canonical JSON; no URL is fetched.
Both inputs require local host confirmation before any pairing request is sent.
Compare the six-digit SAS on Linux and approve the exact request there.

Native profile capabilities currently allow signed status and session revoke.
Missions, chat and repository operations remain unavailable when the host does not
advertise their capability. Existing mission IDs, UNKNOWN readback and explicit
local handoff are retained. Advanced legacy enrollment is under Settings →
Diagnostic details. Home, Missions, Repositories and Settings use static Material3
screens with wrapping text, scrolling and minimum 48dp controls.

Only the public host binding (including owner scope), exact request ID/digest and
completion-attempt metadata are saved atomically in app-private, backup-excluded
preferences. The existing AndroidKeyStore alias and package are unchanged. Tokens
stay in memory. On restart, **Reconnect / recover session** proves the same pinned
host afresh and performs a new signed challenge/reconnect. New source/capsule
values are accepted only from that verified proof. No silent identity, TLS pin or
owner-scope replacement occurs; Forget is an explicit local action. It does not
revoke Linux device approval. Revoke current session ends only that session; the
Linux device revoke action is required to deny future reconnects.

An uncertain begin or complete is never automatically repeated. Read pairing
status uses the saved exact request metadata. Completion is marked durably before
sending; if its response is lost, explicit recovery rotates a fresh session via a
new challenge. Pending polling is spaced by at least 3.1 seconds, bounded by the
invite's 300-second lifetime and 98 automatic polls, and stops on expiry or HTTP429.
Backgrounding cancels pending polling; transport work is serialized.

`PairingProtocolTest` adds JVM behavior coverage for packet/link safety, signatures,
expiry/clock, host/scope continuity, response request binding and uncertain/revoked
completion. These tests have **not run here**: Java/JDK/Android SDK are absent and
no toolchain or dependencies were downloaded. The Python source suite is only a
static source check. APK assembly, lint, physical TalkBack/200% font and scanner
module qualification remain part of the concrete build/device gate.

### Reviewed lifecycle and language behavior

The deep-link activity uses `singleTask` for cold/warm VIEW delivery and clears
consumed intent data before recreation. Public binding writes use a durable
revision and atomic compare-and-set; Forget advances the revision even when the
same host is paired again. Resume reloads changed trust metadata and closes stale
transport. A stale owner cannot restore its previous host after Forget/rebind.
Corrupt public binding data remains fail-closed until explicit local Forget; this
does not clear unresolved mission IDs.

The new primary screens, spoken comparison code, connection states and ViewModel
messages use Android resources with English defaults and Polish translations.
Internal navigation IDs do not depend on translated labels. Messages retain
resource IDs/arguments, so composition resolves the current device language.
The physical gate must switch English ↔ Polish with a pending pairing and while
Settings is selected; inspect long Polish messages and dialogs at 200% font,
scrollability, 48dp targets and TalkBack digit pronunciation. Repeated cold/warm
VIEW deliveries, rotation/intent consumption, Forget/rebind and returning to an
older UI also require the qualified device gate. JVM ownership tests use the real
local ownership/store adapter with fake persistence and transport; they are not
Android Activity instrumentation or a claim of device execution.

Home shows **Pairing saved on this phone** as local pairing history. Only a fresh
signed observation with a valid enrolled session is presented as connected.
After the signed deadline, backgrounding, transport failure or session rejection,
Home must show refresh/recovery and keep the saved pairing as history. The
physical gate must check both rows and the reconnect action through each of
these transitions in English and Polish, including Linux revoke followed by
Refresh signed status. The JVM presentation regressions remain NOT_RUN until
the qualified Android toolchain is available.
