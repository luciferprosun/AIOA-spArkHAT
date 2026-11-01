# N1 — rzeczywista macierz testów

Prywatne surowe logi: `/home/l/projects/META_MOBILE_PRIVATE_20261031/N1_20261031T212814Z/`.
Hashy i komend szukaj w `N1_EVIDENCE_INDEX.json`; nie kopiowano baz, tokenów,
APK ani logów rzeczywistej sieci. PASS dotyczy wykonanej warstwy, nie telefonu.

| Zestaw / komenda z TARGET | PASS | FAIL | SKIP | Poziom dowodu / log |
| --- | ---: | ---: | ---: | --- |
| Baseline `python3 -B -m unittest discover -s tests -p 'test_meta_*.py' -q` | 265 | 0 | 0 | Przed zmianami; BASE_META.log |
| Baseline Node UI / Core warrant / MCP | 7 / 13 / 99 | 0 | 0 | BASE_NODE / BASE_CORE / BASE_MCP.log |
| Końcowe `python3 -B -m unittest discover -s tests -p 'test_meta_*.py' -q` | **323** | 0 | 0 | N7_META.log, 56.418s; zawiera58 nowych testów N1 |
| `python3 -B -m unittest discover -s tests -p test_core_warrant.py -q` | 13 | 0 | 0 | N7_CORE.log |
| `python3 -B -m unittest discover -s tests -p 'test_mcp_*.py' -q` | 99 | 0 | 0 | N7_MCP.log |
| `python3 -B -m unittest discover -s tests -p test_governor_audit_compatibility.py -q` | 4 | 0 | 0 | N7_AUDIT_COMPAT.log |
| `python3 -B -m unittest discover -s tests -p test_memory_patch_persistence_ports.py -q` | 26 | 0 | 0 | N7_NATIVE_PORTS.log |
| `python3 -B -m unittest discover -s tests -p test_memory_patch_lifecycle.py -q` | 24 | 0 | 0 | N7_NATIVE_LIFECYCLE.log |
| `node --test tests/meta_mission_ui.test.cjs tests/meta_mobile_ui.test.cjs` | **10** | 0 | 0 | 7 istniejących UI +3 Android SOURCE; N7_NODE.log |
| Companion `python3 -B -m pytest -q -p no:cacheprovider tests/gateway/test_auth.py tests/gateway/test_host_proof.py tests/gateway/test_server.py` | **51** | 0 | 0 | N5_COMPANION_ISOLATED.log; prywatna kopia źródła, plugin autoload/bytecode wyłączone, brak importu do TARGET |
| `python3 -B -m runtime.mobile_gateway.build_handoff --check` | MATCH | 0 | — | deterministyczny manifest; bez Gradle |
| Ostatnia kontrola Android SOURCE / build-handoff | 10 / 3 | 0 | 0 | N8_ANDROID_SOURCE_GREEN / N8_BUILD_HANDOFF_GREEN; podzbiory Meta, bez podwójnego liczenia |
| `python3 -B -m runtime.mobile_gateway.doctor` | poprawne BLOCKED | 0 | — | oczekiwany exit2, pasywny kernel port metadata, żadna zmiana sieci |
| `python3 -B tests/demo_mobile_fixture.py` | FIXTURE PASS | 0 | — | rzeczywiste podpisane HTTP127.0.0.1:0, istniejący Core, temporary state/keys, zamknięcie serwera |
| Kotlin/JVM | **NOT_RUN (10 przygotowanych)** | — | — | Brak JDK/SDK; nie liczyć jako testów wykonanych |
| Gradle/lint/assemble/signature/phone/TLS LIVE | **NOT_RUN / BLOCKED** | — | — | Brak toolchainu/kwalifikowanego edge/APK/urządzenia; nie „skipped PASS” |

Razem TARGET Python: **489 wykonanych, 0 FAIL, 0 SKIP**; dodatkowo51 Companion
w kopii. Nie sumuj podzbiorów poniżej ponownie do323 Meta.

## Nowe testy N1 w zestawie Meta

| Plik | Liczba | Zakres |
| --- | ---: | --- |
| test_meta_mobile_wire.py | 7 | canonical UTF8/duplikaty/float/bounds/depth, P256 DER, dokładny origin i route, raw body digest |
| test_meta_mobile_gateway.py | 20 | autentyczność fixture principal, prebound code/expiry, replay/revoke/restart/source/task/scope, wrong-device, host key rotation, provider drift, native audit/outbox,128 misji na stronach |
| test_meta_mobile_http.py | 9 | realny loopback HTTP/Core E2E, replay/CSRF/CORS/duplicate headers, lost ACK, reopen, crash po approval, zły receipt |
| test_meta_mobile_android.py | 10 | **SOURCE only**: pakiet/build/manifest, brak sekretów, TLS/retry, wire vector, scroll/lifecycle, reenrollment, expiry i jawne cache ID |
| test_meta_mobile_doctor.py | 3 | redakcja i odmowa fałszywej gotowości z niezweryfikowanych danych |
| test_meta_mobile_build.py | 3 | komplet deterministycznego manifestu, drift i odrzucenie nieznanego wrappera |
| test_meta_mobile_source_seal.py | 2 | zmiana bytes kapsuły i odmowa symlink przed odczytem |
| test_meta_mobile_chrome_mounts.py | 2 | command construction; wyłącznie określone źródła, bez cache/APK, odmowa symlink; bez uruchomienia przeglądarki |
| test_meta_mission_batch_read.py | 2 | zgodna projekcja w jednej transakcji, scope/principal/bounds/duplicates/missing row |

## RED → GREEN i ograniczenia

Zachowano logi pierwotnego RED kontraktu/bramki/HTTP/Android oraz N7_FIX_GATEWAY_RED
(PROVENANCE_CORRUPT, stare credentials przy nowym audience,413 dla128 misji),
N7_FIX_ANDROID_SOURCE_RED, N7_BATCH_RED, N7_PROVIDER_DRIFT_RED i SOURCE_MOUNTS_RED.
Pierwsza próba nowego testu symlink miała błąd składni samego testu; osobny log
TEST_SYNTAX_ERROR zachowano, po poprawieniu testu uzyskano rzeczywisty RED
„ValueError not raised”, następnie GREEN. Nie uznano SyntaxError za dowód defektu
produkcyjnego. Końcowe logi wyżej są zielone po jednej rundzie poprawek.

N7 test128 historii zasila istniejące Core records syntetyczną historią bez
efektów modelu/narzędzi; strony naprawdę przechodzą podpisaną bramkę i Core READ.
Pełny pojedynczy E2E w osobnym teście używa realnych transakcji fixture, host-side
approval, zużycia warrantu i niezależnego porównania receipt/hash; `verified=false`.
Publiczny model ani publiczna przeglądarka nie uczestniczą w tych dowodach.

Po pełnej regresji dopięto publiczny wektor JVM do standardowego
`app/src/test/resources`, zamiast niezapieczętowanego całego zewnętrznego drzewa
fixtures. RED zasobu zachowano, następnie powtórzono10 SOURCE i3 build-handoff
oraz MATCH manifestu. Wszystkie46 plików runtime/source capsule/tested helpers
pozostały byte-identical do pełnej zielonej regresji; zmieniły się wyłącznie
deklaracja zasobów testowych, ich publiczna kopia i odpowiadające hashe/wejściowe
asercje. To nadal nie wykonanie JVM ani Gradle.
