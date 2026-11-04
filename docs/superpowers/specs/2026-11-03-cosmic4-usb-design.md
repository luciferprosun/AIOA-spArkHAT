# Cosmic4 — bezstratne zachowanie starej instalacji i wdrożenie przez USB

Właściciel polecił zbudować APK4.0, zachować wszystkie dane i przygotować automatycznie połączoną instalację na podłączonym Xiaomi. To zastępuje wcześniejszy zakaz utworzenia osobnego pakietu. Nie zastępuje Core, istniejących kontroli authority ani zakazu wkładania sekretów do APK. Wykonanie zlecono bez kolejnej rundy pytań projektowych; decyzje poniżej należą do wykonawcy, nie są domniemaniem wcześniejszej certyfikacji.

## Wybrana droga i ograniczenie Androida

1. Oryginalny podpis APK0.3.0 nie został odzyskany. APK oraz certyfikat publiczny nie zawierają zastępującego go klucza prywatnego. Bez niego normalny update tego samego pakietu jest niemożliwy.
2. Nowy wariant tego samego projektu: applicationId `eu.sparkhat.aioa.companion.cosmic4`, versionCode400, versionName `4.0.0-cosmic`, etykieta `AIOA Cosmic 4.0`. Oryginalny pakiet0.3.0 pozostaje zainstalowany ze wszystkimi danymi i swoim Android Keystore.
3. Prywatnego klucza transportowego starego UID nie eksportujemy ani nie udajemy, że da się przenieść go do nowego UID. V4 generuje własny klucz w Android Keystore. Publiczna konfiguracja tego samego hosta i niesekretne wskazówki historii są przenoszone przez zweryfikowane USB; stare pending ID trafiają do archiwum, nie do ponowienia.
4. Nową tożsamość rejestruje ten sam Core, przez istniejące invite/begin/owner approve/complete/status. Właściciel zlecił automatyczne przygotowanie tej konkretnej instalacji na podłączonym Xiaomi. Delegowane narzędzie operatora musi nadal uzyskać prawdziwy principal aktualnego lokalnego operatora, porównać dokładny nowy SPKI/request digest/SAS po USB i niezależnym odczycie Core. Model, fixture, flagi i dane importu nie są owner authority. Jeśli Core lub OS wymaga interakcji człowieka, operacja zatrzymuje się na tej bramce.

Alternatywy odrzucone: ponowne generowanie „tego samego” zgubionego klucza; uninstall/clear-data starej aplikacji; eksport sprzętowego Keystore; dołączenie tokenu, klucza lub gotowej sesji do dystrybuowanego APK. Nowy pakiet wymaga nowej prawdziwej zgody Core; samo importowanie konfiguracji hosta jej nie zastępuje.

## Zachowanie danych

- Sprawdzić dokładny stary APK i publiczne powiązanie; zapisać inwentarz/hash trwałych danych aplikacji i zaszyfrowany backup niesprzętowych danych poza Git. Starego pakietu, jego danych i kluczy nie usuwać i nie zmieniać.
- Zachować istniejący Core/store/host SPKI/TLS/Tailscale i wszystkie dotychczasowe approvals/history. Nowe zaufanie jest osobnym audytowanym wpisem dla tego samego fizycznego telefonu, nie nadpisaniem starego rekordu.
- Żadne stare pending/UNKNOWN/receipt nie staje się nową operacją lub pozwoleniem. Pozostają w starej aplikacji/Core; eksportowane opaque ID są w nowej aplikacji jedynie archiwalną wskazówką.
- Pełna prywatna tożsamość pozostaje w oryginalnej aplikacji. Nie deklarować, że została skopiowana. W4 wszystkie przeniesione dane i nowe authority mają osobny, sprawdzony readback.

## Aplikacja i USB

Wykorzystać istniejące CosmicApp/MissionViewModel/MobileClient/PairingProtocol/TrustedHostStore/SessionRecovery. Nie tworzyć drugiego runtime. Dodać mały, wersjonowany kontrakt USB:

- Provider wyłącznie w source set cosmic4, wyłącznie debuggable i prawdziwy Binder UID2000(shell). Inne UID, root, wariant lub pakiet odmawiają. Brak dostępu do plików przez URI i brak operacji approval.
- `identity`: publiczny SPKI i podpis świeżego nonce hosta, identyfikator pakietu/certyfikatu i źródła. Nie zwraca klucza prywatnego ani bearerów.
- `stage`: ściśle ograniczony publiczny transferV1: flow ID, docelowy SPKI, publiczne zaufane metadata hosta, jego świeże podpisane invite, oczekiwana tożsamość instalacji i niesekretne archiwalne ID. Nie zawiera tokenów/sesji/kodów enrollment.
- `state`: publiczny stan procesu/pairing i metadata podpisanego odczytu, bez sesyjnego credential. Historyczne lub po-restartowe dane nie są fresh.
- Provider tylko etapuje dane. Istniejący ViewModel wykonuje flow; marker STARTED musi trwale poprzedzać pojedynczy BEGIN. Duplikat tego samego transferu daje readback; zmieniony, wygasły lub obcy transfer odmawia. Restart/ACK loss pozostają UNKNOWN bez ponowienia BEGIN/COMPLETE/APPROVE.
- Host pomocniczy używa przypiętego serialu USB, weryfikuje certyfikat/SHA zainstalowanego nowego APK i challenge proof nowego klucza, następnie porównuje prawdziwy pending Core z publicznym stanem aplikacji. Approval tylko przez istniejący prywatny socket SO_PEERCRED + żywy operator Core. Bez obchodzenia PolicyKit/expiry/revocation.
- Po completion istniejący client pobiera podpisany status. Metadata data_sha256/source/capsule/device/issued_at z faktycznie zweryfikowanej odpowiedzi są porównywane z niezależnym podpisanym odczytem w Core. Screenshot i restart aplikacji stanowią osobną weryfikację.

## Trwały podpis i build

- Jednorazowo utworzyć nowy prywatny podpis Cosmic4, zachować poza Git w katalogu właściciela0700, pliki0600, silne hasło. Nie regenerować przy retry. Publiczny fingerprint przypiąć w jawnym kontrakcie kanału.
- Zabezpieczyć kopię lokalną i chroniony materiał do ponownego podpisywania w GitHub Actions Secrets. Nie drukować wartości i nie publikować keystore w publicznym artefakcie.
- Zachować domyślny kanał aktualizacji oryginalnego pakietu i jego wymagany certyfikat75a539… bez osłabienia. Nowy kanał `COSMIC4_USB_V1` ma rozłączny manifest wejść, pakiet, wersję i certyfikat; oryginalny i nowy artefakt nigdy nie są akceptowane zamiennie.
- Użyć istniejącego zarejestrowanego workflow android-manual-build.yml z tej gałęzi, tego samego sprawdzonego buildera i dodatkowego, ściśle ograniczonego kanału dla dokładnej gałęzi/owner actor/SHA/hash workflow. Nie merge main, nie drugi system kwalifikacji. STRICT i zatwierdzony wyjątek DEBUG Ubuntu22 pozostają bez zmian.
- Standardowy bezpłatny runner publicznego repo;35min na run,128MiB, retencja1dzień. Brak płatnych API, lokalnego wielkiego SDK/emulatora, nowych licencji lub zmian CodeQL settings.
- Rzeczywiste taski Gradle: testCosmic4UnitTest, lintCosmic4, assembleCosmic4; rzeczywisty aapt/apksigner, fingerprint, SHA-256 i package/version. Każdy retry dopiero po rozpoznaniu przyczyny/poprawce. Fixture/JVM nie zastępują tego buildu.

## Odbiór i rollback

Kod/review/regresje → dokładny build → niezależna kontrola APK → instalacja obok0.3.0 → kontrola starego APK/danych → provisionUSB przez rzeczywisty Core → świeży podpisany status przyjęty w aplikacji i zgodny odczyt niezależny → zamknięcie i ponowne uruchomienie bez QR.

Odbiór nie włącza Muse LIVE, WRITE/EXEC ani wydatków. Native obecnie pozostaje profilem READ/statusu; każdy niedostępny element UI wyjaśnia przyczynę. Nie oznaczać AGENT_READY.

Rollback: oryginalna aplikacja i jej dane pozostają dostępne przez cały etap. W razie niepewnego nowego flow zatrzymać automatyzację i wykonać tylko readback. Nie usuwać oryginału, nie odwoływać starego zaufania i nie cofać store snapshotem. Zakończenie ma dostarczyć APK4.0, SHA/cert/source, raport instalacji/provisioningu oraz dokładnie nazwane ograniczenia.

## Źródła

- https://developer.android.com/studio/publish/app-signing — utrata własnego podpisu blokuje zwykły update.
- https://developer.android.com/build/configure-app-module — nowy applicationId to odrębna instalacja przy tym samym projekcie.
- https://developer.android.com/privacy-and-security/keystore — materiał klucza pozostaje nieeksportowalny.
- https://developer.android.com/build/build-variants — dodatkowy build type z applicationIdSuffix.
- https://cli.github.com/manual/gh_workflow_run — dispatch istniejącego workflow na wskazanym ref.
