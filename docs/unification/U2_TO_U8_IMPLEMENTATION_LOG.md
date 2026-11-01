# U2–U8 — dziennik implementacji

U2 — zaimplementowano i zmierzono: istniejący `MissionService` przyjmuje typowany
plan SensorBridge. Lokalny owner zatwierdza dokładny digest. Istniejący
`CoreToolRoute`/`LocalSessionGrant` v2, `CoreServiceGuard` i `CoreIntentJournal`
walidują sesję, warrant, governor i START przed efektem. Ten sam
`LinuxSandboxBroker` tworzy świeży workspace w namespace, wykonuje create,
append i rename, uruchamia 5 zarejestrowanych testów Pythona i odczytuje
artefakty po zakończeniu procesów. Nie przyjmuje dowolnego kodu/argv/path od modelu.
Źródła/manifest, profil, limity, source SHA/capsule i task są częścią zgody.

U3 — zaimplementowano i zmierzono: selektywny kontrakt publishera oparty o
AG04 `git_publish.py` i pure Git object prediction z `git_transport.py`.
Zamiast zewnętrznego checkoutu W7A/venv wykorzystuje kanoniczne
`git_recipe.git_object` i `git_worker.git/environment/inspect_tree`.
Własny `LocalGitPlan` v3 wiąże wyłącznie pliki SensorBridge z uprzedniego
niezależnego readbacku i SHA-256 receipt. Nowa dokładna zgoda/START daje jeden
commit w nowym izolowanym repo. Tree, HEAD, branch, pełny staged diff, czysty
status i pliki są niezależnie weryfikowane. Nie dodaje remote ani credential helper.
Push/draft PR przez agenta: DENY, osobna dokładna zgoda i create-only transport
pozostają wymagane. Klasyfikacja 401/403/429/ACK-loss jest testowana offline;
nie jest dowodem wykonania zdalnego ani transportem produkcyjnym.

Nowy profil Git v3 używa faktycznie zainstalowanego Git 2.43.0,
Ubuntu `1:2.43.0-1ubuntu7.4`, `dpkg -V git` bez różnic,
SHA-256 `eb54b535467e0975c1284d4c4d08eea779aeb248a5d34b02e2ee171382e22201`.
Historyczny pin SyntheticGitPlan v1 pozostaje bez zmian. Inny binary blokuje
przygotowanie profilu; nie ma automatycznej aktualizacji pinów/instalacji.

U4 — zaimplementowano kontrakt i odczyt offline: typowana zależność pip,
exact version/hash/registry/license/workspace/venv/resources/network OFF.
Propozycja zapisuje się w tych samych rekordach MissionService/Core.
`OfflineInstallerAdapter` odczytuje rzeczywisty fixture artifact z nofollow,
single-link i kontrolą tożsamości. Wynik zawsze `OFFLINE_FAKE_INSTALLER`,
`installed=false`. Rzeczywista instalacja, pobieranie i SYSTEM_INSTALL pozostają
zablokowane; nie uzyskano zgody na licencje ani instalację hosta.

U5–U8: implementacja w toku; wyniki końcowe i dokładne komendy będą w U9.

Granice: profil OFFLINE ma jawnie syntetyczne Core admission/model identity.
Rzeczywisty lokalny efekt i readback nie oznaczają produkcyjnego owner binding,
Meta LIVE, telefonu, TLS lub GitHub writes. Istniejące kontrakty v1/v2 zachowano;
nowa sesja USD0 ma odrębny schema. Jeden journal, governor i AUDIT/OUTBOX.

Przygotowanie hosta może kompilować wyłącznie stałe źródła natywnego brokera
i zapisać prywatne, przypięte snapshoty runtime/recipes przed zatwierdzeniem.
Żaden plik workspace, test ani commit nie jest wykonywany przed START.
Nie korzysta z sekretów lub prywatnych receipts starego Nebiusa.
