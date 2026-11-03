# Cosmic pairing — odbiór rzeczywisty

Status: **NOT_RUN na fizycznym telefonie**. Testy izolowane nie zastępują poniższych czynności. Stary APK v2 ma ręczny enrollment; nowy przepływ wymaga nowego APK. USB nie jest potrzebne do parowania przez prywatny Tailscale.

## Przed próbą

1. Zakończyć review i rzeczywiste `testDebugUnitTest lintDebug assembleDebug` na zatwierdzonym builderze; zapisać commit, SHA-256 i certyfikat podpisujący APK. APK <=128 MiB, retencja CI 1 dzień, run <=35 minut. Nie uruchamiać kolejnego buildu bez rozpoznanej przyczyny niepowodzenia.
2. Zweryfikować zgodność podpisu z zainstalowanym APK przed próbą aktualizacji. Nie usuwać istniejącej aplikacji, jej danych ani klucza Keystore automatycznie. Gdy debug signer jest inny, zgłosić potrzebę decyzji właściciela o instalacji testowej; nie obchodzić weryfikacji Androida.
3. Zachować istniejący prywatny katalog Core, bazę i klucz hosta. Zweryfikować, że działa tylko jedna właściwa instancja. Nie zatrzymywać innych usług.
4. Uruchomić istniejący profil `python -m runtime.webapp --mobile-native` z dotychczasowym katalogiem stanu, origin, kluczem/certyfikatem TLS i portem loopback. Rzeczywisty lokalny operator przechodzi istniejący PolicyKit. Nowy commit/source capsule musi być ustabilizowany przed admission.
5. Zweryfikować TLS 1.3, CA, hostname i podpisany host proof przez istniejący prywatny Tailscale. Bez Funnel, trustAll i publicznego wystawiania portu. Brak zaufanego admission oznacza BLOCKED, nie automatyczne approved=True.

## Pierwsze połączenie

- Linux: z tego samego checkoutu `python -m runtime.webapp --mobile-operator console --state-dir <istniejący-prywatny-katalog-Core>`. Polecenie otwiera `/devices` w tej samej aplikacji; nie wypisuje tokenu. Nie wymaga wpisywania danych authority przez użytkownika.
- W panelu wybierz **Dodaj telefon**. QR zawiera publiczny podpisany invite ważny maksymalnie 300 sekund.
- Telefon z aktywnym Tailscale: **Połącz z moim AIOA → Skanuj QR**. Sprawdź wskazany host. Gdy skaner jest niedostępny, zaimportuj cały podpisany publiczny pakiet z panelu; nie wpisuj osobno SPKI ani kodu enrollment.
- Porównaj sześciocyfrowy SAS i urządzenie na obu ekranach. Linux zatwierdza dokładny request digest widocznym przyciskiem. Sama nazwa telefonu, QR ani model nie nadają uprawnień.
- Telefon kończy enrollment i odczytuje świeży podpisany status. Dowód PASS musi zawierać zgodny device fingerprint, request/approval digest, task/status/source, czas i wynik weryfikacji podpisu; bez bearerów, kodów, kluczy prywatnych.

## Powrót i odmowy

Zamknij i uruchom aplikację: połączenie ma wrócić bez QR przez świeży podpisany challenge. Następnie kontrolowanie uruchom ponownie wyłącznie tę instancję hosta, zachowując stan/klucz i wykonując rzeczywiste admission; stara sesja musi zostać odrzucona, nowy reconnect ma zadziałać. Brak sieci, wygaśnięcie i utrata odpowiedzi muszą pozostać czytelne, bez automatycznego ponawiania niepewnej mutacji.

Odwołaj urządzenie na Linuxie: dotychczasowa sesja i reconnect mają otrzymać DENY. Niezużyty stary kod enrollment także nie może odtworzyć dostępu. Ponowne parowanie wymaga nowego jawnego zatwierdzenia. Zły host/TLS/pin, zmiana digestu, replay, nonce lub scope: DENY.

## Granice wyniku

`PAROWANIE PASS` wymaga powyższego rzeczywistego testu z właścicielem. Nie oznacza Muse LIVE, czatu, WRITE, wykonania misji ani GitHub push. Te możliwości zachowują własne uprawnienia i bramki. Obecny lokalny profil native udostępnia podpisany status READ.

Core zachowuje limit 1024 zdarzeń AUDIT i 32 MiB bazy; adapter nie usuwa historii ani nie obchodzi limitów. Trwałość binding nie jest deklaracją nieograniczonej pojemności. Nie używać telefonu do agresywnego odpytywania; pending status co najmniej co 3 sekundy, koniec przy expiry/odmowie.
