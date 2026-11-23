# Odbiór techniczny rejestrów #16 i #53

Właściciel zatwierdził jeden kanoniczny Core i wycofanie historycznych rejestrów wykonawczych przy zachowaniu udowodnionych zachowań. Baza odbioru to `3b8e38df40ddd019075fc0053af3827ccb45c8bd`. Źródło porównania to historyczny W7A `392487849eddc7444f5159994b66b72e73f15934`.

| Pozycja | Zachowanie historyczne i odpowiednik | Odbiór |
| --- | --- | --- |
| #16 | `github/effect_repository.py` utrwalał decyzję, blokował sprzeczne roszczenia do efektu i rozdzielał pokwitowanie od nierozstrzygniętej rekonsyliacji. `CoreWarrantLedger` przyjmuje związany warrant właściciela, a `CoreIntentJournal` atomowo wiąże zużycie, intent, rezerwację i outbox. Ponowne START odmawia kolejnej dyspozycji. | `CORE_EQUIVALENT_LEGACY_AUTHORITY_RETIRED` |
| #53 | `workspace/authority_repository.py` wiązał propozycję z decyzją, jednokrotnym użyciem i dowodem. `CoreCodingTasks`, `CorePatchCapsules`, `CoreWarrantLedger` i `CoreIntentJournal` realizują te wymagane role na jednym stanie Core z podpisaną kapsułą i niezależnym odczytem skutku. | `CORE_EQUIVALENT_LEGACY_AUTHORITY_RETIRED` |

Test porównawczy `test_legacy_authority_replacement` uruchamia tę samą ścieżkę START dla Git i workspace w obu kolejnościach. Po pierwszym efekcie druga domena odmawia przed restartem i po nim, również z nową decyzją, nonce i sesją. Utrzymane zostają UNKNOWN, rezerwacja i HELD. Istniejące testy Core, kapsuł, pokwitowań i GitHub WRITE pokrywają odrzucone decyzje, powtórzenia, odczyt bez mutacji i trwałość. Wyniki w [TEST_RESULTS](TEST_RESULTS.json).

Odbiór dotyczy odpowiedzialności autoryzacyjnej. Dawne UUID i DTO, YAML, Strands interrupt, transport HTTPS oraz źródło historycznych danych pozostają osobnym przedmiotem kwalifikacji w macierzy. Stare pliki, w tym ewentualne pokwitowania, są dowodami historycznymi. Zgodny ref i niesygnowana suma kontrolna dawnego rejestru nie ustanawiają atrybucji ani prawa do efektu. [Macierz](PARITY69_UPDATED.csv) · [Decyzje dla kontraktów](EXTERNAL_CONTRACT_DECISIONS.md)
