# NV06 — osobista pamięć zweryfikowanych różnic

To rozszerzenie istniejących `AgentRuntime`, `LiteCPL`, `NativeLearning`,
`MemoryPatchService` i `MemoryDynamics`. Nie tworzy nowej bazy, schematu,
harmonogramu ani dostawcy CPL. Domyślna konfiguracja bez nowego bindingu
zachowuje dotychczasowy format manifestu, delt i zachowanie NV01–NV05.

## Właściciel i oddzielne dane

`PersonalDeltaPolicy` wskazuje już dopuszczony przez Core `OwnerScope`.
`personal_space_ref` jest deterministyczną nazwą tego domyślnego miejsca;
nie zależy od modelu ani sesji. Zastosowano istniejącą lokalną tożsamość
operatora i zapieczętowane `CorePrincipal`. Nie dodano logowania dla usługi
wielu użytkowników.

Kanoniczne źródła nadal przychodzą przez `CANONICAL_EVIDENCE`, ręcznie
zatwierdzony kontekst przez `OWNER_CONTEXT`, a małe zweryfikowane delty przez
`VERIFIED_DELTA_ADVISORY` w natywnych rekordach `LEARNING`. Osobista nazwa
miejsca nie jest dodatkowym zarejestrowanym HAT-em. Istniejący wybór HAT
dopuszcza jeden aktywny HAT do danego zadania. Grant wskazuje dozwolone HAT-y
i stały dopuszczony HAT kotwiczący rekord zgody w istniejącym RLS.

Rekordy i liczniki są najpierw ograniczane przez natywny scope. W obrębie
tego scope odczyt konkretnego zadania wybiera jego domenę. Limity rekordów
pozostają wspólne dla tego miejsca; nie uruchomiono migracji ani live SQL.

## Zgoda na zapis

| Profil | Automatyczne zachowanie |
|---|---|
| OFF / brak grantu | Bez zapisów uczenia i bez osobistych delt w kontekście aktora. |
| MANUAL | Bez automatycznych zapisów. Dotychczasowe challenge → owner decision → commit → activate pozostają jedyną ścieżką ręcznego zatwierdzenia patcha. |
| AUTO_VERIFIED_SCOPED | Tylko niezależnie zweryfikowane, aktualne, dopuszczone w HAT i mieszczące się w limicie delty; bez materiału zakazanego przez politykę sekretów. |

`PersonalDeltaAccess.set_consent` to jawna operacja Core wymagająca
`OWNER_APPROVAL` od dokładnego właściciela. Zapisuje wersję przez CAS
w istniejącej transakcji `MANAGE`. Nie jest parserem tekstu modelu.
Dozwolone HAT-y i termin ważności (najwyżej rok) muszą być podane jawnie.
Logowanie ani samo skonfigurowanie polityki nie tworzy grantu.

Każdy automatyczny zapis sprawdza aktualny grant w **tej samej transakcji**.
Przed commit sprawdzane są również liczba rekordów i suma ich logicznych
bajtów. Limit bajtów wynosi domyślnie 262144 i nie może przekroczyć limitu
przekazanego natywnego HAT-a. Przepełnienie wycofuje całą transakcję.
Zmiana źródła i jego dostępność są ponownie sprawdzane przy zapisie delty.
Cofnięcie zgody zastępuje jeden rekord także przy wyczerpanym limicie.
Historia pozostaje dostępna właścicielowi do audytu. OFF/cofnięcie/wygaśnięcie
ukrywają ją przed aktorem; nic nie jest automatycznie usuwane. W MANUAL
historyczny odczyt nadal przestrzega bramek czasu/DVM, bez zapisów wyniku
rankingowego ani nowych obowiązków. Takie niedopuszczalne rekordy odpadają.

Detektor wykorzystuje istniejące `critical_loop.redaction` oraz chronione
wartości dostarczone przez Core w `private_values`. Sprawdza rzeczywiste
wartości tekstowe, przed serializacją. Odmowa nie zamienia tekstu w stratną,
ocenzurowaną „wiedzę”. To kontrola zdefiniowanych wzorców i znanych wartości,
nie deklaracja rozpoznawania każdego możliwego sekretu.

## Weryfikacja i znaczenie

`review_claim` rozróżnia trzy tryby:

- CPL_ONLY: wymaga propozycji z krytyki; zgodność krytyków daje zero niezależnych dowodów.
- HAT_ONLY: wybiera jedyną wspieraną, aktualną korektę z dopuszczonych źródeł, bez krytyków.
- HYBRID: propozycja CPL przechodzi te same niezależne kontrole Core.

Każdy tryb kończy przygotowanie korekty na natywnych bramkach scope,
provenance, czasu, konfliktów i co najmniej dwóch wymaganych metodach
z dwóch rodzin źródeł. Nie ma domyślnego oracle dla dowolnego tekstu.

`EpistemicDelta` zachowuje istniejące claimy, identyfikatory dowodów,
wersje, daty, historię i brak uprawnień wykonawczych. Dodano typowane
`REPLACE`, `ADD_MISSING_CONDITION`, `QUALIFY`, `RETRACT`, wymagany warunek
oraz ograniczone tagi. `minimal_delta` jest projekcją kompletnego poprawionego
claimu; nie zapisuje kolejnej kopii tekstu. Warunek dla ADD/QUALIFY musi
występować w poprawionym znaczeniu. Operacja natywnego pakietu zastępuje
cały mały claim; rodzaj semantyczny opisuje, dlaczego znaczenie się zmieniło.

Domyślne `_claim` zachowuje negację, liczby, jednostki, daty i warunki;
normalizuje tylko NFC i skrajne białe znaki. Opcjonalne `DomainSemantics`
zawiera najwyżej 16 ręcznie przejrzanych aliasów, związanych z dokładnym
właścicielem, HAT-em, zadaniem, wersjami źródeł i terminem. Alias interpretuje
wejście, a jego kanoniczny claim nadal wymaga niezależnej weryfikacji.
Nie ma dopasowania przybliżonego, łańcuchów aliasów ani ekwiwalencji
wyznaczanej przez model. Tagi nie zastępują claimu i dowodów.

Tożsamość wiedzy nadal wyklucza aktora. Istniejące pole `model` zachowuje
pochodzenie pierwszego zaobserwowania; nie tworzy osobnej prawdy dla modelu.
Rekord `OVERLAY` referuje deltę, a rekord `TRAIL` referuje jej istniejący ID.

## Pakiet i limit powrotu do aktora

Wykorzystano `NativeCorrectionPacket`, `RequiredCorrection`,
`NativePacketIntegrity`, `NativeVerifier` i `NativeAnswerAssembler`.
Małe `build_required` umożliwia połączenie niezależnie popartego warunku
z natywnym pakietem również wtedy, gdy wcześniejszy detektor leksykalny
nie potrafił sam zaproponować poprawki. Natywne wsparcie poprawionego claimu
jest wymagane. Podpis pakietu dowodzi integralności, nie prawdy ani zgody.

Projekcja dla aktora zawiera claim, korektę, warunek, dowody, wersje,
czas, powód i status. Limit wynosi 4096 bajtów kanonicznego JSON. Nie zawiera
HMAC, nonce zgody, pełnego czatu ani ukrytego toku rozumowania. Sam słownik
review nie daje potwierdzenia: tworzenie pakietu ponownie czyta dowody.

Istniejące CPL nadal wykonuje OpenRouter DRAFTING + 3 critics + REVISING.
To inny aktor niż początkowy NVIDIA. Nowa osobista kompozycja pozwala CPL
zwrócić wyłącznie kandydata; zwykły tick nie zapisuje go automatycznie przed
zamknięciem pętli. Starszy binding bez osobistej polityki zachowuje NV04.

`ActorRepairBudget` dopuszcza dokładnie jedną próbę. Istniejący assembler
otrzymał opcjonalny limit 1, przy zachowanym starszym domyślnym limicie 2.
`LiteJournal.reserve_actor_repair` zapisuje unikalny trace naprawy razem
z rezerwacją budżetu przed transportem. FAILED/RELEASED/UNKNOWN nie
przywracają tej próby. UNKNOWN nadal zatrzymuje przyszłe wywołania
i pozostaje widoczny po restarcie. Samo porównanie kodu bez tej trwałej
rezerwacji nie jest deklarowane jako ochrona restartu.

NV06 przygotowuje te kontrakty. Po przejściu G06 NV07 łączy je z pytaniem
użytkownika i tym samym portem aktora oraz wykonuje pełną demonstrację.

## Pomiary i granice

`storage_metrics` liczy logiczne bajty kanonicznej serializacji: deltę,
referencje/tagi, audyt EPISODE, model OVERLAY i PHEROMONE_EVENT. Dwie pierwsze
wartości sumują się do całego payloadu delty; pozostałe liczą całe rekordy
natywne, bez pochodnego pola digest. To nie są strony SQL, miejsce zajęte
na dysku ani oszczędność kompresji. Nie zmieniono żadnego SQL ani zależności.
LIVE Cockroach pozostaje BLOCKED_EXTERNAL.
