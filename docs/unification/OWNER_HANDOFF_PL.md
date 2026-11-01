# ONE AIOA — odbiór właściciela, 2026-11-01

Stan: READY_FOR_INDEPENDENT_REVIEW. Kod i utrwalony home demo działają;
natywne41/41 PASS po poprawce cache; końcowa pełna regresja i review pozostają
wymagane przed publikacją.
Ten dokument roboczy nie zatwierdza merge, API, instalacji ani Android Actions.

## Co rzeczywiście działa

FAKTY: jeden `runtime.webapp.WebRuntimeService`, istniejący `MissionService`,
CoreAdmission, TransactionRunner, warrant ledger, governor, journal i AUDIT/OUTBOX.
Podpisany klient P-256 proponuje SensorBridge. Dokładna zgoda lokalnego profilu
fixture poprzedza natywny START. Istniejący broker wykonuje create/append/rename,
5 testów Python i niezależny readback plików. Oddzielna zgoda daje rzeczywisty
lokalny commit o przewidzianym tree/HEAD, z plików potwierdzonych poprzednim receipt.
Nowy proces aplikacji zwraca ten sam trwały receipt. Zdalny zapis jest odrzucany.

Proponowanie, status, STOP, UNKNOWN i readback są dostępne w tym samym web,
MCP i podpisanym gateway. Telefon nie zatwierdza wykonania. Muse/Nebius/Local
LLaMA mają jeden katalog, bez automatycznego fallbacku.

Lokalny profil korzysta z istniejącego DurableFactory copy-on-write
(`core-records.json`), przez ten sam TransactionRunner i AUDIT/OUTBOX. Nie
poświadcza CockroachDB, Core M12 ani wieloprocesowego storage produkcyjnego.

To lokalny demonstrator ograniczonej receptury z rzeczywistymi efektami,
syntetycznym admission i bez wywołania modelu przy pisaniu projektu. Nie jest
to `AGENT_READY`, produkcyjny owner, Muse LIVE ani autonomiczny systemowy shell.

## Uruchomienie

```bash
cd /home/l/AIOA_LOCAL_WORKTREES/one-aioa-core-muse-mobile-20261101
PYTHONDONTWRITEBYTECODE=1 python3 -B -m runtime.webapp --unified-offline --host 127.0.0.1 --port 0
```

Polecenie wypisuje rzeczywisty adres loopback. W istniejącym panelu Agent
workspace: przygotować propozycję, obejrzeć manifest/diff i dokładny digest,
potwierdzić jedną operację fixture. Sprawdzić 5 testów, pliki/SHA i receipt.
Git preview jest osobną propozycją i wymaga osobnego potwierdzenia. Instalator
pokazuje wyłącznie plan. Nie wybierać płatnego providera ani starej instancji.
Wymagane są już dostępne, zakwalifikowane Linux/Python3.12/Git/bwrap/cc/cgroups;
polecenie nie instaluje brakujących narzędzi. Profil unified wymaga checkoutu;
sprawdzony wheel/sdist nie poświadcza uruchomienia unified bez source checkoutu.

Odtworzenie całego podpisanego scenariusza z zachowaniem dowodów:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -B -m scripts.unification.offline_demo --evidence-dir /absolute/fresh/private/qa-directory
```

Katalog ma być nowy; harness nie nadpisuje istniejących dowodów.

## Macierz bramek

| Faza | Status po zakończeniu wymaganej walidacji | Granica |
|---|---|---|
| G8 | MERGED_AND_VERIFIED / ANDROID_BUILD_NOT_RUN | PR26, jeden plik, main de6fddb; automatyczny CodeQL success |
| U0 | PASS | Source inventory, dirty Nebius i chronione procesy zachowane |
| U1 | PASS_LOCAL_FIXTURE | Ten sam Core i USD0/risk-only START; produkcyjny owner NOT_BOUND |
| U2 | PASS_LOCAL_FIXTURE | Rzeczywiste pliki i 5 testów, tylko zamknięta receptura w świeżym sandboxie |
| U3 | PASS_LOCAL_AND_DENIED_REMOTE | Prawdziwy lokalny commit; create-only zdalny publisher/ancestry NOT_BOUND |
| U4 | PASS_OFFLINE_CONTRACT | Plan + fake installer artifact readback; installed=false |
| U5 | PASS_LOCAL_FIXTURE | MCP LICENSE READ i proposal → Core → rzeczywisty worker/receipt |
| U6 | PASS_SIGNED_FIXTURE | Ten sam gateway/app source, receipt po restarcie; Kotlin/JVM/APK/telefon/TLS NOT_RUN |
| U7 | PASS_OFFLINE_CATALOG | Meta mock, Nebius NOT_BOUND, LLaMA DESIGN_ONLY; płatne API wyłączone |
| U8 | PASS_LOCAL_FIXTURE | Jeden start, auth HTTP, web, MCP i mobile; brak cutover legacy |
| U9 | PENDING_FINAL_REGRESSION_AND_REVIEW | Świeże regresje, source seals, pakiety i niezależny review |
| U10 | MAIN_MERGE_PENDING_OWNER_GO | Draft integracji po pełnym odbiorze; main nie jest jeszcze scalonym produktem |

Pełne ścieżki i SHAs: U0_SOURCE_LEDGER.md oraz FINAL_INTEGRATION_MATRIX.md.
Komendy, liczniki, źródła i zakres pominięć: U9_QA_EVIDENCE.md.

## Co pozostaje zablokowane

- Produkcyjny owner admission i lokalny zaufany transport właściciela: NOT_BOUND.
  Fixture assignment nie jest takim dowodem. CPL veto ma port/test fixture;
  nie poświadcza rzeczywistego CPL LIVE w tej kompozycji.
- Meta/Muse LIVE: brak aktualnie potwierdzonych billing/credits, właściwego
  native spend binding i osobnej zgody na dokładne wywołanie/model/limit.
  Nebius nie importuje starego salda ani zgody 1 USD. Klucz nie jest zgodą.
- GitHub przez agenta: realny remote push/PR oraz canonical base/ancestry
  wymagają zatwierdzonego create-only transportu, host credential isolation,
  dokładnych osobnych zgód i readback. Nie mylić push tego PR przez Codex
  ze zdolnością AIOA do publikowania repozytorium.
- Rzeczywisty installer, SYSTEM_INSTALL, shell, browser egress, Tailscale
  Serve/ACL i publiczny listener: wyłączone. Nie instalowano SDK ani pakietów
  hosta; packaging QA instaluje tylko własny wheel w prywatnych venv, offline.
- Kotlin/JVM/lint/APK/physical Xiaomi/TLS: nie wykonano. Źródłowe testy Node
  i podpisany klient Python nie są testami wykonania Androida ani układu przeglądarki.
- **Najnowszy APK: dodatkowo BLOCKED_SOURCE_REF_ALIGNMENT.** Zarejestrowany G8
  nadal dopuszcza wyłącznie `codex/android-toolchain-mobile-20261031` i stary
  source `17280c012561ecc59b1b6f7c65689d8e52506c69`. Nie zbuduje nowych v2
  źródeł z tej gałęzi/main. Po zatwierdzonej promocji trzeba osobno przejrzeć
  zgodną zmianę `.github/workflows/android-manual-build.yml` oraz
  `scripts/android/ci_build.py` i regresji, wskazać nowe exact source SHA,
  ponownie sprawdzić ImageVersion i Node24 oraz uzyskać trzy potwierdzenia:
  approve_run, sdk_license_ack, artifact_exposure_ack. Obecne flagi pozostają false.
  Historyczne `20261026.354.1` nie jest gwarancją wersji przyszłego runnera.

## Odbiór i promocja main

PR integracji, exact head i aktualny target main zostaną wpisane po publikacji.
Szeroka integracja nie scala automatycznie PR22 ani PR25. Obie historyczne
gałęzie pozostają zachowane, bez force-push, reset, clean lub zamknięcia PR.

Potrzebna będzie jedna nowa zgoda na konkretny PR/head/base. W PDF U10:
„duży merge wykonaj dopiero po odrębnej zgodzie na konkretny diff”.
Bez tej zgody nie wykonano promotion ani smoke na scalonym main.
Przed przyszłym merge trzeba ponownie sprawdzić head, main, wyniki i brak driftu;
po merge — sprawdzić rzeczywisty wynikowy SHA i uruchomić osobny smoke tego main.

## STOP i rollback

W UI użyć STOP własnego zadania; UNKNOWN wymaga niezależnego readback,
nigdy ponownego POST/run. W terminalu własnej nowej instancji użyć Ctrl+C.
Nie zatrzymywać portów 4314/4316/4321/18765/18766, GOLD72, Chrome ani Codex.
Nie używać killall, restartu usług, reset/clean lub kasowania stanu.

Przed merge rollback polega na pozostawieniu draftu niezatwierdzonego i
zatrzymaniu tylko nowej instancji. Oryginalne checkouty i usługi nie były
przełączane. Zachować prywatne Core records, UNKNOWN, risk reservations,
cache i receipts do rozliczenia. Nie kasować ich dla „naprawienia” statusu.
Po ewentualnym merge cofnięcie zmian na main wymaga osobno zatwierdzonego
revert PR i zachowania dowodów, bez przepisywania historii/baz.

## Decyzje wykonawcze i ich koszt

1. Zastosowano jawny git worktree fallback, bo API nie wybierało repo z /home/l.
   Koszt: ręcznie utrzymywana tożsamość/link do tego samego Git; jest zapisana.
2. Dodano local-zero v2 do istniejącego journala zamiast kopiować zależny od
   Nebiusa LocalZeroBinding. Koszt: dodatkowy kontrakt bezpieczeństwa; v1
   pozostaje osobno testowany, wymagany niezależny review.
3. Host przygotowuje wyłącznie przypięte C/runtime/cache przed approval.
   Koszt: lokalny zapis cache/kompilacja w zaufanej fazie prep; żaden target
   workspace/test/commit nie może wystąpić przed START.
4. Nowy Git v3 przypina faktycznie zainstalowany kwalifikowany binary, bez
   zmiany starego pinu v1. Koszt: inny host/binary wymaga nowej kwalifikacji.
5. Bez JDK/SDK nie wykonywano kompilacji Androida. Koszt: Kotlin/lint/APK
   pozostają nieweryfikowane; signed fixture nie zastępuje tych bramek.
6. Akceptację hosta oddzielono od przenośnego CI. Koszt: CI samo nie poświadcza
   native execution; trzeba jawnie uruchomić host_unified_*.py na qualified hoście.
7. Pełna regresja działa w namespace bez sieci zewnętrznej i rzeczywistych
   sekretów. Koszt: błędy środowiska należy diagnozować; pierwszy przebieg
   ujawnił nodev/dev-null config mask oraz ukryte istniejące zależności.
8. Prywatny interpreter QA używa zapieczętowanych, już zainstalowanych
   zależności NonZero, bez download/pip install. Koszt: wynik dotyczy tego
   dokładnego środowiska; wersje/METADATA/source hashes są zapisane.
9. Raw skan sekretów zachowuje FAIL dla odziedziczonych publicznych fixtures.
   Koszt: rozstrzygnięcie nie jest automatycznym PASS skanera; każda flaga ma
   pochodzenie, hash i redacted review. Nie ukryto kandydatów ani nie zmieniono
   testów po to, żeby uciszyć skaner.

Niezależny review i jego rozstrzygnięcia zostaną uzupełnione przed publikacją.
Przebieg home: U9_DEMO_HOME_GREEN, source9f5e6b437df5a9ebd711c257a092da102d12b038,
5 checks, lokalny commit0d0885cead94fa88efb93dea9bc69b291e0fbe15, restart signed readback.
Pełny wcześniejszy GREEN:2477 total/2472PASS+5SKIP,2062subtests; nowy rerun wymagany.
Node15/15, wheel+sdist2/2 PASS. Dokładne zakresy i źródła są w U9_QA_EVIDENCE.md.
Dowody prywatne są zachowane zgodnie ze zleceniem, poza repo, z ograniczonym dostępem.
