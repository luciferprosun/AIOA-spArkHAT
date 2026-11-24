# Jedna tabela decyzji dla 23 kontraktów zewnętrznych

Zakres potwierdzonych aktywnych odbiorców zewnętrznych pozostaje pusty. GitHub i historia widzą dawne wdrożenie Render oraz historyczne interfejsy. Kategoria w tabeli to rekomendowany tryb rozliczenia, a każdy wiersz zachowuje `UNKNOWN_EXTERNAL` do przypięcia odbiorcy lub decyzji właściciela o zakresie.

| ID | Rekomendowana grupa | Decyzja i konkretny warunek |
| --- | --- | --- |
| 11 | Core obsługuje rolę | Odebrać związanie owner approval, kapsuły, nonce i sesji przez Core. Zachować dawne decyzje jako dowody. |
| 12 | Core obsługuje rolę | Porównać podpisaną kapsułę i binding base, task, PatchSet, etap. Historyczny format kapsuły przyjąć tylko jako obojętną projekcję. |
| 13 | Adapter przy potwierdzonym odbiorcy | Ustalić wersję i wymagane pola DTO repo i poświadczenia. Adapter odrzuca sekrety i nie tworzy autoryzacji. |
| 20 | Adapter przy potwierdzonym odbiorcy | Zmapować VERIFIED, DENIED i UNKNOWN do odczytu ze wskazaniem źródła i rodzaju dowodu. |
| 24 | Adapter przy potwierdzonym odbiorcy | Przypiąć stare HTTP route, headers, status i semantykę trybu. Przy braku odbiorcy wycofać alias i stary transport w uzgodnionym oknie. |
| 26 | Adapter przy potwierdzonym odbiorcy | Porównać timeline, kolejność, ograniczenia długości, redakcję i taint. |
| 30 | Core obsługuje rolę | Odebrać odczyt trwałego klucza oraz odmowę cross-run i replay na próbce rzeczywistego odbiorcy. |
| 33 | Adapter przy potwierdzonym odbiorcy | Porównać DTO ADD/MODIFY/DELETE, bajty i wiązania task, run i worker. |
| 34 | Core obsługuje rolę | Porównać evaluate i recheck, sprawdzić drift, digest, ograniczenia ścieżki i odmowę sekretów. |
| 40 | Adapter przy potwierdzonym odbiorcy | Odebrać kolejność, statusy PASS, FAIL, STOP i UNKNOWN, czytelność wcześniejszego podpisu i odmowę powtórzenia. |
| 44 | Kandydat do formalnego wycofania | Ustalić, czy odbiorca wymaga historycznego lifecycle Docker. Dopuszczalne zachowania kwalifikować przez zamknięty profil Core. |
| 46 | Kandydat do formalnego wycofania | Ustalić konkretną wymaganą receptę i odebrać efekt i sprzątanie w istniejącym brokerze. |
| 47 | Kandydat do formalnego wycofania | Porównać lock i artefakty Python/Node. Historyczny setup i rejestry rozliczać osobno po potwierdzeniu odbiorcy. |
| 50 | Core obsługuje rolę | Zachować wyzwanie właściciela. Przypiąć wymaganie Strands interrupt przed zgodą na adapter. |
| 52 | Adapter przy potwierdzonym odbiorcy | Projektować wyłącznie wymagane zanonimizowane pola DTO. Wyłączyć nonce i uprawnienie apply z projekcji. |
| 55 | Adapter przy potwierdzonym odbiorcy | Porównać artifact ref, rozmiar, digest, taint i trace, chroniąc prywatne ścieżki. |
| 56 | Core obsługuje rolę | Odebrać bytes, hash i allowlist z odmową symlink, hardlink i driftu. |
| 57 | Nadal nierozstrzygnięte | Ustalić, czy rzeczywisty odbiorca wymaga zapisu Render YAML czy efektu Git. Każdy efekt kwalifikuje się osobno. |
| 60 | Core obsługuje rolę | Odebrać ograniczenie deskryptorem, odmowę zmiany inode i limity. |
| 61 | Core obsługuje rolę | Związać artefakty i dozwolone operacje z ograniczonym profilem, sprawdzić brak rozszerzenia uprawnień. |
| 62 | Adapter przy potwierdzonym odbiorcy | Odebrać obojętną propozycję Render z digestami before/after i historycznym dowodem. |
| 66 | Core obsługuje rolę | Odebrać niezależny reopen root, path, bytes, runtime i odmowę po wykryciu zmiany. |
| 67 | Adapter przy potwierdzonym odbiorcy | Porównać report, receipt i proof origin z zachowaniem podpisu, UNKNOWN i zakazu automatycznego apply. |

Dla potwierdzonego kontraktu zapisać właściciela, dokładny punkt wejścia, wspieraną wersję, przykładowy poprawny i błędny fixture oraz dowody odczytu. Dla formalnego wycofania zapisać zakres, termin, powiadomienie i decyzję właściciela. [Macierz 69](PARITY69_UPDATED.csv)

## Klasyfikacja decyzji

W kolumnie `external_contract_disposition` wszystkie 23 wpisy mają `UNKNOWN`. Dziewięć ról ma odpowiednik Core, dziesięć może wymagać adaptera po potwierdzeniu odbiorcy, trzy są kandydatami do wycofania, a #57 ma nierozstrzygnięty wymagany efekt. Żaden kontrakt zewnętrzny nie uzyskał dowodu `VERIFIED`, `IMPLEMENTATION_REQUIRED` ani `NOT_APPLICABLE_WITH_EVIDENCE`.

## Odczyt dowodów C05 dla #30, #33 i #40

| ID | Potwierdzony zakres Core | Brakujący dowód kontraktu |
| --- | --- | --- |
| #30 | Fixed vectors Judge i W7A, identyczne pokwitowanie po restarcie, zero drugiej mutacji i odmowa klucza innego przebiegu. Testy `test_nonzero_parity` oraz `test_nz13_cloudops_contracts`. | Aktualny klient, dokładny import lub endpoint, wersja i zapisany rzeczywisty rekord wraz ze skrótami. |
| #33 | Wyprowadzenie ADD, MODIFY i DELETE z plików. Odtworzenie tej samej projekcji Core oraz odmowa podmienionego zagnieżdżonego PatchSet. Testy `test_hybrid_patchset` i `test_nz25_coding_receipt_read`. | Próbka komunikatu konsumenta. W7A wiąże osobne UUID, trace i run, a Core wiąże task, session i źródło. |
| #40 | Kolejność porażka, naprawa, PASS, zachowanie UNKNOWN przy problemie sprzątania i niezmienny odczyt po wznowieniu. Testy `test_hybrid_repair` i `test_nz25_coding_receipt_read`. | Próbka historycznego DTO wraz z identyfikatorem sandboxa, skrótami stdout/stderr i regułami pochodzenia lub podpisu etapu. |

Wszystkie trzy wpisy zachowują `UNKNOWN_EXTERNAL`. Pozytywne wyniki odczytano w obu przebiegach Pythona na dokładnym `main` `8bd2fe14033f1b49609092a353cd7e6fd6b8d3ef`. [CI po #63](https://github.com/luciferprosun/AIOA-spArkHAT/actions/runs/45223650707/attempts/2)
