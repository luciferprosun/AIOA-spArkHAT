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

U5 — wykonano ten sam Core-backed MCP adapter. Zachowano dotychczasowy Task Bus
GitHub READ. Namespace/origin/source/fingerprint/expiry oraz zamknięte payloady
są sprawdzane przed zapisem transportowego markera. LICENSE ma bounded nofollow
READ; WRITE/EXEC/Git/install są propozycjami REQUIRE_HUMAN. Wynik po lokalnej
zgodzie odczytuje się z tej samej misji/receipt. Nie powstał serwer MCP ani ledger.
Testy targeted: 5 PASS; dotychczasowe MCP: 99 PASS (ponowienie finalne w U9).

U6 — podpisane widoki v2 dodano do tego samego MobileGateway i klienta Android.
N1 /api/mobile/v1 zachowano. V2 wiąże transportowy request/link z kanoniczną
misją, sprawdza scope urządzenia PRZED jej odczytem i nie wystawia run/approve/
install/native_execute/github_write. Testy P-256: 5 PASS, w tym receipt po restarcie,
replay, cross-device i UNKNOWN/STOP. Kotlin ma typed DTO, istniejący MobileClient,
ViewModel i ekran (domyślnie English). Nowe testy JVM są źródłem do uruchomienia
na zakwalifikowanym hoście: NOT_RUN, brak JDK/SDK/kotlinc. Brak APK/telefonu/TLS.

U7 — jeden katalog provider/model, jawne OFFLINE_FIXTURE vs LIVE i availability.
Meta LIVE, billing, Nebius admission i Local LLaMA pozostają zablokowane/niezweryfikowane.
Nie ma fallbacku ani wczytania klucza jako dowodu uprawnienia. Ostatnie wywołanie
jest wyprowadzane z istniejącego Core receipt; lokalna receptura nie udaje
wywołania modelu. 3 targeted PASS; Local LLaMA to wyłącznie opis portu.

U8 — runtime.webapp --unified-offline uruchamia tę samą aplikację i Core.
Nowy panel w istniejącym web/ pokazuje pliki/diff/testy/receipt, dokładny digest,
STOP, GET readback i jawne niezależne rozliczenie UNKNOWN. Nie ponawia POST po ACK
loss. Ten sam serwer obsługuje podpisanego klienta v2, MCP READ i propozycje.
Private sandbox cache oraz fixture key są trwałe; nie są produkcyjnym admission.
Pierwsze testy: HTTP4, recovery2, cache2, rzeczywisty CLI+restart1, Node5 PASS.
Końcowe liczniki i komendy są wyłącznie w U9_QA_EVIDENCE.md.

Bezpieczny start z repo:
`PYTHONDONTWRITEBYTECODE=1 python3 -B -m runtime.webapp --unified-offline --host 127.0.0.1 --port 0`.
Proces poda rzeczywisty port. Istniejące instancje nie są przełączane ani zatrzymywane.

Poprawki test-first: oddzielono capability Git od sesji v1; sesja USD0 ogranicza
zasoby workera i risk reservation; odczyt receipt nie podąża za symlinkami i
odmawia hardlinków. Przy utracie ACK rzeczywistego efektu UNKNOWN rozlicza tylko
niezależny broker readback, nigdy powtórzenie operacji.

Granice: profil OFFLINE ma jawnie syntetyczne Core admission/model identity.
Rzeczywisty lokalny efekt i readback nie oznaczają produkcyjnego owner binding,
Meta LIVE, telefonu, TLS lub GitHub writes. Istniejące kontrakty v1/v2 zachowano;
nowa sesja USD0 ma odrębny schema. Jeden journal, governor i AUDIT/OUTBOX.

Przygotowanie hosta może kompilować wyłącznie stałe źródła natywnego brokera
i zapisać prywatne, przypięte snapshoty runtime/recipes przed zatwierdzeniem.
Żaden plik workspace, test ani commit nie jest wykonywany przed START.
Nie korzysta z sekretów lub prywatnych receipts starego Nebiusa.
