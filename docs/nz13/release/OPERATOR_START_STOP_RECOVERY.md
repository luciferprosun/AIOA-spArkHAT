# Uruchomienie, STOP i odzyskiwanie

Smoke instalacji to aioa-sparkhat --help oraz aioa-sparkhat-web --help w izolowanym środowisku z przypiętymi zależnościami. Lokalny podgląd Mission Control w prywatnym profilu offline używa istniejącego polecenia projektu, python3 -B -m runtime.webapp --unified-offline --host 127.0.0.1 --port 0. Uruchomienie wymaga osobnego katalogu danych i lokalnego loopback. Android korzysta z projekcji tego samego Core po kwalifikacji osobnego profilu Native.

Operator sprawdza podpisaną sesję, ważność przydziału, źródła i docelowy scope przed START. Core ponawia kontrolę w COMMIT. Sandbox dopuszcza tylko zatwierdzony PatchSet, a wynik pracy wiąże z receipt i odczytem.

STOP zatrzymuje przyjmowanie nowych efektów i odwołuje aktywne uprawnienie. Przy utracie ACK zachowaj UNKNOWN, powiązany identyfikator intencji oraz ostatni receipt. Niezależny odczyt w tym samym zakresie może potwierdzić Applied lub NotApplied. Ponowna komenda oczekuje na rozliczenie i nowe uprawnienie. Zachowany ledger zapobiega powtórzeniu efektu po restarcie.

Wznowienie prac lokalnych zaczyna się od RESUME.md i checkpointu E19 w katalogu odbiorczym. Pliki macierzy E18 wskazują dokładne identyfikatory pozostałych przypadków.
