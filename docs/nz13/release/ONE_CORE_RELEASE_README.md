# Jeden AIOA spArkHAT Core

Punktem odniesienia produktu jest E18 e23632302b51e8371298dcc801f01f9842a74003 i drzewo 83cfe482dad9ae301548dea9ada8a5b4a2ad6c08. AIOA składa się z jednego Core, jednego rejestru intencji i autoryzacji oraz adapterów NonZero. Wheel zawiera dystrybucję aioa-sparkhat, a CLI, web i interfejs operatora używają tych samych kontraktów.

WorkerPort przyjmuje zatwierdzony kontekst zadania i zwraca dane kandydata. W prywatnym profilu fixture można wymienić adapter zgodny z WorkerPort i zachować ten sam schemat wejścia oraz PatchSet. Wybór modelu w podpisanym profilu Native przechodzi osobną kontrolę kwalifikacji. Core wyznacza zakres, sandbox sprawdza PatchSet, a ograniczona pętla naprawy podlega pierwotnej polityce i limitom.

READ zbiera dane i podlega redakcji. ADVISORY niesie propozycję bez skutku. WRITE wymaga aktualnego owner warrant, dokładnego zakresu i receipt. Wyniki fixture pozostają lokalnymi dowodami, a kwalifikacja LIVE wymaga niezależnej obserwacji efektu.

Macierz 69 pozycji w RELEASE_CAPABILITY_MATRIX.csv ma SHA-256 1262ce9232a6bc6f98fb7c3c5226bb7688688009450ccfadf4add3d1e9d3b7cc. Wyniki klas E18 oraz warunki hosta są w pakiecie odbiorczym.

Odczyt statusu w profilu offline ładuje konfigurację Native dopiero przy jej jawnym użyciu. Próby bazowej instalacji i odmowy błędnego typu są w skorygowanym checkpointcie E18.
