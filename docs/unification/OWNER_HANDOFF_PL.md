# ONE AIOA — odbiór właściciela, 2026-11-01

Stan: UNIFIED_CANDIDATE_READY / MAIN_MERGE_PENDING_OWNER_GO.
Końcowy kod `1cd2a91da0a1e8ef10186458327d4a115d9444a0`, capsule `2d587c399a4cba5342182bea7f17a7c3ea1dfe6775c1ccc6d938077aba642dfa`.
Python 2488: 2483 PASS +5 SKIP, 2138 subtests; native 42/42 PASS,
Node15/15 i wheel+sdist2/2 PASS. Independent review 0C/3I/1M; Important naprawione
RED→GREEN przez autora i końcowe regresje. Dokładne logi/komendy: U9_QA_EVIDENCE.md.
Raport nie zatwierdza merge, API, instalacji ani Android Actions.

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
Wymagane są już dostępne, zakwalifikowane Linux/Python3.12/cryptography41.0.7/Git/bwrap/cc/cgroups;
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
| U9 | PASS_POST_REVIEW_LOCAL_FIXTURE | Świeże regresje, source seals, pakiety i niezależny review |
| U10 | MAIN_MERGE_PENDING_OWNER_GO | Draft integracji po pełnym odbiorze; exact PR/head/base w końcowym przekazaniu; main bez promotion |

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

Draft integracji: [PR #27](https://github.com/luciferprosun/AIOA-spArkHAT/pull/27),
repo [luciferprosun/AIOA-spArkHAT](https://github.com/luciferprosun/AIOA-spArkHAT),
gałąź `integration/one-aioa-core-muse-mobile-20261101` → `main`.
Przy utworzeniu: head `0c32832a1b2e30c01216be68ec5e516281d3daf1`,
target/merge-base `de6fddb236db1702879fc65838c0c94b53d24cb2`, 216 plików,
24 484 additions / 60 deletions; pełna lista API zgadza się z lokalnym diffem.
Ten dopisek raportu powstaje po tym smoke; bieżący exact head, finalny smoke
i status automatycznego CodeQL są przypięte w opisie tego samego PR.
Wynik pełnych regresji nadal dotyczy kodu `1cd2a91...`; późniejsze commity
zmieniają wyłącznie raporty, przy identycznej capsule 76 plików.
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

10. Review i długa regresja mogły działać read-only na jednym zamrożonym SHA.
    Koszt: reviewer widział nieukończony wynik; przerwany f0 run jest INCOMPLETE,
    a publikację bramkują dopiero rzeczywiste wyniki nowego kodu.
11. I2: wybrano istniejący PendingHints i jawne zachowanie v2 ID; nie osłabiono
    session scope i nie dodano recovery authority. Koszt: stary rekord wymaga
    host reconciliation; limit128/błąd zapisu pozostawia lokalną blokadę.

12. Metadata /proc chronionych host PID sprawdzono read-only poza QA namespace,
    który odmawiał tego odczytu. Koszt: host-specific observation; nie jest
    to dowód izolowanej kontroli procesów ani zmiana uprawnień produktu.

## Niezależny review i rozstrzygnięcia

Review main de6fddb..f0ddb3e: 0 Critical, 3 Important, 1 Minor. Jeden autorski fix pass:
I1 shared revoke wszystkich nowych użyć warrantu (v1 consume/delegate/START,
Meta pre-key/transport); historyczne witness-free v1 i readback zachowano.
I2 jawny persisted agent-ID handoff po utracie sesji, bez Core mutation/retry.
I3 sealed read-only LICENSE i invariant dostępności wszystkich capsule files.
RED→GREEN i final suite: U9_QA_EVIDENCE.md. Poprawek nie przedstawiamy jako
ponownie niezależnie zrecenzowanych; cały pierwotny raport i granice:
INDEPENDENT_REVIEW.md.

Odroczone Minor M1: Android v2 nie wystawia kolejnej strony historii >16 zadań;
starsze ID należy przekazać hostowi. Brak fikcyjnego naprawienia/potwierdzenia UI.

Reviewer świadomie nie oceniał 13 granic. Decyzje autora i koszt, jeśli błędne:

1. Owner/CPL: NOT_BOUND; fixture nie nadaje produkcyjnej authority. Koszt:
   bez prawdziwego admission żadne produkcyjne wykonanie nie jest gotowe.
2. M12/Cockroach/storage: tylko istniejący COW fixture. Koszt: brak certyfikacji
   wieloprocesowej trwałości, migracji, backup/restore i load.
3. API/billing/LLaMA: brak paid calls/fallback/key loading, billing UNKNOWN.
   Koszt: rzeczywisty model i credits wymagają odrębnego potwierdzenia.
4. Remote Git: transport DENY. Publikacja tego PR przez Codex ma osobną zgodę
   i nie jest zdolnością AIOA. Koszt: credential/create-only/ancestry/retry/
   cancellation wymagają kwalifikacji przed zdalnym efektem agenta.
5. Install/SDK/JDK/system: plan i fake bounded artifact, installed=false.
   Koszt: realny installer/licencje/rollback pozostają niesprawdzone.
6. Android: SOURCE guards i przyszłe JVM tests, bez compile/APK/TLS/phone.
   Koszt: kod Kotlin/Keystore/Compose może wymagać poprawek po qualified build.
7. Chrome: poprawiono I3 mounts bez wykonania capture. Koszt: brak dowodu
   wizualnego/DOM/layout na aktualnym źródle.
8. Packaging: importy wheel/sdist PASS, unified wymaga source checkoutu.
   Koszt: bare-wheel startup na innym hoście nie jest certyfikowany.
9. Security: dokładny host/profile/binary i bounded fault tests. Koszt: brak
   pełnego pentestu, wszystkich kernel/same-UID wariantów i nowego audytu C.
10. Historia/transitive/legal: pełny inventory i zachowane notices, depth
    na trust paths. Koszt: nie jest to wyczerpujący audyt binarny/prawny.
11. Provenance/secrets: aktualny lokalny scan historii + źródeł i official
    Gradle checksums; brak unknown flag. Koszt: SDK i pełny supply chain nadal
    wymagają osobnych bramek; raw fixture FAIL nie staje się scanner PASS.
12. GitHub/main: bieżący readback, branch-only push/draft, bez cutover/dispatch.
    Koszt: duży merge wymaga exact owner GO, a potem smoke wynikowego main.
13. Final QA: nowe frozen-code regresje, package/seals/demo faktycznie green.
    Koszt: wynik dotyczy tych bajtów/hosta; drift wymaga ponownej oceny.

Dowody prywatne pozostają zachowane poza repo. Draft to PR #27; bieżący exact
head i target main są w końcowym przekazaniu i opisie tego PR. To unika
podmieniania SHA testów SHA późniejszego raportu. Publiczne raporty i rollback
nie nadają zgody na scalenie.
