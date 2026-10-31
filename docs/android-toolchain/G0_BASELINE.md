# G0 — baseline i izolacja

Zlecenie: `AIOA_Android_Codex_Master.pdf`, 31.10.2026; praca kontynuowana po
północy czasu Europe/Berlin bez zmiany identyfikatora zadania.
Źródło: kanoniczny AIOA spArkHAT, `AIOA-METAGuardiansSPARK`, zweryfikowany
`6216b16f22da167b401f8611291264d73eaacb40`, clean, origin
`https://github.com/luciferprosun/AIOA-spArkHAT.git`.

Nowa izolowana gałąź: `codex/android-toolchain-mobile-20261031`, linked worktree
`/home/l/AIOA_LOCAL_WORKTREES/android-toolchain-mobile-20261031`.
Źródłowy checkout i N1 pozostają bez zmian. Native worktree API nie potrafiło
rozpoznać repozytorium z task cwd `/home/l`; zwróciło błąd, bez ścieżki worktree.
Po potwierdzeniu niezmienionej listy Git użyto jawnie dozwolonego git worktree
fallback z dokładnego SHA, bez domyślnego main. Nie zmieniono `.gitignore` źródła.

Nie wykryto procesów z cwd wewnątrz źródła ani otwartego indeksu przez `fuser`.
To ograniczona obserwacja, nie globalna gwarancja braku wszystkich writerów.
Rozmiar śledzonego drzewa:40115144 bajty/1507 plików; root miał13271547904
bajty wolne, ponad wymagane10GiB. CPU2, RAM3841372KiB, dostępne1007756KiB,
swap wolne95924KiB: brak miejsca na równoległe ciężkie buildy.

Świeży baseline w izolacji: **323 Meta Python PASS**, 55.267s,0FAIL/0SKIP.
Przeczytano N1 `ANDROID_BUILD_HANDOFF.md`, klient README i owner handoff;
zapisano hashe wszystkich istniejących Android/mobile/protocol inputs.
Brak `java`, `javac`, `gradle`, `sdkmanager` i `shellcheck` w PATH.
Nie instalowano zależności z ogólnych procedur setup — G1 ma pierwszeństwo.

Prywatny dziennik, wejścia PDF, procesy i manifest:
`/home/l/projects/ANDROID_TOOLCHAIN_PRIVATE_20261031/G_20261031T224359Z/`
(0700, pliki0600). To jedyny dziennik zadania, poza Git; zostaje zachowany.
Nie skopiowano kluczy, baz, APK, profili Chrome ani prywatnego stanu odzyskiwania.
Nowe artefakty trafiają wyłącznie do zakresu tooling/tests/docs/workflow;
`clients/android`, protokół i runtime/Core są chronionymi wejściami.
