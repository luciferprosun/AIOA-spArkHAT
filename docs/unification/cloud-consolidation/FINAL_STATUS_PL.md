# Konsolidacja AIOA spArkHAT × NonZero

**Status `PARITY_OPEN`.** Kod i testy działają w jednym AIOA Core. Konsolidacja nie osiągnęła `FULL_PARITY`.

## Bieżący odbiór

Main po #59 to `914c9b1bf4dc7bf6ff14687d91560d9bcef1a5f6`, drzewo `f4238a014e210e46863a4f6e7abadc40bf71fa61`. Cztery wymagane kontrole, domyślny CodeQL i MCP Bridge przeszły. Właściciel potwierdził zsynchronizowany Linux Mint i 98/98 testów na obu wersjach Pythona. Kolejna synchronizacja użyje istniejącego checkoutu. [CI](https://github.com/luciferprosun/AIOA-spArkHAT/actions/runs/45107463038) · [Linux](LINUX_SYNC_HANDOFF.md)

Pełny restart Native i G04 mają w obecnym Cloud stan `BLOCKED_HOST`. Wycofanie legacy ma stan `HOLD`. [Host](NATIVE_HOST_QUALIFICATION.md) · [Bramka wycofania](NONZERO_RETIREMENT_GATE.md)

## Ustalony zakres

Punktem odczytu był `main` `7b5fd205c02603231919451b1cacd241f49fd9e9`, drzewo `c6f8f76b5a6e93855e5dd4c80a8af313db0054a2`. Główna gałąź zawiera PR [#52](https://github.com/luciferprosun/AIOA-spArkHAT/pull/52), [#53](https://github.com/luciferprosun/AIOA-spArkHAT/pull/53), [#54](https://github.com/luciferprosun/AIOA-spArkHAT/pull/54), [#55](https://github.com/luciferprosun/AIOA-spArkHAT/pull/55), [#56](https://github.com/luciferprosun/AIOA-spArkHAT/pull/56) i [#57](https://github.com/luciferprosun/AIOA-spArkHAT/pull/57).

Core modeluje intenty, warrant, rezerwacje, podpisane pokwitowania, STOP i stany niepewne. Działa ograniczona ścieżka WorkerMailbox, Task Continuation, PatchSet, Repair Loop, lokalnego Git CAS, Safe Launcher i fixture MCP. `PARITY69_UPDATED.csv` wiąże każdą pozycję z oryginalnym blobem W7A, obecnymi blobami AIOA, rozpoznanymi importami runtime, modułami testów, luką i kryterium odbioru. Import wskazuje zależność kodu, a wykonanie jest udokumentowane w wynikach testów. `TEST_RESULTS.json` przypina dowody do commitów i zakresów.

| Bieżąca klasyfikacja | Liczba |
| --- | ---: |
| `ARCHIVE_ONLY` | 33 |
| `UNKNOWN_EXTERNAL` | 23 |
| `PARTIAL` | 7 |
| `VERIFIED_SCOPED_OFFLINE` | 3 |
| `SECURITY_BLOCKED` | 3 |

Macierz stosuje klasyfikację ID przekazaną w audycie właściciela. `PARTIAL` obejmuje #2, #3, #17, #18, #19, #41 i #63. Każdy z 23 wierszy `UNKNOWN_EXTERNAL` ma własne kryterium odbioru. Wcześniejsze przypisania Cloud zastąpiono dostarczonymi ID. Pełny CSV z Linux Mint pozostaje poza Cloud. Kolumna `release_matrix_status` zachowuje udokumentowaną starszą klasyfikację. `VERIFIED_SCOPED_OFFLINE` dotyczy #5, #15 i #31. Blokady #16 i #53 dotyczą duplikowania źródła autoryzacji, a #69 nieznanego wykonawcy CAS po restarcie.

## Dowody, odbiory i rollback

GitHub pokazywał aktywną próbę 2 przed rozpoczęciem prac. Pierwsza próba 3.11 trwała 15,794 s w teście Chrome i zakończyła się `CHROME_COMMAND_UNKNOWN` przy `Browser.getVersion`. Druga próba przeszła wszystkie cztery wymagane kontrole, w tym Chrome, One-Core i pochodzenie źródeł. Domyślny CodeQL przeszedł na tym samym SHA. Przyczyna pierwszego timeoutu pozostaje niepotwierdzona. Trwałość po awarii jest objęta lokalną regresją `test_nz25_intent_cold_read.py` na 3.11 i 3.12. Native #69 nadal wymaga dowodu pochodzenia. Cztery LIVE mają wynik `NOT_RUN`. Dokładne zakresy, odmowy i wyniki są w `TEST_RESULTS.json`, `SECURITY_GATES.md` i `LIVE_QUALIFICATION.json`. [GitHub Actions](https://github.com/luciferprosun/AIOA-spArkHAT/actions/runs/45045595617)

Przed merge wystarczy pozostawić Draft bez scalenia. Jeżeli później potrzebny będzie rollback, użyć osobnej gałęzi i PR z `git revert` właściwego commita albo `git revert -m 1` właściwego merge commita. Sprawdzić zgodność bazy i uruchomić wymagane CI. Zachować dowody, istniejące `UNKNOWN` i powiązane rezerwacje. Procedura Linux Mint jest w `RESUME.md`.

## Weryfikacja historii i przyszła archiwizacja

Odtworzony bundle legacy zawiera 13 refów i ma SHA-256 `84e5720c6cab3a8be59669a83396ed00018269be04e80e31bdc1e75d4828331e`. Znormalizowana lista refów ma SHA-256 `9cd19a7d2caa6c3bfc4bb88888e6928b3e642bd92b25442bac96863183f14c36`. Po przywróceniu do osobnego repozytorium lista refów była identyczna, a `git fsck --full --no-dangling` zakończył się kodem 0. Piny Judge freeze i W7A to `4fafed8b1a877e55d96ddd9baea0a737fbeeaa4a` i `392487849eddc7444f5159994b66b72e73f15934`. Bundle jest plikiem w obszarze roboczym Cloud. Drugi bundle ma stan `BLOCKED_BACKUP`, ponieważ nośnik był niedostępny podczas audytu właściciela.

Po zamknięciu zakresu NonZero, rozstrzygnięciu odbiorów, sprawdzeniu niezależnej kopii i potwierdzeniu synchronizacji Linux Mint właściciel może oddzielnie zatwierdzić archiwizację oryginału. Oryginał pozostaje aktywnym repozytorium historycznym do tej decyzji.
