# Xiaomi 13T Pro / Android15 / HyperOS2 — poranny checklist

**Teraz: NO-GO dla instalacji/parowania.** N1 dostarcza źródła i podpisany fixture
hosta; brak nowego APK, zweryfikowanego host TLS i produkcyjnego portu enrollment.
Samo uruchomienie Tailscale nie usuwa tych blokad. Nie zastępuj starego APK0.1.0
nowym plikiem o nieudowodnionym pochodzeniu lub innym podpisie.

1. Na telefonie zainstaluj oficjalny Tailscale, zaloguj się do właściwego tailnetu
   i sprawdź **Connected**; porównaj nowy telefon z hostem w zaufanym lokalnym
   kanale. Nie kopiuj tożsamości AGM. Instrukcja: [Tailscale Android](https://tailscale.com/docs/install/android).
2. Na Linuxie wykonaj pasywny doctor:
   `python3 -B -m runtime.mobile_gateway.doctor` z katalogu TARGET.
   Exit2/BLOCKED jest oczekiwany. Opcjonalne read-only `tailscale --socket <własny-socket>
   status --json` i `tailscale --socket <własny-socket> serve status --json` oglądaj
   lokalnie; nie publikuj ich surowego wyjścia. Doctor przyjmuje na stdin `{status,serve}`
   przez `--tailscale-stdin` i wypisuje tylko zredagowaną obserwację, nigdy potwierdzenie
   nowego Xiaomi. Nie uruchamiaj `serve`, `up`, `down`, reset ani zmiany ACL.
3. Wybierz dokładny pełny HTTPS origin Linuxa, bez ścieżki i credentials.
   `127.0.0.1` na Xiaomi oznacza telefon. Potrzebna jest osobno zatwierdzona
   konfiguracja edge oraz **implementacja natywnego qualified-edge binding** do
   istniejącego WebRuntimeService; N1 udostępnia tylko fixture i celowo blokuje
   produkcyjny enrollment. [Serve](https://tailscale.com/docs/features/tailscale-serve)
   nie jest automatycznie włączany przez AIOA. Bez aktualnego certyfikatu,
   TLS1.3/hostname/systemCA i zgodnych niezależnych pinów pozostań przy NO-GO.
4. Zbuduj źródła na kwalifikowanej maszynie według `ANDROID_BUILD_HANDOFF.md`;
   najpierw testy JVM/lint, merged manifest, podpis i SHA. Dopiero po decyzji
   właściciela instaluj zweryfikowany APK; sprawdź ten sam pakiet i legalną ciągłość
   podpisu aktualizacji. Inny podpis wymaga świadomej reinstalacji i nowej tożsamości.
5. W AIOA wpisz HTTPS origin, **TLS cert SPKI pin** i osobno **host identity P-256 SPKI**
   otrzymany bezpiecznie z hosta, nigdy od niezweryfikowanego endpointu.
   Porównaj nowy publiczny klucz telefonu z ekranem operatora na Linuxie.
   Po native owner admission operator może wydać dokładnie prebound jednorazowy kod
   transportowy z TTL≤5min; w obecnym N1 taki kod istnieje wyłącznie w testach.
6. Przed ujawnieniem kodu/tokenu klient musi zweryfikować świeży podpis hosta,
   challenge, origin, source/capsule i capabilities. Bez ich zgodności STOP.
   Transport nie nadaje owner warrant ani PINNED; owner pozostaje NOT_BOUND.
7. Po poprawnym rzeczywistym enrollment sprawdź podpisany status → Preview
   jednego fixture → osobną dokładną zgodę Run w host Mission Control → Evidence.
   Porównaj taskID/digest/source/capsule i receipt. STOP sprawdź na drugiej własnej
   misji; stan UNKNOWN rozlicz na hoście, bez ponowienia POST. To nadal nie test
   płatnego Muse ani publicznego Chrome.
8. Wznów aplikację i pobierz świeży GET/readback; STALE/OFFLINE nie jest sukcesem.
   Następnie zmień Wi-Fi na LTE i ponów wyłącznie GET status/evidence, sprawdź
   revocation i odmowę starej sesji. Po process death token nie jest odzyskiwany,
   a nierozliczoną propozycję starej sesji obsługuje operator hosta.

Po expiry/odwołaniu sesji dostępny pozostaje jawny nowy enrollment. Znacznik
starej propozycji można przyciskiem „Zachowaj nierozliczony ID dla operatora”
przenieść do lokalnej listy ID po przeczytaniu potwierdzenia; nie jest to rozliczenie
Core, zgoda, STOP ani retry. UNKNOWN na hoście pozostaje UNKNOWN. Status ma jawne
strony do16 własnych zadań; „Starsze zadania” wykonuje podpisany GET, nie Run.

Nie są wymagane kontakty, SMS, lokalizacja, broad storage ani omijanie PIN.
Ustawienia oszczędzania baterii zmieniaj tylko po stwierdzonej utracie połączenia;
nazwy opcji HyperOS mogą się różnić. Nie akceptuj niewłaściwego certyfikatu.
Ochrona tożsamości klienta: [Android Keystore](https://developer.android.com/privacy-and-security/keystore),
[Network Security Configuration](https://developer.android.com/privacy-and-security/security-config).
