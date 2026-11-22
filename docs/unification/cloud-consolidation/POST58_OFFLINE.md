# Uzupełnienia offline po scaleniu PR #58

Zakres kandydata obejmuje cztery luki, odtworzone na `main` `ebed8691f84781a5f0413374421a257f8a29b6d1`. Macierz parytetu dalej używa ID autora audytu. Statusy #2, #17 i #41 pozostają `PARTIAL`.

- **#2.** Diagnostyka `OwnedCodexProtocol` odrzuca przepełnienie liczb zmiennoprzecinkowych, obcą wersję JSON-RPC, powiązanie tury z obcym wątkiem oraz opóźniony odczyt po anulowaniu. `CodexWorker` pozostaje `NOT_CERTIFIED`. Testy obejmują ramki bez numeru wersji i poprawne JSON-RPC 2.0.
- **#17.** Projekcja świeżych danych GitHub READ wymaga rzeczywistego czasu scalenia PR i stanu `completed` przed pokazaniem wniosku Actions. Odczyt historycznej projekcji zachowuje wcześniejszy kontrakt. Oficjalny MCP pozostaje osobną bramką.
- **#41.** Wynik Repair Loop zachowuje `UNKNOWN`, gdy STOP lub problem sprzątania nastąpi po obserwacji `UNKNOWN`. Zatrzymana próba zachowuje licznik osieroconych procesów i kod błędu sprzątania. Nie otwiera kolejnej próby i nie wydaje końcowego patcha.
- **#69.** Broker sprawdza nazwany inode względem pierwotnego deskryptora po `fsync` katalogu. Testy obejmują czytelność po wyłącznym link, zgon procesu przed link, po link i po synchronizacji katalogu, STOP przed link, istniejący ref o tej samej treści i podmianę inode. Jest to kontrola fizycznej publikacji i utraty ACK. Brak niezależnego trwałego świadectwa nadal blokuje rozliczenie historyczne. Status `UNKNOWN / BLOCKED_SECURITY_REVIEW` zachowuje `HELD` i zakaz replay.

Publiczny indeks kodu i historia nie ujawniły obecnego zewnętrznego konsumenta dla 23 kontraktów. Przy kwalifikacji potrzebny jest nazwany konsument i reprezentatywny wire fixture. Historyczny #18 Git HTTPS wymaga atomowego create-if-absent i zaufanego dowodu po utracie ACK.

Każda z czterech prób LIVE ma stan `NOT_RUN`. Manifest zawiera przypięty publiczny cel READ A oraz niezakwalifikowanego kandydata C. Cztery mutacje tworzenia tree, commit, ref i draft PR stanowią jedną logiczną publikację w aktualnym adapterze. Zakres jednego wywołania API pozostaje odrębnym kontraktem. [Manifest](LIVE_QUALIFICATION.json)
