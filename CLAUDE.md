# Termolink — instrukcje dla Claude Code

Termolink to wielodostępowy (multi-tenant) portal monitoringu i sterowania urządzeniami grzewczymi
(start: Viessmann przez Viessmann IoT API; docelowo inni producenci przez warstwę adapterów).
Operator: firma Wodmiar (Olsztyn). Klienci końcowi widzą wyłącznie swoje urządzenia.

## Jak pracować w tym repozytorium

1. **Przed każdą zmianą przeczytaj odpowiedni plik w `docs/`.** Dokumentacja jest źródłem prawdy.
   Jeśli implementacja wymaga odstępstwa — najpierw zaktualizuj `docs/`, potem kod.
2. **Nie wymyślaj cech, endpointów ani zachowań API Viessmann.** Wszystko, co dotyczy API, jest w
   `docs/01-viessmann-api.md` z oznaczeniem FAKT / ZAŁOŻENIE. Rzeczy oznaczone ZAŁOŻENIE
   wymagają weryfikacji na zrzutach z etapu 0 (`docs/13-roadmap.md`).
3. **Izolacja klientów jest nienegocjowalna.** Każda tabela z danymi klienta ma `tenant_id` i RLS.
   Każdy nowy endpoint dostaje test „użytkownik A nie widzi zasobu B → 404”.
4. **Sterowanie urządzeniem tylko przez `control/` i tylko zgodnie z `docs/07-control-flow.md`.**
   Żaden inny moduł nie wysyła żądań innych niż GET do API producenta.
5. **Interfejs nigdy nie czeka na API producenta.** Widoki czytają wyłącznie z bazy.
6. Język kodu, nazw i komentarzy: angielski. Język interfejsu użytkownika i dokumentacji: polski.
7. Testy są obowiązkowe dla: izolacji, budżetu API, przepływu sterowania, parsera cech.

## Stos

- Backend: Python 3.12, Django 5.x, Django REST Framework, `httpx` (async) w workerze.
- Baza: PostgreSQL 16 + TimescaleDB. Sesje w bazie. Kolejka zadań w bazie (`SKIP LOCKED`).
- Frontend: React 18 + TypeScript + Vite; wykresy: ECharts; stan serwera: TanStack Query.
- Proxy/TLS: Caddy. Uruchomienie: Docker Compose. PDF: WeasyPrint.

## Struktura repozytorium (docelowa)

```
termolink/
  CLAUDE.md
  docs/                      ← ta dokumentacja
  backend/
    termolink/               ← projekt Django (settings, urls)
    apps/
      accounts/              ← użytkownicy, role, 2FA, sesje, zaproszenia
      tenants/               ← klienci, członkostwa serwisantów, RLS middleware
      providers/             ← konta producentów (OAuth), budżet API
      adapters/
        base.py              ← interfejs ProviderAdapter
        viessmann/           ← implementacja Viessmann
      devices/               ← urządzenia, definicje cech, ostatnie wartości
      ingest/                ← worker: scheduler, poller, zapis historii, agregaty
      control/               ← wykonywanie komend z potwierdzeniem, allowlist, audit
      alerts/
      reports/
      audit/
    tests/
  frontend/
    src/
      app/                   ← routing, layout
      features/              ← moduły: auth, devices, device-detail, control, reports, admin
      components/ui/         ← prymitywy zgodne z docs/09-frontend.md
      api/                   ← klient HTTP + typy generowane z OpenAPI
  deploy/
    docker-compose.yml       ← baza wspólna
    docker-compose.dev.yml   ← nakładka lokalna (hot reload, porty, mailpit)
    docker-compose.prod.yml  ← nakładka VPS (TLS, read-only, backup)
    Caddyfile / Caddyfile.dev
    .env.example
  Makefile
```

## Środowisko pracy

Wszystko działa lokalnie w Dockerze (`docs/15-local-development.md`): `make dev` uruchamia bazę,
backend, worker, frontend i proxy na http://localhost:8080. Nie instaluj Pythona/Node/Postgresa na
hoście — uruchamiaj polecenia przez `docker compose exec` (skróty w Makefile). Ten sam Compose
z nakładką `prod` jedzie na VPS (`docs/11-deployment.md`).

```
make dev          # start wszystkiego z logami (build przy pierwszym razie)
make up / down    # w tle / stop; make reset = stop + usunięcie bazy dev
make migrate      # django migrate           make makemigrations
make seed         # dane demo (tylko dev)    make test / make lint
make worker       # jeden cykl workera       make psql / make shell / make logs s=<usługa>
```

Przy pracy nad UI zatrzymuj worker (`docker compose stop worker`) albo ustaw `VIESSMANN_MOCK=1`,
żeby nie zużywać wspólnego budżetu API Viessmann.

## Spis dokumentów

| Plik | Zawartość |
|---|---|
| docs/00-overview.md | Cel, zakres, decyzje, role, glosariusz |
| docs/01-viessmann-api.md | Wszystko o API Viessmann: auth, endpointy, format cech, limity, błędy, do weryfikacji |
| docs/02-architecture.md | Komponenty, przepływy, skalowanie |
| docs/03-data-model.md | Tabele, RLS, partycjonowanie, agregaty, retencja |
| docs/04-backend-api.md | REST API portalu (kontrakt) |
| docs/05-adapter-interface.md | Interfejs adaptera producenta + znormalizowany model cech |
| docs/06-polling-and-budget.md | Scheduler, budżet API, statusy urządzeń |
| docs/07-control-flow.md | Sterowanie: tryby, potwierdzenie, walidacja, weryfikacja |
| docs/08-security.md | Auth, sesje, 2FA, nagłówki, szyfrowanie tokenów, VPS |
| docs/09-frontend.md | Design tokens (paleta Wodmiar — do uzupełnienia), ekrany, komponenty, wydajność |
| docs/10-reports.md | Typy raportów, agregaty, PDF/CSV, harmonogram, logo klienta |
| docs/11-deployment.md | Docker Compose, Caddy, backupy, monitoring |
| docs/12-testing.md | Strategia testów, obowiązkowe testy, fixtures ze zrzutów API |
| docs/13-roadmap.md | Etapy 0–6 z kryteriami „gotowe” i zadaniami |
| docs/14-open-questions.md | Nierozstrzygnięte pytania i rzeczy do weryfikacji |
| docs/15-local-development.md | Uruchomienie lokalne w Dockerze, Makefile, praca z Claude Code lokalnie, mock API |
| docs/16-etap-0-instrukcja.md | Krok po kroku: Client ID, skrypt `backend/scripts/viessmann_capture.py`, fixtures, test limitu |
