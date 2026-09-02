# 00 — Przegląd projektu Termolink

## Cel

Firma instalacyjna (operator, Wodmiar) udostępnia swoim klientom portal, w którym każdy klient widzi
wyłącznie własne urządzenia Viessmann (pompy ciepła, kotły, wentylacja, solar…), ma czytelne
dashboardy i raporty, a zmiany ustawień są możliwe tylko tam, gdzie operator to włączył, tylko dla
administratora klienta i tylko po jawnym, dwuetapowym potwierdzeniu.

## Decyzje podjęte (2 września 2026)

| Temat | Decyzja |
|---|---|
| Nazwa | **Termolink** |
| Skala startowa | 1 klient, 6 urządzeń |
| Skala docelowa | ~100 klientów, ~500 urządzeń (projektujemy pod nią tam, gdzie zmiana później byłaby droga) |
| Model wdrożenia | Operator konfiguruje wszystko (w tym autoryzację OAuth na koncie Viessmann klienta) i oddaje gotowy produkt |
| Kto steruje | Operator (superadmin/serwisant) i **administrator klienta** — tylko gdy operator włączył tryb „sterowanie” na urządzeniu i tylko z aktywnym 2FA. **Zwykły użytkownik klienta — nigdy** |
| Retencja | Surowe odczyty bezterminowo (kompresja) + agregaty 1 h / 1 d. Retencja surowych = parametr konfiguracyjny (domyślnie bez limitu) |
| Szybkość | Interfejs czyta wyłącznie z bazy; brak oczekiwania po kliknięciu; cel: API < 200 ms dla widoków |
| Logo klienta | Opcjonalne; jeśli wgrane, pojawia się w nagłówku raportów, jeśli nie — nagłówek tekstowy |
| Stos | Django + DRF, PostgreSQL + TimescaleDB, React + TypeScript, Caddy, Docker Compose |
| Kolorystyka | Niebiesko-biała wg www.wodmiar.pl (granat #1e3b87); czerwień #ea0b28 wyłącznie dla ostrzeżeń/błędów/alarmów (`09-frontend.md`) |

## Zakres v1

- Konta: superadmin, serwisant, administrator klienta, użytkownik klienta; zaproszenia; 2FA.
- Podłączanie konta Viessmann (OAuth2 PKCE), odkrywanie instalacji/bram/urządzeń.
- Cykliczny odczyt wszystkich cech, historia, agregaty, statusy online/offline.
- Dashboard klienta, karta urządzenia z grupami cech, wykresy, tabela „pozostałe cechy”.
- Sterowanie z dwuetapowym potwierdzeniem, allowlist komend, weryfikacja po wykonaniu, audit log.
- Raporty (podgląd, CSV, PDF, cykliczne e-mail), alarmy (offline, poza zakresem, komunikaty urządzenia).
- Warstwa adapterów producentów (interfejs + implementacja Viessmann).

## Poza zakresem v1

Aplikacja mobilna natywna, automatyzacje/reguły, implementacja innych producentów, rozliczenia.

## Role

| Rola | Zakres | Sterowanie |
|---|---|---|
| `superadmin` | Wszyscy klienci, konfiguracja globalna, słownik etykiet, adaptery | Tak (oznaczone w audicie jako operator) |
| `technician` (serwisant) | Klienci jawnie przypisani (`tenant_memberships`) | Tak, jeśli membership ma `can_control` |
| `tenant_admin` (administrator klienta) | Własny tenant: urządzenia (nazwa/lokalizacja/opis), użytkownicy, logo | Tak — urządzenia w trybie `control`, wymaga 2FA |
| `tenant_user` (użytkownik klienta) | Własny tenant: podgląd, raporty | **Nie, nigdy** (kontrolki niewidoczne, serwer odrzuca) |

Tryb urządzenia (`read` / `control`) ustawia wyłącznie operator (`superadmin` / `technician`).

## Glosariusz

- **Tenant / klient** — organizacja lub osoba, właściciel urządzeń. Granica izolacji danych.
- **Provider** — producent / źródło danych (np. `viessmann`).
- **Provider account** — autoryzowane konto klienta u producenta (tokeny OAuth), właściciel budżetu API.
- **Installation → Gateway → Device** — hierarchia Viessmann.
- **Feature (cecha)** — jednostka danych w API Viessmann (np. `heating.circuits.0.sensors.temperature.supply`), ma `properties` i `commands`.
- **Property** — pojedyncza wartość cechy z typem i jednostką.
- **Command** — polecenie wykonywalne na cesze, z parametrami i ograniczeniami.
- **Poll / odczyt** — jedno wywołanie `…/features` dla jednego urządzenia (= 1 z budżetu API).
- **Budżet API** — limit wywołań producenta w oknie czasowym, liczony per provider account.
