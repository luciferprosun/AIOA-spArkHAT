# ADR — One-tap pairing, 2026-11-02

Decyzja właściciela: QR z zaufanego ekranu Linuxa + jawne zatwierdzenie konkretnego klucza urządzenia; później podpisany reconnect. Źródło wymagań: AIOA_COSMIC_ONE_TAP_ARCHITECTURE_CODEX_2026-11-02.pdf. Bez kolejnego Core, backendu, bazy, providera ani silnika zgód.

Bazą jest main f71fb33. Stary worktree i jego dwa raporty pozostają nietknięte; kopie z SHA są w prywatnym katalogu COSMIC_20261102T153359Z. Dawny host przeszedł OS/TLS, ale nie ma dowodu enrollmentu Xiaomi. Uprawnienie operatora wygasa po godzinie; dokumentacja nie przedłuża go.

## Wybrana kompozycja

Rozszerzamy istniejący MobileGateway/NativeMobileComposition, CoreAdmission, TransactionRunner i OPERATION/AUDIT/OUTBOX. Oddzielny plik pomocniczy protokołu jest adapterem tej samej instancji, nie nowym runtime. Dotychczasowe v1 enrollment/status pozostają zgodne. Publiczny podpisany invite TTL <=300s nie zawiera bearer credential ani kodu enrollment. Zaufanie do pierwszego hosta pochodzi ze skanu zaufanego ekranu + SAS i potwierdzenia exact device przez lokalnego operatora, nie z samopodpisu lub odkrycia DNS.

Telefon podpisuje begin kluczem Keystore. Host pokazuje SAS związany z invite, publicznym kluczem, origin i source. Zatwierdzenie dotyczy pełnego request digest, nie samej nazwy/SAS. Jeden invite wiąże jedną próbę; liczba prób i nonce jest ograniczona. Replay/ACK loss wymagają jawnego readbacku, nie ponowienia skutku.

Trwałe MOBILE_DEVICE binding w tej samej bazie zawiera publiczny klucz, host identity, zakres tylko status READ, approval provenance i revocation. Restart zachowuje binding, ale unieważnia krótkie sesje/challenges; nowy rzeczywiście uwierzytelniony operator ponownie aktywuje ten sam host. Podpisany nonce pozwala wydać nową sesję bez QR. Revoke binding unieważnia także wszystkie sesje; zmiana klucza hosta wymaga ponownego parowania. Zmiana źródła wymaga świeżego podpisanego challenge i jawnej polityki hosta, nie akceptacji starych nonce. TLS CA/hostname/pin pozostają obowiązkowe; mismatch oznacza blokadę, nie automatyczną rotację z niezaufanej sieci.

## Lokalny panel

Panel urządzeń jest częścią istniejącego web/, obsługiwaną przez ten sam runtime.webapp. Owner HTTP nie może otrzymać authority przez sam loopback: Tailscale proxy także przychodzi z loopback. Bootstrap panelu pochodzi wyłącznie z prywatnego operator.sock/SO_PEERCRED po PolicyKit. Użyć istniejącego session/CSRF transportu po zamknięciu publicznego bootstrapu w profilu native; token krótkotrwały, w pamięci, bez URL query/logów/QR. Token transportuje istniejący principal; nie zastępuje Core. Brak drugiego nasłuchującego serwera lub niezweryfikowanego operator_approved.

## Alternatywy

Skaner: Google Code Scanner `play-services-code-scanner:16.1.0`, przetwarzanie na telefonie bez uprawnienia CAMERA. Moduł Google Play Services może wymagać pobrania przy pierwszym użyciu; brak skanera nie może blokować importu całego podpisanego pakietu. QR zawiera surowy JSON envelope. Alternatywny deep link `aioa://pair#base64url(JSON)` jest tylko nośnikiem tych samych danych, nigdy adresem do automatycznego pobrania.

Bootstrap panelu Linux (FINAL_BUILD §1.2): prywatny socket po SO_PEERCRED rotuje istniejący token transportu i wydaje oddzielny losowy sekret dostarczenia, związany z UID, jednorazowy i ważny 30 sekund według zegara monotonicznego. To pojedynczy wpis w RAM istniejącego serwisu; brak nowej bazy lub authority. Launcher umieszcza wyłącznie sekret dostarczenia w pliku formularza 0600 w katalogu 0700 na `/run/user/<uid>` (tmpfs), usuwanym po 30 sekundach. Argument procesu przeglądarki zawiera wyłącznie ścieżkę pliku. Formularz wykonuje top-level HTTPS POST do dokładnego `/devices`; od pierwszej nawigacji żaden URL, query ani fragment nie zawiera credential.

Wyjątek dla `Origin: null` dotyczy tylko tego POST z dokładnym Host/TLS1.3, `Sec-Fetch-Site: cross-site`, `Mode: navigate`, `Dest: document`, pojedynczym Content-Length 52, dokładnym typem formularza i ciałem `delivery=<43 znaki base64url>`. Brak proxy/chunked/duplikatów. Poprawny sekret jest zużywany pod istniejącą blokadą przed ponownym sprawdzeniem rzeczywistego Core owner/source/TLS i odpowiedzią. Brak, błędny, wygasły, powtórzony sekret lub utracony ACK nie wydaje tokenu ponownie; potrzebne jest nowe jawne lokalne otwarcie. Nie ma automatycznego ponawiania operacji.

Odpowiedź no-store to ten sam HTML panelu z jednorazowym nośnikiem DOM tuż przed skryptem panelu. Skrypt natychmiast czyści i usuwa nośnik, przekazując istniejący token wyłącznie do pamięci klienta. Zwykły GET nie zawiera tokenu. Każda rzeczywista operacja nadal wymaga dokładnego bieżącego HTTPS Origin, CSRF i aktualnego uprawnienia Core; `Origin: null` nie nadaje dostępu do API operatora. Credential nie trafia do argv, stdout, logów/audit/bazy, QR, localStorage ani sessionStorage. Wygaśnięcie godzinnego admission blokuje panel; nie odnawiamy authority flagą. To ograniczony transport lokalnego principal, nie nowy system zgód.

Ograniczenie historii przeglądarki: rzeczywisty Chrome zachowuje wartość jednorazowego POST w pliku `Default/Sessions/Session_*`, mimo no-store i replaceState. Po udanym dostarczeniu ten ticket jest już zużyty; ponowne dostarczenie daje 403 bez tokenu. Nie obiecujemy wyłącznego RAM dla ticketu. Przy nieudanej nawigacji przed zużyciem zachowany ticket może pozostać ważny do końca 30-sekundowego TTL; wymagane jest nowe jawne otwarcie, bez automatycznej próby. Profil użytkownika przeglądarki należy do lokalnej granicy zaufania. Wielokrotnie używany CSRF jest innym sekretem: skan świeżego profilu musi nie znaleźć jego bajtów. Brak CSRF w profilu, WebStorage, URL, argv i logach nie jest twierdzeniem o braku historii jednorazowego POST. Wcześniejsze dwa nieudane sprawdzenia silniejszego zakazu zapisu ticketu pozostają w dowodach; ten jawny residual risk podlega niezależnemu review.

Ręczne pola zachowane wyłącznie w diagnostyce: nie spełniają UX. USB jest debug-only i nie nadaje authority. Publiczny relay i discovery pozostają poza MVP. Model/Muse/WRITE mają niezależne bramki; UI pokazuje faktyczną niedostępność.

## Odbiór

Offline RED/GREEN, niezależny security review, rzeczywista kompilacja Kotlin/lint/APK, następnie właściciel: QR, SAS approve, podpisany status, restart aplikacji bez QR, revoke/DENY. Wyniki fixture nigdy nie stanowią phone PASS. Push/merge/płatne wywołanie wymagają konkretnej bramki zgodnie z nowym promptem.
