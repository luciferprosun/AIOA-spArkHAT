# Cosmic Asset Manifest V1 — wyłącznie placeholdery

Status: **SPECIFICATION_ONLY / NO_ASSETS_GENERATED**. Nie utworzono obrazów,
wektorów, shaderów, animacji, CSS ani nowego ekranu. Nazwy poniżej opisują
przyszłe zasoby; nie są ścieżkami do istniejących plików.

Grafika dekoruje znaczenie przekazane przez natywny Compose. Tekst operacji,
stan połączenia, ryzyko, źródło dowodu i STOP są osobnymi dostępnymi
kontrolkami. Black Hole nie jest zgodą właściciela; Nova nie dowodzi PASS.
Żaden asset nie zmienia capability ani nie maskuje OFFLINE/UNKNOWN/BLOCKED.

## Siedem przyszłych zasobów

Wymiary to maksymalny eksport rastrowy, nie rozmiar widoku w dp. Safe area
jest obszarem bez detalu i **bez tekstu w samym obrazie**. Tekst Compose
otrzymuje jednolite tło Deep Space. Przyszłe ramki rezerwują stały ratio,
żeby ładowanie dekoracji nie przesuwało kontrolek.

| Placeholder | Slot i znaczenie | Ratio / eksport | Safe area i ciemne tło | Format / limit transferu | Redukcja ruchu i dostępność |
|---|---|---|---|---|---|
| White Hole Genesis | Pusty stan / propozycja nowej misji; możliwość utworzenia, nie rozpoczęcie Run | 3:2 / 960×640 px | Lewa dolna 45% szerokości × 35% wysokości bez detalu; cyan poza podkładem tekstu, bez flary pod etykietą | WebP ≤128 KiB; PNG tylko przy potrzebnej przezroczystości i tym samym limicie | Nieruchomy kadr; dekoracja pomijana przez TalkBack, „Nowa propozycja” jako Compose |
| Black Hole Guardian | Sąsiedztwo ryzyka i oczekiwania na owner review; nie przycisk approval | 3:2 / 960×640 px | Dolne 30% jednolite; violet ring poza panelem dowodu, brak ciemnego tekstu na jądrze | WebP ≤128 KiB; PNG transparent opcjonalnie | Statyczny ring bez pulsowania; ryzyko opisane tekstem/ikoną native, nie tylko kolorem |
| Wormhole Gateway | Karta telefonu ↔ Linux; orientacja transportowa, nie potwierdzenie TLS | 3:2 / 960×640 px | Środkowe 50%×35% wolne; host na osobnym nieprzezroczystym tle | WebP ≤128 KiB; źródło wektorowe po audycie | Statyczny schemat dwóch końców; status połączenia wyłącznie z podpisanego backendu |
| Starfield Background | Opcjonalne dekoracyjne tło; najniższy priorytet ładowania | 9:16 / 1080×1920 px | Centralne 70% szerokości × 80% wysokości spokojne; brak gwiazd pod tekstem bez podkładu | WebP ≤160 KiB; brak pełnoekranowego PNG domyślnie | Statyczne tło albo jednolite Deep Space; bez parallax i opisu TalkBack |
| Mission Constellation | Ilustracja obok listy misji/dowodów; dekoracja, nie rzeczywisty graf stanu | 16:9 / 960×540 px | Dolne 25% bez węzłów; właściwa lista i relacje w natywnych elementach | WebP ≤96 KiB; uproszczony VectorDrawable po przeglądzie | Nieruchome punkty; brak animacji i odczytywania każdej gwiazdy |
| Nova Success | Mały element przy zweryfikowanym terminalnym wyniku; nie zastępuje receipt i trybu | 1:1 / 384×384 px | Margines 15% z każdej strony; detale poza etykietą DONE/OFFLINE_FIXTURE | WebP/PNG ≤64 KiB; prosty wektor dopuszczalny | Statyczny znak; bez błysku/konfetti; wynik odczytywany raz z tekstu native |
| AIOA Cosmic Emblem | App/about/header identity, nie znak Meta/NVIDIA ani certyfikat | 1:1 / 256×256 px | 20% marginesu; raster bez liter, pełna nazwa jako native tekst obok | Przejrzany VectorDrawable ≤24 KiB; WebP/PNG fallback ten sam limit | Statyczny; opis „AIOA spArkHAT” tylko gdy brak sąsiedniej dostępnej etykiety |

Każdy wpis ma obecnie `source: NOT_CREATED`, `author: UNKNOWN`,
`license: UNVERIFIED`, `sha256: NONE`, `approval: NOT_GRANTED`. Przed użyciem
wymagane: autor, data, oryginalne źródło/projekt, uprawnienia do modyfikacji
i dystrybucji, narzędzie generacji (jeśli później zatwierdzone), licencja i
atrybucja, eksporter oraz SHA256 każdego wariantu. Nie kopiować assetów
Companion/AgentLab bez licencji. Nie dodawać cudzych logo ani fontów o niejasnym
pochodzeniu. „Generated” nie jest nazwą licencji.

SVG jest dopuszczalny jako przeglądane źródło, nie aktywny zasób: bez script,
event handlerów, foreignObject, fontów zewnętrznych, URL i osadzonych payloadów.
Konwersja do VectorDrawable jest osobnym zadaniem; teraz żaden taki plik nie powstaje.

## Tokeny przyszłego projektu

Propozycje nie zmieniają theme aplikacji. Obliczenia dotyczą nieprzezroczystego
sRGB na jednolitym `#081122`; nie oceniają gradientu, alpha, gotowego ekranu
ani zgodności całej aplikacji z WCAG.

| Token | HEX | Zastosowanie | Kontrast do Deep Space |
|---|---|---|---|
| Deep Space navy | `#081122` | Tło i tekst na jasnym wypełnieniu | — |
| White Hole cyan | `#67E8F9` | Propozycja / neutralny akcent | 13.01:1 |
| Gravity violet | `#C4B5FD` | Powiązania/kontekst, bez znaczenia approval | 10.21:1 |
| Event Horizon amber | `#FBBF24` | Ostrzeżenie/oczekiwanie, z etykietą | 11.30:1 |
| STOP red | `#FF6B6B` | Scoped STOP z jednoznacznym tekstem | 6.80:1 |
| Text primary | `#F8FAFC` | Tekst na navy | 18.02:1 |

Na jasnym tokenie stosować navy jako tekst. Biały tekst na cyan/amber/red
wymaga nowego pomiaru i nie jest zatwierdzony tą tabelą. STOP ma odróżnialny
kształt i podpis; kolor nie wystarcza. DENIED/UNKNOWN nie staje się sukcesem
dzięki zmianie ilustracji.

## Budżety i odbiór

Sumaryczny transfer siedmiu wariantów: **≤728 KiB**. Nie ładować wszystkich
jednocześnie: najwyżej tło + jedna ilustracja. Łączny zdekodowany raster
docelowo ≤12 MiB; 1080×1920 RGBA to około7.91 MiB, a 960×640 około2.34 MiB.
Testować na Xiaomi i słabszym urządzeniu; to budżet, nie wynik profilera.
Przy braku pamięci, błędzie lub oszczędzaniu danych: jednolite tło i native treść.

Tekst ≥4.5:1; duży tekst ≥3:1; istotne granice/ikony kontrolek ≥3:1 wobec
sąsiedniego tła. Kryteria projektu oparto na
[WCAG contrast minimum](https://www.w3.org/WAI/WCAG22/Understanding/contrast-minimum.html)
i [non-text contrast](https://www.w3.org/WAI/WCAG22/Understanding/non-text-contrast.html);
to nie certyfikat Androida. Natywne kontrolki: cel dotyku ≥48dp, kolejność
TalkBack, etykiety/focus, skalowanie tekstu do200% bez utraty STOP i dowodu.
Kontrolka nie może znajdować się w rastrze.

Wszystkie placeholdery są domyślnie statyczne. W przyszłości respektować
systemową redukcję/wyłączenie animacji; możliwość eliminacji ruchu opisuje
[WCAG animation from interactions](https://www.w3.org/WAI/WCAG22/Understanding/animation-from-interactions.html).
Nie stosować błysków, parallax, automatycznej zmiany kadru ani wymuszonego
ruchu. Brak dekoracji nigdy nie blokuje propozycji lub scoped STOP.

Odbiór przyszłego eksportu: licencja/provenance/hash, format/wymiary/waga,
brak aktywnej zawartości, pomiary kontrastu na ekranie, TalkBack/font-scale/
reduced-motion i profil pamięci. Osobna zgoda pozwoli utworzyć grafiki lub
zmienić UI. **Teraz wykonano tylko specyfikację i obliczenia kontrastu.**
