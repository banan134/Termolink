# 09 — Frontend

Stos: React 18 + TypeScript + Vite, React Router, TanStack Query (cache + polling jobów), ECharts
(wykresy), `openapi-typescript` (typy z `/api/schema/`), CSS: zwykłe CSS modules + zmienne CSS
(bez Tailwind — mniej zależności, pełna kontrola nad paletą). Język UI: polski (teksty w `src/i18n/pl.ts`
od początku, żeby dodanie innego języka nie wymagało przeszukiwania kodu).

Referencja wizualna: klikalny mockup `../mockup-termolink.html` (7 ekranów, paleta Wodmiar). Mockup jest wzorcem układu
i zachowań, nie pikseli.

## Design tokens (`src/styles/tokens.css`)

Paleta odczytana ze zrzutu strony www.wodmiar.pl (2 września 2026, próbkowanie pikseli logo,
napisu i przycisków; wartości mogą różnić się o kilka jednostek od oryginalnych plików wektorowych —
jeśli operator ma księgę znaku, wpisać wartości z niej):

| Element źródłowy | Wartość |
|---|---|
| Granat logo i napisu WODMIAR | `#1e3b87` |
| Jaśniejszy granat (antyaliasing napisu) | `#3f568c` |
| Czerwień logo / przycisków | `#ea0b28` |
| Tło sekcji | `#f4f4f4` |
| Tekst | `#1c1c1c` |

Decyzja operatora: **baza niebiesko-biała; czerwień wyłącznie dla ostrzeżeń, błędów i alarmów**
(nie dla przycisków akcji, jak na stronie WWW).

```css
:root {
  /* marka */
  --brand-primary:   #1e3b87;
  --brand-secondary: #3f568c;
  --brand-red:       #ea0b28;
  --brand-ink:       #ffffff;   /* tekst na brand-primary; kontrast 10.6:1 */

  /* powierzchnie (jasny motyw — domyślny) */
  --bg: #ffffff; --surface: #ffffff; --surface-2: #f4f6fa;
  --border: #d7dce8; --border-strong: #b9c2d8;
  --text: #1c1c1c; --text-muted: #5a6275; --text-faint: #8b93a7;

  /* semantyka */
  --accent: var(--brand-primary); --accent-bg: #e6ebf6;
  --control: #8a5a00; --control-bg: #fbeed3;     /* tryb sterowania / potwierdzenia — bursztyn, żeby nie mylić z alarmem */
  --danger: var(--brand-red); --danger-bg: #fde7ea; /* błędy, offline, alarmy, akcje nieodwracalne */
  --ok: #1f7a3d; --ok-bg: #e1f1e4;
  --focus: var(--brand-primary);

  /* typografia */
  --font: Inter, system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
  --font-mono: "JetBrains Mono", ui-monospace, Menlo, monospace;
  --fs-xs: 12px; --fs-sm: 13px; --fs-md: 15px; --fs-lg: 20px; --fs-xl: 25px; --fs-2xl: 31px;

  /* odstępy (4-pt) i promienie */
  --sp-1: 4px; --sp-2: 8px; --sp-3: 12px; --sp-4: 16px; --sp-6: 24px; --sp-8: 32px;
  --r-sm: 6px; --r-md: 10px; --r-lg: 12px;
}
:root[data-theme="dark"] {
  --brand-primary: #7c97e6; --brand-secondary: #a4b5ea; --brand-red: #ff5a6e;
  --bg: #0f1523; --surface: #161d2e; --surface-2: #1e2740; --border: #2b3653; --border-strong: #3d4a6d;
  --text: #e9ecf4; --text-muted: #a3adc6; --text-faint: #6f7a99;
  --accent-bg: #1c2a4d; --accent-ink: #0b1120;
  --control: #e3b25a; --control-bg: #3a2d12; --danger-bg: #3b1a20; --ok: #7fd08f; --ok-bg: #1c3322;
}
```

Motywy:
- **Domyślnie jasny (białe tło)** — niezależnie od ustawień systemowych (brak `prefers-color-scheme`).
- Przełącznik „Tryb ciemny” w pasku górnym i w `/account`; wybór zapisywany w profilu użytkownika
  (`users.ui_theme: 'light'|'dark'`) i odtwarzany po zalogowaniu; przed zalogowaniem — jasny.
- Na białym tle karty rozdziela cień `0 1px 2px rgba(30,59,135,.06)` + obramowanie `--border`.

Zasady kolorów:
- Granat (`--brand-primary`): nawigacja, przyciski główne, linki, główna seria wykresów, logo Termolink.
- **Czerwień tylko dla**: błędów, stanu offline, alarmów, ostrzeżeń w dialogu potwierdzenia, akcji nieodwracalnych. Nigdy dla zwykłych przycisków akcji.
- Tryb sterowania i chipy „sterowalne”: bursztyn (`--control`) — odróżnialny od alarmu. Jeśli operator woli czerwień także tu, zmiana to jeden token.
- Online: zieleń. Neutralne: szarości z niebieskim odcieniem.
- Kontrast tekstu ≥ 4.5:1 (WCAG AA): `#1e3b87` na białym = 10.6:1, `#ea0b28` na białym = 4.6:1 (OK dla tekstu ≥ 14 px pogrubionego; dla drobnego tekstu używać `#c40a22`).
- Nigdy nie kodować znaczenia samym kolorem — zawsze etykieta/ikona obok.

## Ekrany (routing)

| Ścieżka | Ekran | Rola |
|---|---|---|
| `/login`, `/reset`, `/invite/:token` | logowanie, reset, przyjęcie zaproszenia | — |
| `/admin/tenants`, `/admin/tenants/:id` | klienci (lista, karta, konto Viessmann, użytkownicy, logo) | operator |
| `/admin/technicians`, `/admin/labels`, `/admin/audit`, `/admin/system` | | operator |
| `/t/:tid` | dashboard klienta: karty urządzeń, budżet API, ostatnie zdarzenia | wszyscy |
| `/t/:tid/devices/new` | kreator: konto → discover → wybór → ustawienia (tryb) → pierwszy odczyt | operator |
| `/t/:tid/devices/:id` | karta urządzenia: zakładki Przegląd / Wykresy / Wszystkie cechy / Komunikaty | wszyscy |
| `/t/:tid/devices/:id/chart` | eksplorator wykresu (drill-down; stan w query string) | wszyscy |
| `/t/:tid/devices/:id/settings` | nazwa, lokalizacja, opis (tenant_admin); tryb, interwał, limity (operator) | |
| `/t/:tid/reports`, `/t/:tid/reports/schedules` | | |
| `/t/:tid/alerts`, `/t/:tid/alert-rules` | | |
| `/t/:tid/changes` | dziennik zmian (commands) | |
| `/t/:tid/users` | użytkownicy klienta | tenant_admin |
| `/account` | profil, hasło, 2FA, sesje | wszyscy |

Operator wchodząc w `/t/:tid` widzi pasek „Przeglądasz jako operator — klient: X”.

## Karta urządzenia — Przegląd (rendering generyczny)

1. Nagłówek: nazwa, model, lokalizacja, opis, chip statusu, chip trybu, „Odśwież teraz”, „Ustawienia”.
2. Sekcje wg `group_key` w kolejności: `sensors` (kafelki z sparkline 24 h), `circuits.*` (karta obiegu),
   `dhw`, `heat_source`, `solar`, `ventilation`, `buffer`, `statistics`, `messages`, `other` (tabela surowa).
3. Sekcja pusta → nie renderuje się. Cechy `is_enabled=false` → tylko w „Wszystkie cechy” z oznaczeniem.
4. Widget per property wg typu:
   - `number` bez komendy → wartość + jednostka + sparkline; z komendą `set*` (min/max/stepping) → suwak + pole liczbowe + „Zastosuj zmianę…”.
   - `string` z `enum` komendą → select; bez → tekst.
   - `boolean` → chip on/off; z komendami `activate`/`deactivate` → przycisk.
   - `schedule` → podsumowanie + „Edytuj harmonogram…” (edytor tygodniowy).
   - `array`/`object` → rozwijany JSON w czytelnej formie.
5. Etykieta = `label_pl` ze słownika, fallback nazwa techniczna; nazwa techniczna zawsze widoczna jako
   podpis mono (pomaga w serwisie i w rozmowie z Viessmannem).
6. Kontrolki renderowane **tylko** gdy `capabilities.can_control` — w przeciwnym razie wartości są
   tylko do odczytu, bez „wyszarzonych” kontrolek (żeby nie kusić).

## Wykresy — wymagania

Każdy wykres w Termolink (kafelek, karta urządzenia, raport) spełnia poniższe zasady. Komponenty:
`ChartLine`, `ChartBar`, `ChartExplorer` (ECharts).

### Opis i czytelność
- **Tytuł** wykresu: etykieta polska cechy + nazwa urządzenia (np. „Temperatura zasilania — obieg 1 · Pompa ciepła — dom”);
  pod tytułem nazwa techniczna cechy mono (`heating.circuits.0.sensors.temperature.supply`).
- **Oś X**: czas w strefie tenanta; etykiety dopasowane do zakresu (godziny dla ≤ 48 h, dzień+godzina
  dla tygodnia, daty dla miesiąca i dłużej); linie siatki pionowe co pełną jednostkę (godzina/dzień/tydzień).
- **Oś Y**: tytuł z jednostką (`°C`, `%`, `kWh`, `h`, …) z `feature_latest.unit`; skala od sensownego
  minimum (nie zawsze od 0 — temperatury), dla liczników i procentów od 0; siatka pozioma.
- **Legenda**: zawsze widoczna przy > 1 serii; nazwa serii = etykieta PL; kliknięcie w legendę
  ukrywa/pokazuje serię. Serie w kolorach z palety: `--brand-primary`, `--brand-secondary`, `#8a5a00`,
  `#1f7a3d`, `#7c4dff`, `#00838f` (max 6 serii na wykresie; powyżej — ostrzeżenie i wybór).
- **Tooltip** przy najechaniu/dotknięciu: dokładny czas (`dd.MM.yyyy HH:mm`), wartość z jednostką dla
  każdej serii; dla agregatów: min / śr. / max / ostatnia. Na telefonie: dotknięcie ustawia kursor,
  wartości w panelu pod wykresem.
- **Rozdzielczość danych** widoczna na wykresie (np. „surowe · co ~7 min”, „średnie godzinowe”,
  „średnie dobowe”), żeby użytkownik wiedział, co ogląda. Agregaty rysowane jako linia średniej +
  półprzezroczysty pas min–max.
- Luki w danych (offline) — przerwa w linii, nie łączenie punktów; okresy offline zaznaczone szarym
  pasem z podpisem po najechaniu.
- Zmiany ustawień z dziennika komend (`commands.verified`) — pionowy znacznik na osi czasu z tooltipem
  „22 °C → 24 °C, Jan Kowalski” (można wyłączyć w ustawieniach wykresu).
- Kolor nigdy nie jest jedynym nośnikiem znaczenia; dostępny tryb wysokiego kontrastu (grubsze linie, wzory kresek).

### Drążenie (drill-down)
- Każdy wykres/kafelek na karcie urządzenia i w raporcie jest **klikalny** → otwiera `ChartExplorer`
  (pełny ekran na telefonie, duży panel na desktopie) z tą samą cechą.
- `ChartExplorer` — pasek zakresu z gotowymi przyciskami: **Dzień · Tydzień · Miesiąc · Kwartał ·
  Półrocze · Rok · Własny zakres** (dwa pola daty + godzina, walidacja `from < to`, max 5 lat).
  Zakres domyślny po wejściu: Tydzień. Strzałki ◀ ▶ przesuwają okno o jego długość; „Dziś” wraca do teraz.
- **Zoom**: przeciągnięcie po wykresie (desktop) / szczypnięcie (mobile) zawęża zakres; podwójne
  kliknięcie/„Resetuj” wraca do wybranego przycisku. Po zawężeniu poniżej 48 h rozdzielczość
  przełącza się automatycznie na surowe dane (ponowne pobranie z `/history?resolution=raw`).
- Rozdzielczość automatyczna wg zakresu (≤ 48 h surowe, ≤ 90 d 1 h, > 90 d 1 d) z możliwością
  ręcznej zmiany (surowe/1 h/1 d), jeśli liczba punktów ≤ 20 000; inaczej opcja wyszarzona z wyjaśnieniem.
- **Porównanie**: przycisk „+ Dodaj serię” — inna cecha tego samego urządzenia lub ta sama cecha innego
  urządzenia klienta (do 6 serii); serie w różnych jednostkach dostają drugą oś Y (prawą) z własnym tytułem.
- **Porównanie okresów**: „Nałóż poprzedni okres” — ta sama cecha z poprzedniego tygodnia/miesiąca/roku
  jako przerywana linia.
- Panel statystyk pod wykresem dla bieżącego zakresu: min (z czasem), max (z czasem), średnia,
  ostatnia wartość, liczba próbek, dostępność (%). Dla liczników: przyrost w zakresie.
- **Eksport**: CSV (dane widocznych serii w bieżącej rozdzielczości), „Dodaj do raportu” (przekazuje
  cechy i zakres do `/reports`) oraz **PNG** — patrz niżej.

### Pobieranie wykresu jako PNG
- Dostępne na **każdym** wykresie (kafelek, karta urządzenia, eksplorator, podgląd raportu) przez
  ikonę „Pobierz PNG” w rogu wykresu (menu „⋯” na telefonie) oraz w eksploratorze jako przycisk.
- Generowanie po stronie przeglądarki (`echarts.getDataURL({pixelRatio: 2, backgroundColor})`) — bez
  wywołań serwera; plik zapisuje się natychmiast.
- Zawartość obrazu: tytuł, nazwa urządzenia i lokalizacja, nazwa techniczna cechy, osie z tytułami
  i jednostkami, legenda, siatka, znaczniki, w stopce: zakres dat, rozdzielczość, strefa czasowa,
  „Termolink · <nazwa klienta>”, data wygenerowania. Tło zawsze **białe** (także w trybie ciemnym),
  żeby obraz nadawał się do maila i wydruku.
- Rozmiar: 1600×900 px (2× dla ostrości), format PNG-24. Na życzenie w eksploratorze: 3200×1800 px.
- Nazwa pliku: `termolink_<urządzenie>_<cecha>_<od>_<do>.png` (bez polskich znaków i spacji).
- Logo klienta (jeśli wgrane) w prawym górnym rogu — zgodnie z zasadą z raportów.
- Wykres w PNG ma być identyczny z tym, co widać na ekranie (ten sam zakres, zoom, ukryte serie
  pozostają ukryte).
- Stan eksploratora w URL (`?feature=…&from=…&to=…&res=…&series=…`), żeby link dało się wysłać
  serwisantowi i wrócił dokładnie do tego widoku.

### Wydajność wykresów
- Serwer zwraca max 2 000 punktów na serię (downsampling LTTB dla surowych); przy zmianie zakresu
  pobierane są tylko brakujące dane (cache TanStack Query per cecha+zakres+rozdzielczość).
- Zmiana zakresu przyciskiem: skeleton wykresu, dane w < 300 ms z agregatów.

## Komponenty (`src/components/ui/`)

`Button` (primary/secondary/ghost/danger; stan loading), `Chip` (ok/off/read/ctrl/neutral),
`Card`, `Tile` (wartość + jednostka + sparkline), `DataTable` (sortowanie, sticky header, overflow-x),
`Field` (label, help, error), `Slider+NumberInput` (respektuje stepping), `Select`, `ConfirmDialog`
(z odliczaniem i checkboxem — `07-control-flow.md`), `ReauthDialog`, `Toast`, `EmptyState`,
`Skeleton`, `ChartLine`/`ChartBar`/`ChartExplorer` (ECharts; osie z tytułami i jednostkami, legenda, tooltip, drill-down, zakresy), `RangePicker` (Dzień…Rok + własny), `ScheduleEditor`, `BudgetBar`.

## Wydajność (wymaganie „bez czekania”)

- Nawigacja SPA, code-splitting per ekran (`React.lazy`).
- TanStack Query: `staleTime` 30 s dla list, 10 s dla karty urządzenia; `refetchInterval` 60 s na
  dashboardzie; optimistic UI dla edycji nazw/opisu.
- Skeletony zamiast spinnerów; dane pokazywane progresywnie (nagłówek → kafelki → wykresy).
- Wykresy: rozdzielczość auto (`/history` bez `resolution`); max 2 000 punktów na serię; downsampling po stronie serwera.
- Budżety: LCP < 2 s na 4G, bundle początkowy < 250 kB gz, czas do interakcji karty urządzenia < 500 ms przy ciepłym cache.
- Pomiary: Web Vitals logowane do backendu (`/api/v1/metrics/web-vitals`, tylko agregaty).

## Dostępność

Focus widoczny, pełna obsługa klawiaturą, `aria-*` dla dialogów i tabel, `prefers-reduced-motion`
respektowany, minimalny cel dotyku 40×40 px, treści błędów w języku polskim.

## Responsywność

Punkty: ≤ 560 (telefon: 1 kolumna, dolna nawigacja), ≤ 900 (tablet: 2 kolumny, boczne menu chowane),
> 900 (desktop: boczne menu stałe). Tabele w kontenerze `overflow-x: auto`.
