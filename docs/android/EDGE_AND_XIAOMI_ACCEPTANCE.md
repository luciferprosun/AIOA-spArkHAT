# A16 — edge i odbiór Xiaomi po rzeczywistym APK

Status: **PROJEKT / REMOTE_DEPLOYMENT_BLOCKED / ANDROID_E2E_NOT_RUN**.
Ten patch nie zmienia Core, protokołu mobilnego ani aplikacji Android.

## Istniejąca ścieżka i blokada

`clients/android` → `runtime.webapp` → `MobileGateway` → istniejący
`MissionService` → `CoreAdmission` i wspólny TransactionRunner/AUDIT/OUTBOX.
Wersja v2 przekazuje propozycję do tego samego zadania; Run nadal wymaga
oddzielnego lokalnego principal `OWNER_APPROVAL`. Transport ES256 nie jest
warrantem Core ani zgodą na WRITE, GitHub, instalację lub koszt modelu.

`MobileGateway.__init__` w `runtime/mobile_gateway/service.py` dopuszcza
obecnie wyłącznie fixture + provider MOCK + tenant offline-fixture.
`MobileClient.verifyHostProof` odrzuca profil OFFLINE_FIXTURE dla telefonu.
`runtime.webapp` wiąże HTTP tylko do loopback; handler mobilny jest już
adapterem do tej samej instancji MissionService. Sam reverse proxy nie
usuwa żadnej z tych blokad. Nie wolno zmienić fixture na LIVE flagą.

Brakuje autentycznej kompozycji ownera oraz zakwalifikowanych: exact HTTPS
origin, cert chain/hostname, TLS SPKI, osobnego host identity SPKI, audience,
source SHA/capsule i owner scope. `runtime/mobile_gateway/doctor.py` jest
pasywnym raportem; obserwacja Tailscale/Android nie kwalifikuje tych danych.

## Minimalny przyszły adapter — bez drugiego gatewaya

1. Zaufany host dostarcza skonfigurowaną, tę samą instancję CoreAdmission,
   MissionService i TransactionRunner oraz rzeczywisty lokalny owner binding.
   Brak lub odwołanie bindingu blokuje enrollment i Run.
2. Oddzielnie zakwalifikowany prywatny HTTPS edge przekazuje do istniejącego
   loopback `runtime.webapp` tylko `/api/mobile/v1/` i `/api/mobile/v2/`.
   Nie przekazuje UI, CSRF/bootstrap, owner ani dowolnego API. Nie ufamy
   `Forwarded`/`X-Forwarded-*` jako dowodowi tożsamości lub origin.
3. Dokładny zewnętrzny origin i dwa różne piny (TLS i podpisujący host)
   pochodzą z zaufanego enrollmentu operatora, nigdy z nagłówka klienta.
   Błędny hostname, challenge, audience, source albo pin odmawia przed
   wysłaniem kodu/credential. Nie dodajemy cleartext ani trust-all TLS.
4. Profil produkcyjnego transportu musi zostać podłączony do obecnego
   MobileGateway dopiero po dowodach z punktów 1–3 i odrębnych testach.
   Obecny patch projektuje tę granicę, nie tworzy fikcyjnego profilu.

Nie uruchomiono Serve/Funnel/ACL, publicznego portu, cert provisioning ani
enrollmentu. Implementację profilu odkładamy, ponieważ nie istnieją jeszcze
kwalifikowane dane wejściowe ani zgoda na zdalną ekspozycję. Koszt tej
decyzji: nawet poprawny APK nadal nie sparuje telefonu z obecnym fixture.

## Odbiór po APK i osobnej zgodzie P1

| Krok | Dowód wymagany | Warunek odmowy |
|---|---|---|
| Instalacja | SHA-256 APK = zaakceptowane CI evidence; cert DEBUG; decyzja o ewentualnym odinstalowaniu starej aplikacji | Inny cert/hash; zgodność aktualizacji starego APK UNKNOWN |
| Klucz telefonu | Nowy P-256 w Android Keystore na Xiaomi 13T Pro, rzeczywiste Android15/HyperOS2 zapisane prywatnie | Import starego klucza AGM H6; brak ochrony/algorytmu |
| HTTPS | Fresh TLS1.3, prawidłowy hostname/chain i niezależny TLS SPKI | Zły SPKI/hostname, redirect, TLS downgrade, cleartext |
| Host proof | Challenge, audience, osobny host SPKI, capabilities, SHA/capsule/scope, expiry | Fixture, stale/zmienione źródło, zła sygnatura |
| Enrollment | Kod prebound do nowego device SPKI, TTL ≤300s, wystawiony lokalnie przez ownera, zużyty raz | Stolen code, inny device, drugi redeem/replay |
| Status/Preview | Typowane, podpisane odpowiedzi, exact nonce/method/path/session/device/source, odczyt bez efektu | Skażony packet, duplicate nonce, inna sesja/digest |
| Run | Osobny lokalny owner approval dla exact zadania w jednym Core; brak mobilnego approve endpointu | Mobilne WRITE/EXEC/GitHub/koszt albo fałszywe permission |
| Evidence | Ten sam task ID, preview digest, source, receipt i niezależny lokalny readback | Syntetyczny receipt przedstawiony jako LIVE |
| STOP | Zakres tylko własnego zadania, trwałe potwierdzenie; UNKNOWN pozostaje UNKNOWN | STOP jako retry lub odtworzenie niepewnego efektu |
| Revocation | Odcięcie sesji/rotacja key/restart odrzucają stary token; stary task ma host reconciliation | Automatyczny retry POST po lost ACK/401/restart |
| Wi-Fi i LTE | Cała ścieżka na obu sieciach; zaniki po POST i niezależny GET readback | Sam Tailscale Connected albo pojedynczy screenshot |

Obecne źródła Kotlin mają TLS1.3, `retryOnConnectionFailure(false)`, brak
redirectów, fresh proofs, obsługę UNKNOWN i unieważnienie sesji. To fakty
o kodzie; bez kompilacji/JVM i fizycznego testu nie potwierdzają działania
na Android15/HyperOS2. Zestawy Python/mobile/wire/native w raporcie A17
sprawdzają kontrakty i izolowany host, nie telefon.

`ANDROID_E2E_VERIFIED` wolno nadać dopiero po pełnym odbiorze. Muse LIVE,
GitHub WRITE i produkcyjna certyfikacja Core pozostają osobnymi bramkami.
