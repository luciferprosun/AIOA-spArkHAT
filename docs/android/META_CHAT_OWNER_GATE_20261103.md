# Cosmic4 Meta chat — zakres zgody właściciela,2026-11-03

Źródło: polecenie właściciela w tej sesji i lokalny PDF `AIOA_Cosmic4_Meta_Muse_FINAL_PROMPT_2026-11-03.pdf` (7 stron). Historia zgód zezwala na prace w istniejącej aplikacji, branch/worktree, testy, kontrolowany bezpłatny DEBUG CI i aktualizację tego samego pakietu przez USB bez usuwania danych. Aktualne polecenie nie zezwala na merge do main ani płatny Meta smoke bez osobnej dokładnej zgody.

- SOURCE: nowa gałąź `feat/cosmic4-muse-chat-20261103`, baza4c00d7b; nie zmieniać zamrożonego działającego Native5fae310 ani jego PR39.
- UPDATE: pakiet `eu.sparkhat.aioa.companion.cosmic4`,401/4.1.0-cosmic, dotychczasowy certyfikat3aa33eda63d3516010ddbf0fe0ff8de6b6dab6f6fc48088ee2592bde3b627bc4.
- BUILD: istniejący ręczny workflow, standardowy publiczny ubuntu-22.04, kontrolowany DEBUG_UBUNTU22_V1/ImageVersion20261026.341.1; STRICT nadal domyślny. Istniejąca jawna rozbieżność metadanych i przypięty SDK pozostają bez osłabiania.35min/run,128MiB, retencja1dzień. Actions ostatniego buildu41688400577 raportują billable Ubuntu total_ms0. Bez CodeQL migration, paid runner, licencji automatycznych i nowych usług.
- PUBLISH: oczyszczony kod i artefakt DEBUG w istniejącym publicznym repo; jeden kumulatywny draft PR do przeglądu. Bez merge.
- HOST: po izolowanych testach rzeczywista autoryzacja PolicyKit i kontrolowana wymiana wyłącznie Native4317 przy zachowaniu stanu, scope, host/TLS/transport keys, Tailscale i revocations.4314/4316/4321 chronione.
- FINANCE: **NOT_AUTHORIZED**. Żadna płatna próba Meta nie została zlecona w tym etapie. Przed pierwszym wywołaniem przygotować dokładne task/request/source/model/limit<=0.05USD/one-attempt i uzyskać osobną zgodę. Ta zgoda musi przejść przez prywatny kanał operatora i zapisany Core warrant, nie HTTP/model/env.
- NATIVE WORKER/GITHUB WRITE: **NOT_AUTHORIZED / NOT_BOUND**. P1 pozostaje BLOCKED, jeżeli istniejąca natywna ścieżka READ nie spełnia kontraktu.

Nie są to twierdzenia o zakończeniu kompilacji, aktualizacji telefonu lub LIVE. Dowody należy dopisać po faktycznym wykonaniu.

## Uzupełnienie zgody — naprawa czatu i APK 4.1.1, 2026-11-04

Rzeczywiste polecenia właściciela w tej sesji: „nie film ja wykonam pozniej […] napraw tylko chat i pozniej dam nowy prompt” oraz „w takim razie daj mi ostatnia narazie wersje apk i wtedy przejdziemy dalej”. Obowiązuje wcześniejsza rozszerzona zgoda na niezbędne poprawki aplikacji, bezpłatny kontrolowany CI, ten sam signer i dostarczenie APK. Film i dalsze funkcje są wyłączone z bieżącego etapu.

- UPDATE: wyłącznie Cosmic4, 402/4.1.1-cosmic, ten sam package i certyfikat. Nie zmieniać Keystore, zapisanych danych parowania, TLS, Tailscale ani PolicyKit.
- REPAIR: po podpisanym odczycie UNKNOWN użytkownik może świadomie rozpocząć pustą, osobną rozmowę. Poprzedni rekord i finansowy UNKNOWN pozostają w Core, a publiczny identyfikator zostaje zachowany lokalnie. Ta akcja nie wysyła wiadomości, nie ponawia POST i nie udziela zgody finansowej.
- BUILD: istniejący `DEBUG_UBUNTU22_V2` i uprzednio zweryfikowany dokładny zestaw `20261026.341.1|20261101.347.1`, niezmieniony przypięty SDK, hash workflow, JDK17/Gradle, standardowy publiczny runner, 35 minut, APK do128MiB, retencja1dzień. Inny obraz lub SDK oznacza odmowę. Bez akceptacji nowych licencji, zmiany CodeQL, płatnego runnera lub nowych usług.
- HOST: poprawka języka i minimalnego reasoning została osobno zweryfikowana na b7f4002; nowy APK nie oznacza automatycznego nowego wdrożenia hosta ani fizycznego odbioru aktualizacji.
- FINANCE / MERGE / FILM: brak nowej zgody na płatną próbę modelu, merge do main, publikację filmu lub formalne submission. Każdy późniejszy płatny test wymaga własnego dokładnego zatwierdzenia w istniejącym natywnym kanale.

Wyniki rzeczywistej kompilacji i sumy gotowego APK należy przekazać w oddzielnym raporcie wydania; ten zapis zgody nie jest wynikiem testu.
