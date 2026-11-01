# Naprawa po rzeczywistej próbie CI

Spec: pierwotny A11–A20 PDF; wykonana zgoda na exact PR28 i jeden dispatch.
Fakty: docs/android/ANDROID_FIRST_BUILD_RESULT_20261101.md; prywatne GO_20261101T153216Z.
To nowa lokalna poprawka po rzeczywistym błędzie, nie ponowny review starego PR28.

- [x] Wykonać dokładnie zatwierdzony PR/merge/migrację/dispatch i zachować readback.
- [x] Przy FAIL przywrócić poprzedni CodeQL i potwierdzić walidację; bez retry.
- [x] Odtworzyć cached JDK symlink RED; użyć istniejącego pinned acquire; GREEN.
- [x] Odtworzyć realny konflikt ImageVersion/startup metadata RED; native metadata guard przed checkout; GREEN.
- [ ] Jeden niezależny read-only review wyłącznie nowego diff od087937c; autor naprawia Important/Critical w jednej serii RED→GREEN.
- [ ] Zachować prywatne dowody, manifesty i chronione źródła/procesy; końcowy scan/test.
- [ ] Dostarczyć konkretny patch/raport i exact nowy head/base. Nie publikować/merge ani nie dispatchować bez nowej zgody.

Review focus: JDK wyłącznie z istniejącego SHA-bound instalatora; brak podążania za cache linkiem; brak rozluźnienia SDK/Core/CI owner gates; runtime metadata guard faktycznie przed checkout i spójny w trzech jobach; test symlink musi odrzucać kernelowym O_NOFOLLOW; żaden wynik offline nie może oznaczać nowego APK/obrazu/kompilacji. Jeden run już wykorzystany, CodeQL default musi pozostać przywrócony podczas przygotowania.

Brak SDK/JDK download/install na hoście, drugiego Core, nowego klienta lub zmian storage/providerów. Pozostały SDK/pub-artifact consent z poprzedniego GO jest zachowany; nie obejmuje nowego head ani dodatkowego dispatch.
