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

Cosmic0.3.0 pozostaje zainstalowany pod dotychczasowym pakietem. Jego APK zachował SHA-256 `43ca92f447f89a31d37ddd91481ff2d627a5921a10798db002a3922294d7a537`. Wszystkie11 wpisów inwentarza danych aplikacji są identyczne także po rzeczywistej instalacji Cosmic4 i teście restartu; ponownie sprawdzono2026-11-03T18:31:15UTC. Zaszyfrowana kopia danych została niezależnie odszyfrowana i sprawdzona w prywatnym workspace właściciela. Nie eksportowano klucza Android Keystore, nie usunięto aplikacji ani danych, nie odwołano starego zaufania.

Nowy pakiet jest konieczny po utracie prywatnego podpisu starego APK. Zachowanie starej instalacji nie oznacza przeniesienia jej nieeksportowalnego klucza. Cosmic4 wytwarza własną tożsamość i uzyskuje zgodę tego samego Core. To nie jest drugi Core ani nowe repozytorium.

## Stan fizycznego wdrożenia

- `APK_BUILD`:PASS.
- `APK_INDEPENDENT_VERIFY`:PASS.
- `ORIGINAL_DATA_PRESERVED`:PASS w wykonanym porównaniu.
- `ANDROID_INSTALL`:PASS — rzeczywista instalacja została później potwierdzona przez ADB. Bajty zainstalowanego APK są identyczne z niezależnie zweryfikowanym artefaktem6e018c8. Wcześniejsza odmowa USB `INSTALL_FAILED_USER_RESTRICTED` pozostaje historycznym dowodem; nie powtarzano jej automatycznie.
- `CORE_OWNER_ADMISSION`:PASS — po odblokowaniu Linuxa rzeczywisty PolicyKit uwierzytelnił lokalnego operatora; Native PID1178571. Ten sam source5fae310, capsule, host/TLS, store i nieodwołane oryginalne urządzenie zostały niezależnie sprawdzone. Porty4314/4316/4321 bez zmian.
- `COSMIC4_PAIRING`:PASS — telefon i ten sam Core przechowują identyczne request ID/digest oraz stan COMPLETED; urządzenie jest zaufane i nieodwołane.
- `COSMIC4_SIGNED_STATUS`:PASS —2026-11-03T18:30:35UTC aplikacja przyjęła świeży podpisany status. Podpis ECDSA, device ID, session, nonce, source/capsule i data SHA sprawdzono niezależnie; dokładnie ten sam proof/signature występuje w bieżącym Core.
- `COSMIC4_RECONNECT`:PASS — pojedynczy force-stop i start wyłącznie Cosmic4 spowodował automatyczne połączenie oraz rotację sesji. Ten sam klucz i rekord parowania; zero nowego QR, BEGIN i owner approval. Lista żądań Core nie zmieniła się.

LinuxCore pozostaje przy5fae31002031ab0eb0aa94b9e57e8f6fbb3b6e01 i zachowanym katalogu stanu. Przygotowany launcher odnowienia sprawdza rzeczywistą aktywną sesję i dokładny poprzedni PID/czas startu/source, korzysta z PolicyKit i nie zatrzymuje portów4314/4316/4321. Nie używa fikcyjnego ownera ani `approved=True`.

## Bieżąca obsługa

Aplikacja4.0 jest zainstalowana i sparowana. Nie instalować ponownie ani nie tworzyć nowego QR dla tego odbioru. Zachować Tailscale online i działający Linux Core. Po wygaśnięciu krótkiego dowodu statusu użyć „Odśwież podpisany stan”; wygaśnięcie dowodu nie usuwa trwałego parowania.

Przy sprawdzeniu telefon miał już prawdziwe zakończone parowanie. Przygotowanego helpera PROVISION_01 nie uruchamiano, nie generowano dodatkowego invite i nie powtarzano BEGIN/APPROVE/COMPLETE. Akceptację wykonano odczytem istniejącego stanu i jednym kontrolowanym restartem klienta.

Prywatne dowody: `CURRENT_PAIRING_VERIFIED.json`, `PRE_RESTART_HISTORICAL_STATUS_VERIFIED.json`, `RECONNECT_ACCEPTANCE_VERIFIED.json`, `ORIGINAL_PRESERVATION_AFTER_REAL_INSTALL.json` w katalogu `/home/l/projects/AIOA_COSMIC4_PRIVATE_20261103`. Bez bearerów i kluczy prywatnych w raporcie/Git.

## Dokończenie i rollback

Odbiór fizyczny parowania, statusu i reconnect zakończony PASS. Nie ma pozostałego wymogu instalacji lub nowej zgody na parowanie. Brak sieci i revocation mają pokrycie regresyjne; w tym fizycznym teście nie wyłączano sieci ani nie odwoływano działającego urządzenia.

Rollback zachowuje oryginał i jego dane. Nie przywracać starego snapshotu Core, nie czyścić danych i nie powtarzać APPROVE/BEGIN/COMPLETE po UNKNOWN. Nie odwołano starego ani nowego urządzenia.

Aktualny Native profil obsługuje podpisany status READ. Gotowy APK ani ta bramka nie oznaczają Muse LIVE, GitHub WRITE lub AGENT_READY.

Źródła ograniczeń platformy: [Android signing](https://developer.android.com/studio/publish/app-signing), [Android Keystore](https://developer.android.com/privacy-and-security/keystore), [Android applicationId](https://developer.android.com/build/configure-app-module).

Aktualizacja narzędzia hosta po realnym buildzie:12 targeted Python tests PASS. Dla nowej pustej instalacji helper wymusza świeży lifecycle Activity przed STAGE, żeby ręczne otwarcie aplikacji po instalacji nie ominęło ON_RESUME. Najpierw odmawia przy dowolnym pending/UNKNOWN/powiązaniu i weryfikuje utrzymanie tego samego klucza. Nie wymaga to nowego APK; kod Androida/bajty artefaktu pozostają dokładnie6e018c8.
