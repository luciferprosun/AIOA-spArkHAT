# Cosmic4 — rzeczywisty odbiór Android/Linux, 2026-11-04

## Zakończony rzeczywisty test Muse LIVE — 2026-11-04

**P0_CHAT_ACCEPTANCE / CHAT_READY: PASS w lokalnym profilu demonstracyjnym.** Telefon wysłał prawdziwe pytanie. Właściciel osobno potwierdził koszt w lokalnym oknie, Core wydał i skonsumował exact warrant, a Meta odpowiedziało przez rzeczywiste API. Następnie telefon wykonał podpisany GET wyniku i rozmowy; oba SHA danych odpowiadają dokładnie odczytowi Core. Właściciel potwierdził odebranie odpowiedzi. Ten sam wynik i receipt zostały wyświetlone w rzeczywistym Chrome na Linuxie.

- Request `89c750cf10f643798858a60de5fa7aaf`; task `chat-89c750cf10f643798858a60de5fa7aaf`; thread `6b9e092798b7477ba6930c3bc116cbd6`.
- Stan `SUCCEEDED`, actor `ANDROID`, model potwierdzony przez API: `muse-spark-1.3`, provider `meta_model_api`, environment `META_API_LIVE_VERIFIED`, fallback=false.
- Dokładnie 1 próba i 1 model_call. Użycie:229 prompt +301 completion =530 tokenów.
- Estymata użycia `0.0015655 USD`, **nie faktura**. Zatwierdzony limit0.05USD; konserwatywna rezerwacja/rozliczenie governor oparte na bound0.00392975USD, bez podnoszenia globalnego limitu.
- SHA-256 odpowiedzi `7f3bbcbb075fdcd54d5674bc400f4f548aa9d01fe1ca377a361c9ae48d2e0b27` — niezależnie przeliczone na hoście i zgodne z receipt. Odpowiedź: „Stan Core: ADMITTED.”
- Review digest `aa91682cdfb4e64700514323c3063e9eb600c2a2ae0079a2b105b83fe291d0b0`; warrant `sha256:f4e4c9097ea3be219b9c33ea5b5e0a68cb89284a92555024b02d6e9f74a6b897`; policy epoch2. Warrant dotyczył wyłącznie tej jednej wiadomości.
- Podpisany odczyt aplikacji: `GET /api/mobile/v2/chat/requests/89c750cf10f643798858a60de5fa7aaf`, SHA danych `aa2149c6b37be7f344e308e4ff514f660bb2ea03149f8d9cc0eccc8b1d2c3fe0`; odczyt thread `a614dadddcc9b614341829c833e7a63ecfbda677edadd51456b9b5b725d5b24c`. Podpis hosta zweryfikowany; Core zachował identyczne obserwacje. Odczyty nie zwiększyły liczby wywołań modelu.
- Linux: rzeczywisty panel pokazał tę samą rozmowę, odpowiedź, SUCCEEDED, source0b3f48e i receipt SHA. Prywatny kontrolowany zrzut `LINUX_REAL_MUSE_CHAT_OWN_WINDOW.png`.

**Granice:** DEMO_READY dotyczy tego odebranego demonstratora czatu, nie produkcyjnego Core M12 ani pełnego agenta. `AGENT_READY` nie jest deklarowane. `MISSION_READ=BLOCKED_NATIVE_WORKER_NOT_BOUND`; Native profile ma run/native_execute/github_write=false i nie wiąże Workera wykonawczego. Nie uruchamiano kolejnej płatnej misji ani Github WRITE.

Sesja operatora Native jest ograniczona do jednej godziny od rzeczywistego admission; jej wygaśnięcie blokuje API i wymaga ponownej autentycznej autoryzacji. Tekst czatu pozostaje w pamięci maksymalnie15minut; Save knowledge=OFF, trwałe są metadane i receipt. To ograniczenia bieżącego profilu, nie obietnica stałego działania bez obsługi właściciela. Panel może chwilowo pokazywać BUSY przy nakładających się odczytach urządzeń i czatu; nie wykonuje z tego powodu nowego płatnego POST. Jedna odmowa startu Chrome oraz cleanup ENOTEMPTY pozostają opisane niżej jako nieudane próby, nie PASS. Wideo nie było nagrywane w tym wznowieniu.

Dowody prywatne: `REAL_MUSE_LIVE_BACKEND_VERIFIED.json`, `REAL_ANDROID_MUSE_SIGNED_READBACK.json`, `FINAL_REAL_META_ANDROID_LINUX_ACCEPTANCE.json`, kontrolowany zrzut Linuxa. Dane powyżej dotyczą konkretnego rzeczywistego testu; historyczny odczyt nie nadaje nowej authority. Każde następne płatne pytanie wymaga nowej exact zgody. Nie zakłada się aktualnego salda Meta na podstawie tego jednego sukcesu.

## Wcześniejszy odbiór przed zgodą na Muse — zapis historyczny


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
