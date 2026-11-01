# N1 / N0 — preflight, 31.10.2026

TARGET `/home/l/projects/AIOA-spArkHAT-META`, branch `AIOA-METAGuardiansSPARK`, HEAD `7387d823f38d1bc4ca964788ae11441d29b6ae6e`, clean; upstream `origin/AIOA-METAGuardiansSPARK`, origin `https://github.com/luciferprosun/AIOA-spArkHAT.git`. Jeden writer TARGET; metadane procesów comm/cwd sprawdzone bez argv/env. Nie zmieniano main ani source worktree.

Companion `codex/final-connect-20261023@9cf6c567b40bc87385fb90e9143b0fb170889b2a` i Agent Lab `feature/aioa-android-agent-lab-20261028@fb8642f108aea7db5db7a0b1446d4145f4167991` są czyste. Nebius `feature/nebius-nemotron-integration-20261028@6e9dd8ebc1dcb2c03345d9dc7d30895013751cd5` ma zachowane24 modified/199 untracked; tylko odczyt. Nie odczytywano sekretów/state ani nie dotykano M12/GOLD72/WD/LSC.

Baseline wykonany: Meta265/265, Node7/7, Core13/13, MCP99/99; zero FAIL/SKIP. Prywatne logi/snapshoty: `/home/l/projects/META_MOBILE_PRIVATE_20261031/N1_20261031T212814Z` (0700). SHA76 wybranych publicznych plików kodu/kontraktu: `N0_SOURCE_MANIFEST.json`; nie kopiowano APK ani baz. Stary APK ma oczekiwany SHA `43943d19196d26e3be93015d1d6f1cad87a49f94015978ce40afa7ccce4725c6`, pozostaje bez zmian.

W obu źródłach nie znaleziono pliku LICENSE/COPYING/NOTICE. Zgodnie z mandatem nie importujemy ich projektu verbatim: nowa neutralna implementacja zachowuje techniczny kontrakt transportu i tożsamość aplikacji, a mapa wskazuje źródło idei. TARGET ma własną MIT LICENSE. Ewentualny standardowy Gradle wrapper wymaga niezależnej weryfikacji upstream/checksum/Apache-2.0.

Zastane moduły TARGET: `MissionService`, `CoreAdmission`, `CoreWarrantLedger`, `CoreDualGovernor`, `TransactionRunner`, Meta provider/R6, `runtime.webapp` i `web/` — REUSED. `runtime/mcp_bridge/mobile_nebius.py` jest nieautorytatywną kopertą READ z procesowym replay guard, nie podpisanym/persisted transportem; nie zastępuje urządzeniowej sesji i nie zostanie rozszerzony do ownera. Brak `clients/android` i podpisanej bramki MobileMissionV1.

Narzędzia: Python/Node/ADB obecne, java/javac/gradle/kotlinc nieobecne w PATH; `/usr/lib/jvm`, `~/Android/Sdk`, `~/.gradle/wrapper/dists` nie istnieją. Dalszy N6 tylko sprawdzi dozwolone cache; żadnej instalacji/pobierania toolchainu. Nie wywoływano ADB ani konfiguracji Tailscale. Nowe serwery testowe wyłącznie127.0.0.1:0, odrębny prywatny state, own cleanup. Chronione18766/4314/4315/4316/4321 nie są używane.
