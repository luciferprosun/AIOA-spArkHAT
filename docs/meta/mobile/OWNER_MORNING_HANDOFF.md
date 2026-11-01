# Poranny handoff N1

Przygotowałem klienta Android0.2.0-n1 w tym samym pakiecie oraz podpisany adapter do istniejącego AIOA Core i MissionService.
Lokalny fixture faktycznie przechodzi enrollment, Preview, osobną zgodę hosta, Core Run, receipt/evidence i scoped STOP, bez kosztu modelu.
Pierwszy bezpieczny test rano: z TARGET uruchom `python3 -B tests/demo_mobile_fixture.py` i sprawdź `HOST_GATEWAY_MOBILE_FIXTURE_PASS` oraz `verified:false`.
Nowego APK nie zbudowano, bo brak kompletnego JDK17/SDK36/Gradle8.13; build-handoff i hashe są w dokumentacji.
Companion, AgentLab, Nebius i stary APK zachowano, niczego nie wypchnięto ani nie zainstalowano na telefonie.
Na Xiaomi możesz przygotować oficjalny Tailscale i porównać nowe urządzenie z Linuxem według `XIAOMI_13T_PRO_SETUP_PL.md`.
Przed rzeczywistym parowaniem potrzebne są kwalifikowany HTTPS/TLS edge, jego natywny adapter w jednej aplikacji, niezależne piny hosta, realne owner admission oraz zweryfikowany build i podpis APK.
Obecny kod celowo blokuje produkcyjny enrollment, więc sama zmiana adresu lub włączenie Serve nie wystarczy.
Telefon może proponować i odczytywać własne misje oraz żądać STOP, ale nie nadaje Run, approval ani budżetu.
Przy UNKNOWN wykonaj GET/readback lub rozlicz zadanie na hoście, bez ponawiania POST.
