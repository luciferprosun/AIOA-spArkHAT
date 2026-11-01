# G7 — niezależny review i jeden cykl poprawek

Niezależny reviewer sprawdził cały zakres
`6216b16f22da167b401f8611291264d73eaacb40..042469a362a5e9675ab9056bbca94b9e0ca56b02`.
Werdykt pierwotny: **With fixes**,0 Critical,5 Important,1 Minor. Prywatny
pełny raport: `INDEPENDENT_REVIEW.md` w katalogu evidence zadania. Reviewer
nie instalował niczego, nie używał sieci ani dysku zewnętrznego; uruchomił34
testy i własne małe reprodukcje. Nie zlecono drugiego review.

Właściciel zmian ponownie ocenił wpływ ustaleń. M1 podniesiono do Important:
ignorowany limit wrapper JVM i `user.home` dotyka budżetu4GiB i izolacji
wyjścia, więc nie jest tylko kosmetyką. Wszystkie6 ustaleń weszło do jednego
cyklu RED→GREEN; nie pozostawiono odroczonego Minor.

| Ustalenie | Poprawka | Regresja w `tests/test_android_review_regressions.py` |
|---|---|---|
| I1 manifest >64KiB | Osobny limit16MiB komponentów, weryfikacja przed promocją; authority nadal64KiB | `test_package_scale_manifest_is_readable_after_promotion_and_reuse` —450 plików, ponowne użycie, twardy limit pinów |
| I2 samopotwierdzający manifest | Oczekiwane inventory z cache archiwum o przypiętym SHA256, ten sam plan materializacji, odczyt z FD, ponowny hash i identity check | `test_replaced_binary_and_rewritten_inventory_cannot_claim_archive_provenance`, `test_missing_or_corrupt_archive_cannot_authenticate_an_installed_component`, `test_readonly_archive_inventory_matches_materialized_tar_file_aliases` |
| I3 ignorowane override SDK/Gradle | Odrzucenie ignored Android inputs i aktywnych init/properties w Gradle user home przed uruchomieniem narzędzi | `test_ignored_sdk_override_is_rejected_even_when_git_status_is_clean`, `test_gradle_user_configuration_is_rejected_before_any_tool_process` |
| I4 SIGTERM osieroca potomka | SIGTERM/SIGINT ustawiają cancellation, wykonywany bounded cleanup tylko własnej grupy; handlery przywracane | `test_sigterm_supervisor_cleans_its_owned_child_and_restores_handlers` — pidfd zabezpiecza sprzątanie fixture |
| I5 obcy APK dostaje source SHA z nazwy katalogu | Standalone zawsze `source_binding:UNKNOWN`; tylko kontrolowany udany build dopina źródło/invocation/log i report digests | `test_artifact_reuse_under_new_sha_cannot_gain_new_source_provenance` |
| M1 → Important, nieskuteczne JAVA_OPTS | `JDK_JAVA_OPTIONS` dla wrappera/SDK, jawne JVM home/tmp we własnym wyjściu; bez zmiany klienta N1 | `test_existing_launcher_receives_jvm_limits_through_a_java_native_variable` |

Dziesięć nowych przypadków najpierw odtworzyło błędy (wraz z podprzypadkami),
potem przeszło. Pierwsza próba GREEN nadal zgłaszała `FileNotFoundError` dla
brakującego archiwum zamiast typowanej odmowy; poprawiono to w tej samej rundzie.
Dodano też test komunikatu Java17 o JDK_JAVA_OPTIONS, aby po poprawce JVM nie
mylić tego oczekiwanego stderr z błędem wersji sdkmanagera. Inne komunikaty
i niewłaściwe wersje pozostają blokadą.
Końcowy zestaw tooling: **44 PASS,0 FAIL,0 SKIP**. RED i nieudane pośrednie
GREEN pozostają w prywatnych logach, bez nadpisywania ich nazwą PASS.

Końcowy werdykt autora dla zakresu narzędzi: **PASS_OFFLINE**, kwalifikacja
instalacji/build/CI nadal **BLOCKED/NOT_RUN**. To nie jest twierdzenie o nowym
niezależnym zatwierdzeniu poprawek; weryfikacją poprawek są RED→GREEN i pełne
właściwe regresje, bez ponownego review.

## Rozstrzygnięcia „Declined to judge”

1. Faktyczna kondycja WD/USB/SMART i autentyczna integracja publishera:
   pozostają BLOCKED, nie zastąpiono testem fixture. Koszt błędnego odbioru:
   ryzyko danych; żaden zapis na woluminie nie jest autoryzowany wynikiem unit.
2. Aktualność wszystkich upstream dostawców/licencji/bezpieczeństwa akcji:
   metadata i piny zbadano osobno, bez pełnego audytu dostawców ani przyjęcia
   licencji. Koszt: właściciel musi ponownie ocenić dostawców przed runem.
3. Rzeczywiste rozmiary archiwów, zgodność JDK/SDK/Gradle i wynik kompilacji:
   nie wykonano pobrań/buildu.450 plików fixture sprawdza błąd limitu, nie
   zastępuje rzeczywistego pakietu. Koszt: pierwsza prawdziwa instalacja może
   ujawnić dalszą niezgodność; nie ma deklaracji TOOLCHAIN/CI PASS.
4. Pełne transitive byte locking: zachowano jawną limitację N1 bez jego
   przebudowy. Koszt: brak dowodu reprodukcji bajt w bajt; manifest komponentu
   i aktywne konfiguracje mimo tego zostały naprawione, nie pominięte.
5. Poprzedni N1/Core/MCP i historyczne LIVE: zachowano kod i wykonano
   właściwe regresje, bez nowego audytu całej historii. Koszt: nie jest to
   certyfikacja M12 ani potwierdzenie dawnych LIVE/telefonu.
6. Telefon, release signing, continuity aktualizacji, Tailscale, V2 i assety:
   poza implementacją, jawne BLOCKED/SPECIFICATION_ONLY. Koszt: brak gotowego
   Android E2E; właściciel musi odebrać te osobne etapy.
7. Pełne przejęcie roota/repo/evidence przez ten sam UID: nie deklarujemy
   odporności na przejęty host. Poprawka I2 zabezpiecza podmianę toolchainu
   przy zachowaniu zaufanego repo/katalogu. Koszt: native host i jego źródła
   pozostają częścią granicy zaufania, bez nowego sandboxa.
8. Końcowy handoff, odziedziczona historia i push/PR: kontrole autora po review,
   zgodnie z planem. Koszt: niezależny reviewer nie odbiera późniejszej
   dokumentacji ani12 dawnych commitów jako nowej implementacji. Publikacja
   wymaga osobnego skanu wszystkich wychodzących blobów i bezpiecznego ref.
