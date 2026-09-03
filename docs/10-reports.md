# 10 — Raporty i alarmy

## Typy raportów (v1)

| `report_type` | Zawartość | Źródło danych |
|---|---|---|
| `operation` | temperatury (min/śr/max), statusy pracy, godziny pracy i starty (przyrosty), dostępność | `feature_values_1h/1d`, `device_status_history` |
| `energy` | cechy zużycia/energii **tylko jeśli istnieją** w `feature_definitions` (grupa `statistics`); brak → raport informuje, że API nie udostępnia ich dla tego modelu; nic nie jest szacowane | `feature_latest` + historia |
| `availability` | czas online/offline, lista przerw, alarmy | `device_status_history`, `alerts` |
| `changes` | dziennik komend z wynikami | `commands` |

Parametry: `device_ids[]`, `from`, `to`, `resolution` (`raw`/`1h`/`1d`, auto), `features[]`
(opcjonalnie; domyślnie zestaw z `feature_labels.report_default=true` + wszystkie numeryczne w `sensors`).

## Wyliczenia

- Liczniki rosnące (godziny pracy, starty, energia skumulowana): raportujemy **przyrost** = `last(to) − first(from)`
  z ochroną przed resetem licznika (jeśli spadek → sumuj odcinki rosnące; po resecie doliczamy wartość
  po resecie, bo licznik startuje od zera). Przy rozdzielczości `1h`/`1d` przyrost liczony jest z wartości
  `last` kolejnych kubełków — wzrost wewnątrz pierwszego kubełka nie jest widoczny (błąd ≤ 1 kubełek).
- Dostępność = suma czasu w `online` / długość okresu; przerwy < 2 min pomijane w liście (ale liczone).
- Średnie z agregatów: `avg` ważona `count` przy łączeniu godzin w dni.

## Formaty

- **Podgląd** (`/reports/preview`): synchroniczny, z agregatów, limit 50 000 punktów; wykresy w UI.
- **CSV**: UTF-8 z BOM, `;` jako separator (Excel PL), nagłówek: `czas;urządzenie;cecha;właściwość;wartość;jednostka`.
- **PDF**: WeasyPrint z szablonu HTML (`apps/reports/templates/reports/report.html`), CSS print w
  palecie UI; wykresy renderowane serwerowo jako **inline SVG własnym rendererem**
  (`apps/reports/render.py::svg_chart`: linia średniej + pas min–max, siatka, znaczniki komend) —
  decyzja etapu 5: bez matplotlib i bez headless Chrome (mniejszy obraz, brak zależności natywnych
  poza pango dla WeasyPrint). Wymagane biblioteki systemowe: `libpango-1.0-0 libpangoft2-1.0-0
  libharfbuzz0b fonts-dejavu-core` (Dockerfile i CI).
  Nagłówek: logo klienta **jeśli `tenants.logo_path` ustawione**, w przeciwnym razie tylko
  `report_header_text` lub nazwa klienta; stopka: „Termolink · Wodmiar”, data generowania, zakres.

## Harmonogram

`report_schedules.cron` (np. `0 6 * * 1` tygodniowo, `0 6 1 * *` miesięcznie), strefa tenanta.
Scheduler (tik workera, `apps/reports/jobs.py::schedule_reports`) tworzy job `render_report`, gdy
kolejne odpalenie crona (liczone od `last_run_at`/`created_at` w strefie klienta) minęło; okres raportu
= zamknięty poprzedni dzień/tydzień/miesiąc (`period`). Wynik w `report_files` (plik w
`media/reports/{tenant}/{id}.{pdf|csv}`, wygasa po 30 dniach — `purge_expired`), e-mail z linkiem do
pobrania (nie z załącznikiem — link wymaga logowania). „Uruchom teraz” = ten sam job z okresem
harmonogramu. Podgląd (`/reports/preview`) i pliki mogą pobierać wszystkie role; zapis harmonogramów
i usuwanie plików — tenant_admin i operator. Limit 50 000 punktów → 413 `too_many_points`.

## Alarmy

| `alert_rules.type` | Warunek | Domyślnie |
|---|---|---|
| `device_offline` | status `offline` ≥ `minutes` | 30 min, włączony dla każdego urządzenia |
| `value_out_of_range` | `feature.property` poza `[min,max]` w ≥ 2 kolejnych odczytach | brak (konfiguruje tenant_admin/operator) |
| `device_message` | nowa cecha w grupie `messages` lub zmiana jej wartości | włączony |
| `provider_account` | `reauth_required` / `rate_limited` | zawsze, do operatora |
| `verify_mismatch` | komenda nie potwierdzona odczytem | zawsze, do autora i operatora |

Alarm otwarty → wpis w `alerts`, e-mail (jeśli włączony w regule), widoczny w UI z możliwością
potwierdzenia; zamykany automatycznie, gdy warunek ustąpi. Deduplikacja: jeden otwarty alarm per
(tenant, device, type, key) — `key` to np. cecha.właściwość (zakres), cecha+hash treści (komunikat),
id konta/workera/komendy.

Implementacja (`apps/alerts/services.py`, etap 5): `evaluate_all()` uruchamiane w tiku workera co
60 s w kontekście systemowym; `device_offline` i `device_message` działają domyślnie dla każdego
urządzenia (reguła może zmienić `minutes`, wyłączyć typ lub e-mail; reguła per urządzenie ma
pierwszeństwo nad regułą dla całego klienta); `verify_mismatch` otwierany hookiem z `control` (e-mail
do autora + `ALERT_EMAIL_OPERATOR`); `provider_account` i `worker_down` (żaden worker nie ma heartbeatu młodszego niż 2 min;
wiersze starsze niż 1 h są usuwane, bo zabity proces nie sprząta po sobie; `tenant_id = NULL`)
tylko do operatora. E-maile do aktywnych `tenant_admin` klienta.
Alarmy bez `tenant_id` (worker) widzi tylko operator: `GET /admin/alerts`.
