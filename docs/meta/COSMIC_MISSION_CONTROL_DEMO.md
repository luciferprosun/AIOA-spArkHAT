# Cosmic — scenariusz demonstracji jednego systemu

**Stan odbioru fizycznego: NOT_RUN.** Ten dokument jest instrukcją odbioru, nie nagraniem ani dowodem działającego telefonu.

## Pierwszy materiał: prawdziwe parowanie

1. Pokaż istniejący panel urządzeń AIOA na Linuxie i otwórz publiczny podpisany QR po rzeczywistym admission operatora.
2. Na telefonie otwórz nową aplikację, zeskanuj QR i sprawdź host. Na obu ekranach pokaż zgodny SAS. Zatwierdź dokładne urządzenie na Linuxie.
3. Pokaż świeży, podpisany status: source SHA, stan połączenia i czas obserwacji. Tokenów, kodów starego enrollment, prywatnych kluczy i haseł nie nagrywaj.
4. Zamknij aplikację i otwórz ją ponownie. Odbiór wymaga nowego połączenia bez kopiowania kluczy i bez QR.
5. Odwołaj dostęp w panelu Linux. Telefon ma pokazać odmowę, a nie zachować zielony status po wygaśnięciu obserwacji.

Warunki techniczne i test restartu hosta: `docs/android/ONE_TAP_PAIRING_ACCEPTANCE.md`.

## Misja dopiero po PAROWANIE PASS

Wybierz funkcję rzeczywiście dostępną w podpisanych capabilities tego samego Core. Obecny profil native udostępnia status READ i nie przyznaje wykonywania misji. Sam nowy wygląd, zapamiętany telefon i testy syntetyczne nie zmieniają tych uprawnień.

Jeśli rzeczywista misja jest nadal NOT_BOUND, pokaż ten stan i przyczynę. Nie przełączaj do fixture pod etykietą LIVE. Plan/approval/dispatch/readback/receipt muszą dotyczyć tej samej operacji i source SHA. UNKNOWN wymaga niezależnego readbacku, bez automatycznego ponowienia efektu.

Muse LIVE wymaga oddzielnej, świeżej zgody obejmującej dokładny model, jedno wywołanie lub ograniczony tool turn, limity tokenów i koszt. Historyczna pula 1 USD dla Nebiusa nie jest zgodą na nowy provider. GitHub push/PR także wymaga uzgodnionego zakresu. Do demonstracji parowania nie potrzeba płatnego modelu.

## Dowody, które mają powstać

- Exact source commit i capsule, APK SHA-256 oraz certyfikat podpisujący.
- Wyniki rzeczywistego Kotlin JVM/lint/assemble oraz niezależnego review.
- Wynik fizycznego QR/SAS/status/reconnect/revoke z datą; urządzenie identyfikowane publicznym fingerprintem.
- Oddzielne statusy: PAROWANIE, CZAT, MISJE, MUSE LIVE, GITHUB WRITE. Brak próby oznacza NOT_RUN; brak authority oznacza NOT_BOUND/BLOCKED.

Nie deklarujemy jeszcze gotowego filmu ani AGENT_READY.
