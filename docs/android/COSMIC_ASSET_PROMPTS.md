# Manifest przyszłych zasobów Cosmic

Status: **PROPOZYCJE / NIE WYGENEROWANO**. Obecny interfejs używa natywnego tekstu, kolorów i kontrolek Compose. Ten manifest nie uruchamia imagegen, płatnej usługi ani pobierania grafik.

Paleta wspólna dla telefonu i Linuxa: Deep Space `#080D1C`, panel `#13203B`, błękit `#63D9FF`, fiolet `#A58CF5`, akcent `#F1A75D`, tekst `#F4F7FF`. Zasoby dekoracyjne nie mogą zastępować tekstowego statusu ani sygnalizować LIVE bez dowodu Core.

| Identyfikator | Zastosowanie i przyszły brief | Format docelowy / ograniczenie |
|---|---|---|
| cosmic-create | Prosty symbol białej dziury: jasny rdzeń i dwa dyskretne pierścienie na Deep Space; tworzenie, bez tekstu i bez logo zewnętrznych firm. | VectorDrawable/SVG, do 12 KiB, statyczny |
| cosmic-connect | Dwa wyraźne punkty połączone łagodnym tunelem czasoprzestrzennym; połączenie Android–Linux, czytelne także bez koloru. | VectorDrawable/SVG, do 12 KiB, statyczny |
| cosmic-boundary | Ciemny horyzont otoczony otwartym obrysem; granica dostępu. Stan odmowy opisuje osobny tekst, nie sam kolor. | VectorDrawable/SVG, do 8 KiB |
| cosmic-mission | Pojedyncza czteroramienna gwiazda z prostym konturem; misja. Nie dodawać konfetti, migotania ani symbolu sukcesu do stanu UNKNOWN. | VectorDrawable/SVG, do 4 KiB |
| cosmic-empty | Delikatny układ kilku punktów w pustej przestrzeni; tło pustej listy misji, bez sugerowania istniejących zadań. | Wektor, do 12 KiB, bez animacji |

Przyszły odbiór: kontrast WCAG dla tekstu i kontrolek, 48dp obszary dotyku, tekst 200%, TalkBack opisuje działanie zamiast dekoracji. Dekoracje mają pusty contentDescription; znaczące ikony mają lokalizowane opisy. Bez dużych bitmap, ciężkich animacji, CDN i dodatkowego providera. Dodanie rzeczywistych plików wymaga ponownego pomiaru APK i aktualizacji istniejącego manifestu wejść kompilacji.
