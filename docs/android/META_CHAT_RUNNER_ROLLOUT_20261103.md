# Rozpoznana zmiana runnera — Cosmic4 Meta chat

Pierwsza próba41709088611, source86a472247cd4082a76a9de786d157b2b97c6601a, zatrzymała się na IMAGE_CHECK, przed checkout/JDK/Gradle. Brak APK; nie jest to błąd Kotlin ani PASS builda.

Dostarczono ubuntu-22.04/ImageVersion20261101.347.1 zamiast20261026.341.1. Natywne root-owned imagedata i env są zgodne:20261101.347.1; SHA-256 metadanych `29096352b00e4ed83a17ca7c04e54650ea3197842d07e95901ff1a82a21817b3`. Nie zmieniono/ukryto tych danych.

Oficjalne wydanie: [actions/runner-images ubuntu22/20261101.347](https://github.com/actions/runner-images/releases/tag/ubuntu22%2F20261101.347), opublikowane2026-11-02; OS22.04.5LTS, kernel6.8.0-1070-azure, ImageVersion20261101.347.1. To potwierdza identyfikację wydania, nie certyfikację bezpieczeństwa całego runnera.

Minimalna naprawa w istniejącym workflow: osobny `DEBUG_UBUNTU22_V2` przyjmuje tylko tę dokładną, zgodną parę env/metadata oraz zaobserwowany hash. Żaden wyjątek rozbieżności v1 nie jest dziedziczony. STRICT i oba v1 pozostają bez zmian. JDK17.0.21+9,SDK36rev2/build-tools35.0.0/Gradle8.13/SDK inventory9f81aed02ae39189e55282cd66a561969590f2c032a868beaa1afc7e3b51e793, source/actor/workflow/ref,35min,128MiB,1dzień,persistent cert nadal obowiązują. Odmienny SDK pozostaje odmową, nie nową automatycznie zaakceptowaną bazą.

Zakres obecnego polecenia obejmuje samodzielną naprawę CI i powtarzalne bezpłatne buildy. Nowa próba jest uzasadniona oficjalnie potwierdzoną zmianą obrazu i konkretnym patchem; nie jest ślepym retry. Nie zmieniono ustawień CodeQL ani budżetów. Konto billing API jest niedostępne dla obecnego OAuth; standardowy publiczny runner jest bezpłatny zgodnie z [oficjalną dokumentacją](https://docs.github.com/en/actions/concepts/billing-and-usage). Ostatni wcześniejszy realny build raportował billable0; aktualne artefakty repo przed próbą miałyłącznie23,053,381B.

RED: nieznany nowy profil został odrzucony. GREEN:56 testów konfiguracji/metadata/source/SDK/STRICT/v1 PASS. Pierwotne logi zachowano prywatnie w CI_41709088611_FAILED.log i CI_41709088611_STATUS.json. Płatna inferencja pozostaje NOT_AUTHORIZED.
