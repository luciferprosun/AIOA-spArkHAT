# Zmiany NZ13

E15 przypiął podstawę E14. E16 rozliczył 69 pozycji źródłowych i zakres portów. E17 zweryfikował lokalne ADD i MODIFY, receipt oraz jeden Core.

E18 a1af07e12ceaab0e21ad50d9f923f8d86c9b2c40 zachował sprawdzanie START przed rezerwacją, powtórną kontrolę w COMMIT, związanie capture CONTROL z fazą i idempotencję po utracie ACK. Zmiana położenia kontraktów governora usunęła zależność cykliczną. Przypięcia pochodzenia zaktualizowano po porównaniu blobów i AST.

E19 wiąże ten stan z dokumentacją, macierzą i wnioskami właściciela.

Korekta E18 e23632302b51e8371298dcc801f01f9842a74003 odracza opcjonalny import konfiguracji Native w odczycie statusu. Jawny import klasy i kontrola typu w trybie Native przeszły na obu Pythonach.
