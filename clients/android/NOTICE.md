# Pochodzenie / notices

Nowy neutralny kod klienta w kanonicznym AIOA (MIT, patrz główny LICENSE).
Zachowuje pakiet Companion i fakty kontraktu, bez kopiowania kodu Companion/AgentLab,
których licencja projektu nie została odnaleziona. Nie importuje ich Gateway, bazy,
owner identity ani zasobów prywatnych. Autor zmian: Codex na zlecenie operatora, N1.

Jedyny przeniesiony plik binarny to niezmieniony upstream Gradle 8.13 wrapper JAR,
43 705 bajtów, SHA-256 `81a82aaea5abcc8ff68b3dfcb58b3c3c429378efd98e7433460610fecd7ae45f`.
Pochodzi z lokalnego cache Companion, zweryfikowano go niezależnie względem
[oficjalnych sum Gradle](https://gradle.org/release-checksums/#v8.13).
Zachowano dołączony META-INF/LICENSE w `licenses/gradle-wrapper-LICENSE.txt`.
Gradle: Copyright 2015 the original author or authors; Apache-2.0.
Własny launcher `gradlew` nie jest skopiowanym skryptem projektu źródłowego.

Zależności są zadeklarowane, nie pobrane: AndroidX/Compose (Apache-2.0),
Kotlin/kotlinx (Apache-2.0), OkHttp (Apache-2.0), JUnit4 (EPL-1.0).
Pełny audyt transitive artifacts i notices następuje po rzeczywistym buildzie;
nie jest dowodem ukończonej kompilacji ani zgody na publikację APK.
