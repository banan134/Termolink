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
  z ochroną przed resetem licznika (jeśli spadek → sumuj odcinki rosnące).
- Dostępność = suma czasu w `online` / długość okresu; przerwy < 2 min pomijane w liście (ale liczone).
- Średnie z agregatów: `avg` ważona `count` przy łączeniu godzin w dni.

## Formaty

- **Podgląd** (`/reports/preview`): synchroniczny, z agregatów, limit 50 000 punktów; wykresy w UI.
- **CSV**: UTF-8 z BOM, `;` jako separator (Excel PL), nagłówek: `czas;urządzenie;cecha;właściwość;wartość;jednostka`.
- **PDF**: WeasyPrint z szablonu HTML (`reports/templates/report.html`), ten sam CSS co UI (print),
  wykresy renderowane serwerowo jako SVG (matplotlib → SVG lub ECharts SSR; decyzja na etapie 5).
  Nagłówek: logo klienta **jeśli `tenants.logo_path` ustawione**, w przeciwnym razie tylko
  `report_header_text` lub nazwa klienta; stopka: „Termolink · Wodmiar”, data generowania, zakres.

## Harmonogram

`report_schedules.cron` (np. `0 6 * * 1` tygodniowo, `0 6 1 * *` miesięcznie), strefa tenanta.
Scheduler tworzy job `render_report`, wynik w `report_files`, e-mail z linkiem do pobrania
(nie z załącznikiem — link wymaga logowania) — ewentualnie załącznik PDF jako opcja w harmonogramie.
E-mail: SMTP operatora (env), szablony PL.

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
do autora + `ALERT_EMAIL_OPERATOR`); `provider_account` i `worker_down` (brak heartbeatu > 2 min,
`tenant_id = NULL`) tylko do operatora. E-maile do aktywnych `tenant_admin` klienta.
Alarmy bez `tenant_id` (worker) widzi tylko operator: `GET /admin/alerts`.
