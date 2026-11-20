# Przepływ kodowania w izolacji

Obie próby używają Task, SyntheticWorker, PythonRepositoryRecipe i rzeczywistego worker materializacji na kopii. Baza źródłowa i rezultat mają osobny odczyt i skrót. Zewnętrzne środowisko bwrap ogranicza każdy przypadek do własnych ścieżek i prywatnej sieci.

Kwalifikacja podpisanego wykonania przez Core wymaga zaufanego keepera systemd, cgroup i readback. E17 zachowuje oddzielne wyniki materializacji, wyroczni, istniejącego CoreRemoteGitRoute z fixture GitHub, HTTP/CLI, STOP/UNKNOWN oraz UI.
