# AIOA Cosmic4 — rzeczywisty APK,2026-11-03

## Dostarczony plik

- Linux: `/home/l/Downloads/aioa apk/AIOA-Cosmic-4.0.0-debug-6e018c8.apk`
- Xiaomi: `/sdcard/Download/AIOA-Cosmic-4.0.0-debug-6e018c8.apk` — kopia sprawdzona SHA-256.
- SHA-256: `853857703e479fa4528936142725bd0afea61edaf41f0105452095d7608206f9`
- Rozmiar:12113711B, poniżej limitu128MiB.
- Źródło APK: `6e018c877d518c2ab3f16c312cccecc80ac69080`.
- Pakiet: `eu.sparkhat.aioa.companion.cosmic4`, versionCode400, versionName4.0.0-cosmic.
- Certyfikat APK SHA-256: `3aa33eda63d3516010ddbf0fe0ff8de6b6dab6f6fc48088ee2592bde3b627bc4`.
- Podpis trwały: prywatny PKCS12 i hasło poza Git, kopia w chronionych Secrets CI. Nie jest generowany ponownie przy retry. Sekretów brak w APK i publicznych artefaktach.

## Faktycznie wykonane kontrole

[GitHub Actions41688400577](https://github.com/luciferprosun/AIOA-spArkHAT/actions/runs/41688400577): **SUCCESS**.

- Rzeczywiste `testCosmic4UnitTest`:76 PASS,0 failure/skip.
- Rzeczywisty `lintCosmic4`:0 errors.
- Rzeczywisty `assembleCosmic4`:PASS.
- Runner/JDK17/SDK36/Gradle8.13/source/workflow/signature/artifact readback:PASS, istniejący zatwierdzony profil DEBUG_UBUNTU22_V1.
- Niezależny host: hash ZIP zgodny z metadanymi GitHub, CRC/nazwy/zawartość; SHA APK; aapt package/version/SDK/permissions/manifest; apksigner API26–32 i ten sam certyfikat. CI dodatkowo użyło build-tools35.
- Kotlin/JVM przed CI:73 PASS; Python:177 PASS; JavaScript:29 PASS; targeted pairing:24 PASS.128-reconnect endurance pozostaje NOT_COMPLETED, bez deklaracji PASS.
- Niezależny code review:PASS dla dokładnego buildu.
- Nie wykonano merge, nie zmieniono konfiguracji CodeQL, nie uruchomiono płatnych modeli. Model calls0. Artefakt CI ma retencję1dzień; kopia lokalna pozostaje.

## Zachowanie oryginału

Cosmic0.3.0 pozostaje zainstalowany pod dotychczasowym pakietem. Jego APK zachował SHA-256 `43ca92f447f89a31d37ddd91481ff2d627a5921a10798db002a3922294d7a537`. Wszystkie11 wpisów inwentarza danych aplikacji są identyczne przed/po próbie instalacji. Zaszyfrowana kopia danych została niezależnie odszyfrowana i sprawdzona w prywatnym workspace właściciela. Nie eksportowano klucza Android Keystore, nie usunięto aplikacji ani danych, nie odwołano starego zaufania.

Nowy pakiet jest konieczny po utracie prywatnego podpisu starego APK. Zachowanie starej instalacji nie oznacza przeniesienia jej nieeksportowalnego klucza. Cosmic4 wytwarza własną tożsamość i uzyskuje zgodę tego samego Core. To nie jest drugi Core ani nowe repozytorium.

## Stan fizycznego wdrożenia

- `APK_BUILD`:PASS.
- `APK_INDEPENDENT_VERIFY`:PASS.
- `ORIGINAL_DATA_PRESERVED`:PASS w wykonanym porównaniu.
- `USB_INSTALL`:BLOCKED — rzeczywisty Android zwrócił `INSTALL_FAILED_USER_RESTRICTED: Install canceled by user`; nowy pakiet nie został zainstalowany podczas tej próby. Bez automatycznego retry.
- `CORE_OWNER_ADMISSION`:EXPIRED — istniejący Native Core odmawia; sesja Linuxc2 jest nieaktywna, ekran logowania aktywny. Wymagana rzeczywista sesja lokalna/PolicyKit.
- `COSMIC4_PAIRING`:NOT_RUN, nie PASS.
- `COSMIC4_SIGNED_STATUS`:NOT_RUN, nie PASS.
- `COSMIC4_RECONNECT`:NOT_RUN, nie PASS.

LinuxCore pozostaje przy5fae31002031ab0eb0aa94b9e57e8f6fbb3b6e01 i zachowanym katalogu stanu. Przygotowany launcher odnowienia sprawdza rzeczywistą aktywną sesję i dokładny poprzedni PID/czas startu/source, korzysta z PolicyKit i nie zatrzymuje portów4314/4316/4321. Nie używa fikcyjnego ownera ani `approved=True`.

## Dokładne czynności właściciela

1. Na Xiaomi otworzyć Pobrane i powyższy APK, zaakceptować zwykłą instalację **AIOA Cosmic4.0**. Alternatywnie umożliwić instalację USB. Starego AIOA nie odinstalowywać.
2. Odblokować lokalny ekran Linuxa. Jeżeli pojawi się PolicyKit, zatwierdzić hasłem wyłącznie w systemowym oknie.
3. Pozostawić telefon połączony przez USB oraz Tailscale online. Wykonawca zweryfikuje zainstalowane bajty APK i nowy proof klucza, przeniesie publiczny host z oryginału i przeprowadzi istniejący protokół Core, bez ponowień niepewnych efektów.

Przygotowane publiczne dane transferu, backup, klucz APK i dowody znajdują się w prywatnych katalogach właściciela. Do APK ani Git nie włożono gotowej sesji lub tokenu. Nie utworzono invite na zapas, więc nie ma wygasającego kodu oczekującego w raporcie.

## Dokończenie i rollback

Po uzyskaniu obu zgód systemowych: odczyt tożsamości nowej instalacji → prawdziwy invite → pojedynczy BEGIN przez istniejący ViewModel → porównanie dokładnego urządzenia/request digest/SAS przez USB i Core → istniejący owner approval → pojedynczy COMPLETE → porównanie tego samego świeżego proof statusu w aplikacji i Core → restart/reconnect bez QR.

Rollback zachowuje oryginał i jego dane. Nie przywracać starego snapshotu Core, nie czyścić danych i nie powtarzać APPROVE/BEGIN/COMPLETE po UNKNOWN. Nową instalację można pozostawić nieaktywną do odczytu stanu. Do czasu odbioru fizycznego nie deklarować automatycznego sparowania.

Aktualny Native profil obsługuje podpisany status READ. Gotowy APK ani ta bramka nie oznaczają Muse LIVE, GitHub WRITE lub AGENT_READY.

Źródła ograniczeń platformy: [Android signing](https://developer.android.com/studio/publish/app-signing), [Android Keystore](https://developer.android.com/privacy-and-security/keystore), [Android applicationId](https://developer.android.com/build/configure-app-module).
