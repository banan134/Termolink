# 14 — Pytania otwarte i rzeczy do weryfikacji

## Z implementacji (etap 5)

- **Alarm `worker_down` ewaluuje sam worker** — gdy padną wszystkie workery, nikt go nie otworzy.
  Docelowo (etap 6, monitoring z docs/11) zewnętrzny healthcheck `GET /api/v1/health` powinien
  sprawdzać także wiek ostatniego heartbeatu.

## Do weryfikacji w etapie 0 (API)

| # | Pytanie | Wpływ | Gdzie zapisać odpowiedź |
|---|---|---|---|
| A1 | Czy limit 1450/24 h jest per konto użytkownika, czy per Client ID? | Decyduje o wykonalności skali 500 urządzeń bez umowy z Viessmann | `01-viessmann-api.md` §5 |
| A2 | Czas życia refresh tokena; czy rotuje | **Częściowo (2026-09-03): nie rotuje; access 3600 s; czas życia refresh — obserwować** | `01` §2 |
| A3 | Kod HTTP i treść przy przekroczeniu limitu | Mapowanie `RateLimitedError` | `01` §6, `adapters/viessmann/errors.py` |
| A4 | Czy istnieje limit 120/10 min | `short_limit` | `01` §5 |
| A5 | Dokładne ścieżki features/commands i base URL | **Odpowiedziane (2026-09-03): `/iot/v2`, v1 = 410 GONE** | `01` §3 |
| A6 | Które cechy zużycia/energii zwraca API dla 6 urządzeń klienta | zakres raportu `energy` | fixtures |
| A7 | Czy `POST commands` zwraca coś poza statusem (np. nowy stan) | weryfikacja | `01` §3 |
| A8 | Czy urządzenia typu `gateway`/`HEMS` mają cechy warte pokazania | **Odpowiedziane (2026-09-03): bramka TCU ma 1 cechę; RoomControl 363 (pokoje) — nie dodawać domyślnie** | `01` §3 |

## Do decyzji operatora (Wodmiar)

| # | Pytanie | Domyślne założenie w dokumentacji |
|---|---|---|
| B1 | Docelowa domena portalu | `app.termolink.<domena>` — do ustalenia; sprawdzić dostępność domeny i znaku „Termolink” |
| B2 | Paleta kolorów | ✔ odczytana ze zrzutu wodmiar.pl (granat #1e3b87, czerwień #ea0b28 tylko dla ostrzeżeń) — `09-frontend.md`; jeśli istnieje księga znaku, zweryfikować |
| B3 | Retencja IP w audit logu | bezterminowo |
| B4 | Co po usunięciu klienta: usuwać historię pomiarów czy anonimizować | anonimizacja PII, historia zostaje |
| B5 | Czy e-mail z raportem ma zawierać PDF jako załącznik, czy tylko link | link (bezpieczniej), załącznik jako opcja |
| B6 | Godziny „normalne” dla alertu o komendach poza godzinami | 6:00–22:00 |
| B7 | Czy tenant_admin może sam zapraszać użytkowników klienta | tak |
| B8 | SMTP: własny serwer operatora czy usługa (np. Postmark) | do ustalenia przed etapem 5 |
| B9 | Kto jest administratorem danych w rozumieniu RODO (Wodmiar) i czy potrzebna umowa powierzenia z hostingiem VPS | do ustalenia z operatorem/prawnikiem |

## Założenia projektowe do potwierdzenia na danych (etap 2–3)

- Reguły grupowania `group_key` poza prefiksami widocznymi w fixtures.
- Zestaw `highlights` na kartach urządzeń per typ.
- Mapowanie parametr komendy → property (`value_before`) — czy nazwa parametru zawsze odpowiada
  nazwie property (w `setTemperature` param `targetTemperature` vs property `temperature` — **nie**
  odpowiada, więc potrzebne mapowanie w `feature_labels.command_property_map`).
