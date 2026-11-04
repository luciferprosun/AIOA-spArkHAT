# Cosmic4 — rzeczywisty odbiór Android/Linux, 2026-11-04

APK 4.1.0 zostało zainstalowane na Xiaomi przez `adb install -r`. To ten sam pakiet i signer; podpisany proof urządzenia oraz zapis parowania są identyczne przed i po aktualizacji. Nowy QR, uninstall, clear i migracja Keystore nie były potrzebne.

| Bramka | Dowód i wynik |
|---|---|
| APK_UPDATE_IN_PLACE | PASS; 400→401, 4.1.0-cosmic, faktyczny pull z telefonu identyczny z CI |
| KEYSTORE_AND_PAIRING_PRESERVED | PASS; ta sama publiczna tożsamość urządzenia i dokładnie ten sam PairingRecord po instalacji |
| ANDROID_RECONNECT / SIGNED_STATUS | PASS w pierwszym rzeczywistym przebiegu; podpis z aplikacji identyczny z journalem Core, bez enrollment |
| NATIVE_OWNER_ADMISSION | PASS; rzeczywisty PolicyKit, obecny PID 1236673, niezależny proces PPID1 |
| TLS / HOST IDENTITY | PASS; TLS1.3, CA i hostname, ten sam cert/pin i klucz hosta; metadane plików identyczne |
| LINUX_PANEL_READY | PASS; faktyczny Chrome, prywatny one-use bootstrap przez stdin/CDP pipe, HTTP200 i odczyt rejestru Core na ekranie |
| CURRENT_PHONE_FRESH_READBACK | Wymaga ręcznego odświeżenia po ostatnim restarcie; wcześniejszego PASS nie przedstawia się jako stale świeżego statusu |
| MUSE_LIVE_CHAT | BLOCKED_FRESH_PHONE_REQUEST_AND_EXACT_FINANCIAL_APPROVAL; 0 wywołań modelu |
| MISSION_READ | BLOCKED_NATIVE_WORKER_NOT_BOUND; nie uruchamiano P1 |
| DEMO_READY / AGENT_READY | BLOCKED / NOT_CLAIMED |

Źródło APK i działającego Native: `0b3f48ef0842833e17cf6bb79e8b72d44e7e7eee`. APK: `/home/l/Downloads/aioa apk/AIOA-Cosmic-4.1.0-debug-0b3f48e.apk`, SHA-256 `c88aa9c106b1f4464b66e9ef9ffc68eeaa85e4eda5d966f1ab1455713e23209e`. Pakiet `eu.sparkhat.aioa.companion.cosmic4`; cert SHA-256 `3aa33eda63d3516010ddbf0fe0ff8de6b6dab6f6fc48088ee2592bde3b627bc4`. Urządzenie `9496cfd6389338b30b4c79d2bde7bf9e22af16e3fd87078d29b649851eb4bf7a`. Native capsule `8048d43b4668bc458f8cf1752b71af8705adc48d6534e211e70b4d3373e1a665`.

Host działa z zamrożonego `/home/l/AIOA_LOCAL_WORKTREES/cosmic4-muse-native-20261103`, na `127.0.0.1:4317`, z istniejącym state `/home/l/.local/state/aioa-mobile-native-main-20261102`. Origin `https://l-1.tail8c781e.ts.net`; prywatny Tailscale Serve, bez Funnel. Nie zmieniano chronionych 4314/4316/4321, produkcyjnych sekretów ani uprawnień wykonawczych agenta.

Pierwszy nowy Native PID1233383 zakończył się kodem143 (TERM). Przyczyna zewnętrznego sygnału pozostaje UNKNOWN; proces był powiązany z sesją narzędziową. Log zachowano. Następny start wykonano jako oddzielny proces przez `Popen(start_new_session=True)`, z ponownym rzeczywistym PolicyKit. Baza, host/TLS keys, revocations i niepewne zapisy nie były cofane ani kasowane. Aktualny niezależny PID jest wskazany powyżej. Lokalny profil demonstracyjny ma godzinny lease operatora; jego wygaśnięcie nadal wymaga prawdziwego uwierzytelnienia, nie automatycznej zgody.

## Chrome — przyczyna i poprawka

Rzeczywisty probe bez logowania wykazał `about:blank` z `readyState=complete` przed załadowaniem HTTPS panelu. Stary pomocnik uznawał tę kartę za docelowy dokument. Poprawiono operator client: czeka na dokładny URL, origin, complete i secure context, dopiero potem wysyła jednorazowy POST. To zewnętrzny klient operatora z commitu `3e9f9f541697ecbed21d3bdd59930a0e77d42216`; działający host i APK pozostają zamrożone na0b3f48e. Nie zmieniano Native authority ani protokołu parowania.

RED: brak nowego warunku dokumentu, 2 błędy. GREEN: 4 testy lifecycle. [Pełne required CI klienta](https://github.com/luciferprosun/AIOA-spArkHAT/actions/runs/41756784319): Python3.11/3.12 po2705 testów, 0failures/errors, 5 jawnie dozwolonych opcjonalnych skipów; dodatkowo po105 NonZero PASS. Packaging, rzeczywisty networkless Chrome wykorzystujący ten sam warunek dokumentu, architecture, Ruff, AST i command discovery PASS. [Build Androida](https://github.com/luciferprosun/AIOA-spArkHAT/actions/runs/41720343414) pozostaje82 testy/0fail/0skip/lint0/assemble/signature PASS.

Po restarcie jeden zwykły start panelu zakończył się ogólnym błędem, bez READY. Nie uznano go za sukces. Bieżące otwarcie wykonano tą samą funkcją produkcyjną z prywatnym, bezpiecznym śladem metod CDP: oczekiwanie na właściwy dokument, POST200, reload i faktyczny panel. Ślad nie zawiera delivery ani wyrażeń fetch. Root cause tej dodatkowej odmowy pozostaje UNKNOWN. Jeden diagnostyczny cleanup własnego tymczasowego profilu zgłosił ENOTEMPTY; nie przedstawiono go jako udanego testu. Nie wyłączano sandboxa ani TLS.

## Wiadomość i następny krok właściciela

Core otrzymał rzeczywistą wiadomość z Androida: request `e4304c88a68b4c13aad0bece1c522de5`, thread `6b9e092798b7477ba6930c3bc116cbd6`. Nie wydano dla niej zgody finansowej; po upływie terminu wynik to `FAILED / CHAT_APPROVAL_EXPIRED`, receipt modelu brak, model_calls=0. To odmowa bez kosztu, nie Muse LIVE. Nie ponowiono tego POST ani nie usunięto pending ID przez ADB.

Właściciel powinien zostawić AIOA na ekranie telefonu, odświeżyć podpisany stan, w Czacie nacisnąć „Sprawdź wynik — bez ponowienia”, wpisać nowe pytanie oraz nacisnąć Wyślij. Potem wykonawca odczyta dokładny nowy request/review digest i otworzy systemowe potwierdzenie jednej próby<=0.05USD w istniejącym prywatnym kanale. Sama zgoda na kodowanie, PolicyKit startu hosta i stary budżet Nebius nie są zgodą na płatny Meta request. Obecnie nie ma świeżego pytania ani podstaw do uruchomienia testu płatnego.

Ponowne otwarcie panelu, dopóki Native ma ważne admission:

```bash
cd /home/l/AIOA_LOCAL_WORKTREES/cosmic4-muse-chat-20261103
python3 -B -m runtime.webapp --mobile-operator console --state-dir /home/l/.local/state/aioa-mobile-native-main-20261102
```

Rollback nie oznacza cofania SQLite lub usuwania UNKNOWN. W razie potrzeby zakończyć wyłącznie rozpoznany własny Native i uruchomić wcześniej sprawdzony kod na tym samym state z rzeczywistym PolicyKit. Klienta nie odinstalowywać ani nie downgrade; ewentualny rollback aplikacji wymaga aktualizacji z wyższym versionCode i tym samym signerem.

Prywatne dowody: `/home/l/projects/AIOA_META_CHAT_PRIVATE_20261103/PHYSICAL_20261104_te5bvtyo` — PHONE_BEFORE_VERIFIED, PHONE_UPDATE_VERIFIED, REAL_ANDROID_RECONNECT_VERIFIED, NATIVE_ROLLOUT_VERIFIED, CURRENT_PHYSICAL_HANDOFF, aktualny detached log, host proofs, publiczne odczyty Core/aplikacji oraz kontrolowane zrzuty panelu Chrome. Błędny jednorazowy zrzut innej aplikacji usunięto z lokalnego katalogu i telefonu; nie użyto go w dowodach. Dalsza diagnostyka odrzuca niezgodne aktywne okno i zachowuje tylko elementy AIOA. Nie kopiowano kluczy prywatnych, bearerów ani Meta key do raportów.

PR40 pozostaje draft, bez merge do main. Nowy APK nie był potrzebny do poprawki operator client. Końcowy rezultat tego wznowienia: rzeczywista aktualizacja i zachowane połączenie, płatny czat nadal czeka na dokładną interakcję właściciela.
