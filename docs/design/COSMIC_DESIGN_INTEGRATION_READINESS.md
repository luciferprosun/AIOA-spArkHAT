# Cosmic — gotowość integracji projektu i mapowanie
Aktualizacja Master: kontynuacja4960ba2 jest opisana w COSMIC_MASTER_CAPABILITY_MATRIX.md i COSMIC_MASTER_CODE_REVIEW.md. Poniższy audyt historyczny zachowano; Master zmienia muted na#AAB7D2 oraz uzupełnia komponenty i mapowanie stanów. Wynik realnego wdrożenia Linux i blokada aktualizacji Androida są w lokalnym CODEX_COSMIC_FINAL_IMPLEMENTATION.md. Dostęp MCP do Figmy(17ramek), Canvy(12stron znalezionego ID) i MagicPath ponownie potwierdzono; nie zmieniano źródeł projektowych ani kont.

Data kontroli: 2026-11-03. Tryb początkowy PREPARATION_ONLY; późniejsza wiadomość właściciela zezwala na lokalną implementację skórki i testy. Bez merge, płatnych operacji, zmian kluczy lub resetowania parowania.

## Fakty i zakres
- Repozytorium: luciferprosun/AIOA-spArkHAT (publiczne), zdalny main: bda9d3126150b7c44f94d923ed236e10de5dba59.
- Uruchomiony host: cosmic-one-tap-20261102, 11b1505730da3759f0e00091157416005ff196a0; nie zmieniono jego kodu ani stanu.
- Implementacja: istniejący odizolowany worktree cosmic-pairing-diagnostics-20261103; baza df1a13ece15f94cf19357f437dd54a73170087c0; branch feat/cosmic-design-system-20261103. Zastane nieśledzone .superpowers/ zachowane.
- Zatwierdzony kierunek: natywny Jetpack Compose i istniejący web/index.html. Te same MissionViewModel, MobileClient, istniejący transport operatora i jeden Core.
- Zainstalowany APK 0.3.0 oraz wcześniejsze fizyczne parowanie pozostają zachowane. Nie są dowodem przetestowania nowej skórki lub recovery 0.3.1 na telefonie.

## Środowisko Codexa
Codex CLI 0.166.0, /home/l/.local/bin/codex; instalacja standalone. Aktywny model konfiguracji gpt-6.1-sol, reasoning max. Znaleziono także aktywną instancję 0.165.0; żadnej nie zatrzymano ani nie aktualizowano. Odczytano wyłącznie bezpieczne pola konfiguracji, bez auth.json i wartości sekretów.
Konfiguracja CLI zawiera MCP chrome-devtools, nvidiaNemoClawDocs, nvidiaBuild. Nie wywoływano inferencji. Narzędzia zarządzanych aplikacji w tej sesji udostępniają dodatkowo Figmę, Canvę, MagicPath i GitHub. To odrębne źródło narzędzi od wpisów mcp_servers.

## Konektory — rzeczywiste wyniki
| Kontrola | Wynik | Dowód / ograniczenie |
|---|---|---|
| FIGMA_READ | PASS | Oficjalny MCP: create_session, get_metadata strony 0:1, get_design_context Home i Linux oraz Foundations; download_assets Home zwrócił eksport. Bez edycji pliku. |
| CANVA_READ | PASS dla projektu znalezionego na koncie | search_designs AIOA zwrócił DAHZ2xNq8Ig, AIOA Cosmic Mission Control; 12 stron 1920×1080, odczytano strony i richtexts. Podany skrót /d/BLrKSz_xqs7BDMg nie jest akceptowany przez get_design; nie utożsamiamy nierozwiązanego skrótu z ID bez dodatkowego dowodu. |
| MAGICPATH_READ przez MCP | PASS | Po ponownym odkryciu narzędzi istniejący plugin 2.0.0 udostępnił projekt 468340598617829376, jeden komponent ready-flood-7620 i trzy oryginalne pliki edytowalne. Nie instalowano drugiego MCP. |
| MAGICPATH_READ alternatywny | PASS — publiczny podgląd UX | designs.magicpath.ai/v1/ready-flood-7620 odpowiada rzeczywistemu komponentowi projektu, potwierdzonemu później MCP. Prototyp ma wyraźne etykiety PROTOTYP i pokazowego statusu. |
| GITHUB_READ | PASS | Połączony konektor odczytał repo oraz workflow main. Uprawnienia konta nie upoważniają do zapisu w tym etapie. |
| ANDROID_BUILD_ENV | FAIL | JDK17 i sam kompilator Kotlin dostępne; pełny zakwalifikowany SDK36/build-tools35/Gradle8.13 niepotwierdzony. Brak katalogu toolchain i jego pinu kwalifikacji. Dostępny RAM ok. 698 MiB, wymagany próg 1536 MiB; swap niemal pełny. |
| DESIGN_TO_CODE_MAPPING | READY dla Figmy i istniejących funkcji | Wszystkie 17 ramek przypisano poniżej. Eksport źródłowy MagicPath nie jest wymagany do natywnego Compose. |
| PAIRING_PRESERVED | BEZ ZMIAN | Host 4317, dane Core, AndroidKeyStore, TLS, Tailscale i zatwierdzenie telefonu nie są modyfikowane. |

MCP odczytuje Figmę, projekt Cosmic znaleziony na koncie Canva i dokładny projekt MagicPath. Ograniczenie identyfikacji dotyczy wyłącznie nierozwiązanego skrótu Canva. Dostęp do projektu i jego 12 plansz został rzeczywiście sprawdzony.

## Pełny inwentarz Figmy
Plik odRmVoOW86gDN3Gm15JKJe, jedna strona Page 1 (0:1). Poniższe ID pochodzą z odczytu, nie z założeń.
Ścieżka Android: clients/android/app/src/main/java/eu/sparkhat/aioa/companion/.
| ID | Ramka | Mapowanie Android / Linux | Rzeczywiste zachowanie |
|---|---|---|---|
| 1:85 | Cosmic Android — Home | CosmicScreen.kt / web/index.html overview | Stan sesji, zapisane zaufanie i historyczny czas odczytu odróżnione od bieżącej świeżości. |
| 1:105 | Cosmic Android — Chat | CosmicMissionPages.kt chat / panel Muse | Brak kontraktu czatu w native status-only; wyraźnie niedostępny, bez przykładowych odpowiedzi. |
| 1:125 | Cosmic Android — Misje | CosmicMissionPages.kt missions / panel missions | Lista i propozycje wyłącznie według podpisanych capabilities; bez sztucznych Orion/Lyra. |
| 1:145 | Cosmic Android — Critical | CosmicMissionPages.kt critical / panel critical | Bieżące zaufanie, zakres, istniejący STOP tylko dla właściwej misji; nie udziela uprawnień. |
| 1:165 | Cosmic Android — GitHub | CosmicMissionPages.kt repositories / panel repositories | Istniejące dowody Git, jeśli udostępnione; brak GitHub WRITE i wymyślonych repozytoriów. |
| 1:185 | Cosmic Android — Ustawienia | CosmicScreen.kt settings / panel settings | Zachowane jawne unieważnienie sesji i potwierdzane usunięcie lokalnego hosta. |
| 1:205 | Cosmic Linux — Mission Control | web/index.html, styles.css, mobile_devices_dom.js | Ten sam /devices i zaufany transport operatora; nawigacja nie tworzy nowej aplikacji. |
| 1:238 | Cosmic Foundations | wspólne cosmic.tokens.json | Konstelacje/misje, Muse/kreacja, Wormhole/połączenie, Critical/ochrona — język wizualny. |
| 2:2 | Canva Foundations / Cosmic Tokens | CosmicTheme.kt i styles.css | Odczytane wartości kolorów, spacing i skala typograficzna. |
| 2:31 | Canva Semantic States / UX | CosmicScreen.kt, CosmicMissionPages.kt i transport operatora | SIGNED, PENDING, OFFLINE, ERROR, PLANNED opisane tekstem; sam kolor nie jest dowodem. |
| 2:53 | Canva Navigation & User Flows | CosmicScreen.kt, istniejący mobile_devices_dom.js | Pięć głównych sekcji i dostęp do sekcji dodatkowych; niezależne przewijanie. |
| 6:2 | Devices / Pairing | istniejący CosmicPage devices / urządzenia Linux | Zachowane import/QR, potwierdzenie hosta, SAS, odczyt i recovery. |
| 6:22 | Approvals | CosmicMissionPages.kt approvals / Linux approvals | Android nie zatwierdza; Linux używa istniejącej dokładnej zgody urządzenia i SAS. |
| 6:42 | Mission Details | CosmicMissionPages.kt details / Linux missions | Tylko istniejące zadania, dowody, receipts i STOP; brak dowodu oznacza brak wykonania. |
| 6:62 | Activity & Logs | CosmicMissionPages.kt activity / Linux activity | Odczytane zdarzenia w bieżącym widoku; brak sfabrykowanej historii i eksportu. |
| 6:82 | Providers | CosmicMissionPages.kt providers / Linux providers | Odczyt istniejącego profilu, brak przełącznika uruchamiającego niezatwierdzoną inferencję. |
| 6:102 | Recovery & Errors | istniejące SessionRecovery.kt i CosmicPage recovery | Podpisany readback, brak ponowienia niepewnego POST, zachowany zapisany host. |

Figma nie ma zdefiniowanych variables dla Foundations: get_variable_defs zwrócił {}. Kolory odczytano z rzeczywistych właściwości w get_design_context; nie deklarujemy istniejącej biblioteki variables/Code Connect. Warstwy to ramki, tekst i prostokąty; obecność ramki nie dowodzi gotowego komponentu produkcyjnego.

## Canva — 12 plansz
ID DAHZ2xNq8Ig; 12 plansz 1920×1080. Treści odczytane z połączonego konta:
1. AIOA Cosmic Mission Control — system UI/UX Android i Linux.
2. Kosmos jako język interfejsu; paleta i znaczenia.
3. Typografia i siatka: Space Grotesk, Manrope, IBM Plex Mono; 4/8/16/24/32, dotyk ≥48 dp.
4. Home — dwa urządzenia, jeden status.
5. Muse — czat, LIVE/OFFLINE opisane jako planowane.
6. Misje — plan, zgoda, wykonanie, STOP jako planowane.
7. Critical — podpisany status i decyzje użytkownika.
8. GitHub — przykładowe repozytoria i WRITE planowany.
9. Ustawienia — połączenie i odzyskiwanie.
10. Linux — desktopowe Mission Control.
11. Komponenty — normalny, fokus, niedostępny, błąd, TalkBack/kontrast.
12. Plan przeniesienia tokenów, komponentów i regresji.
Indeks potwierdzono kolejnym odczytem richtexts osobno dla każdej z 12 stron; pełny zapis znajduje się w COSMIC_SOURCE_INVENTORY.json. Skrót dostarczony przez właściciela prowadzi w przeglądarce do logowania; sam jego związek z ID znalezionym przez MCP nadal nie jest potwierdzony.
MCP udostępnia richtexts i miniatury, ale nie potwierdzono odrębnego eksportu fontów/licencji/grafik. Nie rozpoczynano transakcji edycji tylko po to, by uzyskać podgląd.

## MagicPath
W publicznym podglądzie potwierdzono: nagłówek Cosmic Mission Control, podpis PROTOTYP, karty Linux signed-status/White Hole/Wormhole, nawigację Home/Chat/Misje/Critical/GitHub oraz Urządzenia/Zgody/Historia/Dostawcy/Ustawienia.
Status i funkcje to demonstracja UX, nie dowód komunikacji z Core. Nie kopiować bundla React do APK.
Oficjalny plugin wskazuje https://api.magicpath.ai/mcp/openai/v1. Działa w tej sesji bez reinstalacji. Potwierdzono projekt 468340598617829376, komponent 468341358789300224 (ready-flood-7620), rewizję 468345348532875264. Odczytano src/App.tsx, src/index.css i src/components/generated/AIOACosmicInteractiveAndroidMissionControl.tsx. Zapisano prywatny snapshot źródeł; jest to eksport edytowalnego komponentu, nie pełny projekt Vite.
Odczytany install plan wymienia class-variance-authority, clsx i tailwind-merge oraz instrukcje instalacji dla Reacta. Nie wykonano tych instrukcji, nie instalowano zależności ani nie kopiowano Reacta do APK. Kod prototypu zawiera symulowany online i lokalne demonstracyjne odpowiedzi czatu — nie przeniesiono ich do działających statusów AIOA. Licencja kodu prototypu i pełnego scaffoldu pozostaje UNKNOWN; wdrożenie Compose/Web korzysta z odczytanego UX i własnego kodu istniejącej aplikacji.
Quota MCP: w chwili odczytu limit50/tydzień, remaining38 po odczycie quota. Ten audyt zużył łącznie5 wywołań API quota/metadata/źródła; otwarcie canvas jest wyłączone z naliczania. Nie rozpoczęto generowania, sesji edycji, builda ani zakupu kredytów; nowe wywołania po wyczerpaniu quota są blokowane przez usługę.

## Tokeny, typografia i zasoby
Źródło: docs/design/cosmic.tokens.json. Kolory: #0B1023 background, #151D33 surface, #55D9F6 action, #8A63FF Muse, #F6F8FF text, #9DA9C6 muted, #FFC66D warning, #4AD8A0 success, #FF647A danger.
Skala: 4/8/16/24/32; karta radius14, minimalny cel48; nagłówek32/40, treść16/24, podpis14/20; brak ruchomych dekoracji. Stany nie polegają wyłącznie na kolorze.
Figma obecnie renderuje Inter. Zgodnie z Canvą i Foundations pobrano docelowe Space Grotesk / Manrope / IBM Plex Mono z przypiętego commitu oficjalnego google/fonts. Sprawdzono Git blob SHA i SHA-256 oraz dołączono OFL1.1 do Android assets i Linux Web. COSMIC_FONT_PROVENANCE.json zawiera dokładne pochodzenie; oba interfejsy korzystają z plików lokalnych, bez pobierania fontów w runtime.
Eksport Home z Figmy działa; brak potrzeby umieszczania makiety ekranu jako bitmapy w aplikacji. Ewentualne ikony/ilustracje eksportować z konkretnych ID; zapisać pochodzenie, SHA-256 i licencję, bez tymczasowych podpisanych URL w Git. Nie generowano obrazów ani nowych projektów z kredytów.

## Android, aktualizacja i rollback
- Piny projektu: JDK17, SDK36, build-tools35.0.0, Gradle8.13, AGP8.11.1, Kotlin2.2.21. Obecna przygotowana wersja: 0.3.1-cosmic, versionCode4; paczka eu.sparkhat.aioa.companion.
- Historyczny build bda9d312 miał testDebugUnitTest/lintDebug/assembleDebug; nie jest kompilacją bieżącej skórki.
- Wcześniejsza baza recovery: 24 rzeczywiste testy JVM oraz testy Python wskazane w pakiecie architekta. Bieżąca kontrola ujawniła przestarzały test źródłowy oczekujący versionCode3; zostanie związany z istniejącym manifestem wersji zamiast osłabienia weryfikacji APK.
- Nie potwierdzono dostępu ADB do telefonu w tym etapie. Nie instalowano, nie odinstalowano i nie czyszczono danych.
- Do aktualizacji zachowującej dane wymagany dokładnie istniejący certyfikat: 75a539bc1cc1cf9ca9cde7fddf32f8dc82ceaee3fd2c8831d9e32a7a14ab6404.
- Stary CI generował efemeryczny klucz debug. W dostępnych znanych lokalizacjach nie znaleziono jego kopii. Sam APK zawiera publiczny certyfikat, nie odtwarzalny klucz prywatny. Nie deklarujemy gotowości instalacji ani automatycznej migracji AndroidKeyStore.
- Kopia bazowa: /home/l/Downloads/aioa apk/AIOA-Cosmic-0.3.0-debug-bda9d312.apk, SHA-256 43ca92f447f89a31d37ddd91481ff2d627a5921a10798db002a3922294d7a537.
- Rollback kodu: baza df1a13e i zachowane patche/bundle w pakiecie architekta. Rollback telefonu do starej wersji nie jest obietnicą zachowania danych przy obcym podpisie lub downgrade; żadnej takiej operacji nie wykonano.

## Granice wdrożenia
Przygotowanie nowej skórki nie zmienia aktualnej tożsamości uruchomionego hosta. UI jest częścią source seal. Deploy nowego źródła wymaga realnej ponownej autoryzacji operatora i analizy zgodności zapisanych approvals, nie obejścia source/capsule binding. Na ten moment natywny operator odmawia odczytu po wygaśnięciu lokalnej sesji; nie przedłużano jej sztucznie.
Nowy wygląd nie nadaje uprawnień do płatnych modeli, GitHub WRITE, wykonania misji ani zatwierdzania na Androidzie.

## Zależności i autoryzacje
- Żaden nowy Core, frontend, runtime, baza, MCP lub provider nie jest potrzebny.
- Nie instalować kolejnego MCP Figma/Canva: działają.
- MagicPath: istniejący plugin działa. Nie jest wymagana instalacja ani kolejne OAuth w tej sesji. Pomoc CLI0.166.0 potwierdza obsługę mcp add --url i mcp login, lecz nie zmieniano konfiguracji. Nie dodawać konkurencyjnego połączenia.
- Pełny Android SDK/Gradle i podpis są blockerami przygotowania bezpiecznego APK. Nie kwalifikować dysku fikcyjną flagą ani nie osłabiać STRICT/DEBUG.
- GitHub Actions: odczyt i konfiguracja potwierdzone. Nie uruchomiono workflow, nie modyfikowano CodeQL, brak merge/push w tym etapie.

## Kryteria odbioru implementacji
1. Wszystkie ramki mają rzeczywistą trasę lub jawny stan niedostępności; brak atrap LIVE, repozytoriów i receipts.
2. Jedne tokeny i czytelne karty/nawigacja; ekran przewijalny przy 200% czcionki, cel48dp, opisy fokusu, TalkBack i kontrast.
3. Te same publiczne identity, zapisany host, TLS1.3/pin, nonce, podpisy, expiry/revocation i fail-closed.
4. Niepewny POST nie jest automatycznie ponawiany; source/capsule/authority pozostają egzekwowane.
5. Realne testy logiki i web; testy źródłowe nie zastępują kompilacji Androida.
6. Przed instalacją: pełne testDebugUnitTest/lintDebug/assembleDebug, SHA-256 APK i ten sam podpis, fizyczne sprawdzenie parowania/reconnect.
7. Brak merge bez osobnej zgody.

## Decyzja
COSMIC_DESIGN_ENV_BLOCKED dla pełnego buildu/aktualizacji Androida. Dostęp MCP i mapowanie zostały sprawdzone; lokalna skórka Compose/Web została przygotowana i poddana osobnym testom opisanym w COSMIC_DESIGN_IMPLEMENTATION_REPORT.md.
Konkretny blocker instalacji: brak klucza pierwotnego podpisu; bez niego nie da się dostarczyć zgodnej aktualizacji 0.3.0 zachowującej AndroidKeyStore. Decyzja o jakiejkolwiek migracji danych/parowania pozostaje po stronie właściciela i architekta.
