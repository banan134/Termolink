import { useState, type FormEvent } from "react";
import { Link, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ApiError } from "@/api/client";
import { devicesApi } from "@/api/devices";
import { reportsApi, type Period, type ReportFormat, type ReportSchedule, type ReportType } from "@/api/reports";
import { PageTitle } from "@/app/AppLayout";
import { Alert, Button, Card, Chip, Field, Skeleton } from "@/components/ui";
import { formatDateTime } from "@/features/devices/format";
import { t } from "@/i18n/pl";
import s from "./reports.module.css";

const CRON_PRESETS: { key: string; cron: string; label: string }[] = [
  { key: "monthly", cron: "0 6 1 * *", label: t.reports.cronMonthly },
  { key: "weekly", cron: "0 6 * * 1", label: t.reports.cronWeekly },
  { key: "daily", cron: "0 6 * * *", label: t.reports.cronDaily },
];

/** /t/:tid/reports/schedules — harmonogramy (docs/10 §Harmonogram). */
export default function SchedulesPage() {
  const { tid = "" } = useParams();
  const qc = useQueryClient();
  const list = useQuery({ queryKey: ["report-schedules", tid], queryFn: () => reportsApi.schedules(tid) });
  const devices = useQuery({ queryKey: ["devices", tid], queryFn: () => devicesApi.list(tid) });
  const invalidate = () => qc.invalidateQueries({ queryKey: ["report-schedules", tid] });
  const toggle = useMutation({ mutationFn: (r: ReportSchedule) => reportsApi.updateSchedule(tid, r.id, { enabled: !r.enabled }), onSuccess: invalidate });
  const remove = useMutation({ mutationFn: (id: string) => reportsApi.deleteSchedule(tid, id), onSuccess: invalidate });
  const runNow = useMutation({ mutationFn: (id: string) => reportsApi.runSchedule(tid, id), onSuccess: () => qc.invalidateQueries({ queryKey: ["report-files", tid] }) });

  const [name, setName] = useState("");
  const [type, setType] = useState<ReportType>("operation");
  const [deviceIds, setDeviceIds] = useState<string[]>([]);
  const [period, setPeriod] = useState<Period>("last_month");
  const [format, setFormat] = useState<ReportFormat>("pdf");
  const [cron, setCron] = useState("0 6 1 * *");
  const [recipients, setRecipients] = useState("");
  const create = useMutation({
    mutationFn: () =>
      reportsApi.createSchedule(tid, {
        name: name.trim(),
        report_type: type,
        device_ids: deviceIds,
        features: [],
        period,
        resolution: "auto",
        format,
        recipients: recipients
          .split(/[,\s]+/)
          .map((x) => x.trim())
          .filter(Boolean),
        cron,
        enabled: true,
      }),
    onSuccess: () => {
      invalidate();
      setName("");
    },
  });
  const err = create.error instanceof ApiError ? create.error : null;
  const allDevices = devices.data?.results ?? [];
  const deviceName = (id: string) => allDevices.find((d) => d.id === id)?.display_name ?? id.slice(0, 8);

  return (
    <>
      <p className={s.sub}>
        <Link to={`/t/${tid}/reports`} style={{ color: "var(--accent)" }}>{t.reports.title}</Link> / {t.reports.schedules}
      </p>
      <PageTitle>{t.reports.schedules}</PageTitle>
      <p className={s.sub}>{t.reports.schedulesHelp}</p>

      <Card title={t.reports.newSchedule}>
        <form
          className={s.form}
          noValidate
          onSubmit={(e: FormEvent) => {
            e.preventDefault();
            create.mutate();
          }}
        >
          {err && !Object.keys(err.fields).length && <Alert tone="error">{err.message}</Alert>}
          <Field label={t.reports.scheduleName} value={name} onChange={(e) => setName(e.target.value)} required error={err?.fields.name} />
          <div className={s.row}>
            <label className={s.field}>
              <span className={s.sub}>{t.reports.type}</span>
              <select value={type} onChange={(e) => setType(e.target.value as ReportType)} className={s.select}>
                {(["operation", "energy", "availability", "changes"] as ReportType[]).map((k) => (
                  <option key={k} value={k}>
                    {t.reports.types[k]}
                  </option>
                ))}
              </select>
            </label>
            <label className={s.field}>
              <span className={s.sub}>{t.reports.period}</span>
              <select value={period} onChange={(e) => setPeriod(e.target.value as Period)} className={s.select}>
                <option value="last_day">{t.reports.periods.last_day}</option>
                <option value="last_week">{t.reports.periods.last_week}</option>
                <option value="last_month">{t.reports.periods.last_month}</option>
              </select>
            </label>
            <label className={s.field}>
              <span className={s.sub}>{t.reports.format}</span>
              <select value={format} onChange={(e) => setFormat(e.target.value as ReportFormat)} className={s.select}>
                <option value="pdf">PDF</option>
                <option value="csv">CSV</option>
              </select>
            </label>
            <label className={s.field}>
              <span className={s.sub}>{t.reports.when}</span>
              <select value={CRON_PRESETS.find((p) => p.cron === cron)?.key ?? "custom"} onChange={(e) => setCron(CRON_PRESETS.find((p) => p.key === e.target.value)?.cron ?? cron)} className={s.select}>
                {CRON_PRESETS.map((p) => (
                  <option key={p.key} value={p.key}>
                    {p.label}
                  </option>
                ))}
                <option value="custom">{t.reports.cronCustom}</option>
              </select>
            </label>
          </div>
          <Field label="cron" value={cron} onChange={(e) => setCron(e.target.value)} help={t.reports.cronHelp} error={err?.fields.cron} />
          <fieldset className={s.devices}>
            <legend className={s.sub}>{t.reports.devices}</legend>
            {devices.isPending && <Skeleton height={20} />}
            {allDevices.map((d) => (
              <label key={d.id} className={s.check}>
                <input type="checkbox" checked={deviceIds.includes(d.id)} onChange={(e) => setDeviceIds(e.target.checked ? [...deviceIds, d.id] : deviceIds.filter((x) => x !== d.id))} /> {d.display_name}
              </label>
            ))}
            {err?.fields.device_ids && <span className={s.error}>{err.fields.device_ids.join(" ")}</span>}
          </fieldset>
          <Field label={t.reports.recipients} value={recipients} onChange={(e) => setRecipients(e.target.value)} help={t.reports.recipientsHelp} error={err?.fields.recipients} />
          <div className={s.actions}>
            <Button type="submit" loading={create.isPending} disabled={!name.trim() || deviceIds.length === 0}>
              {t.common.add}
            </Button>
          </div>
        </form>
      </Card>

      {list.isPending && <Skeleton height={80} />}
      {list.data && (
        <Card title={t.reports.schedules}>
          {list.data.results.length === 0 && <p className={s.sub}>{t.reports.noSchedules}</p>}
          {list.data.results.map((r) => (
            <div key={r.id} className={s.scheduleRow}>
              <div className={s.itemMain}>
                <div className={s.itemTop}>
                  <Chip tone={r.enabled ? "ok" : "neutral"}>{r.enabled ? t.alerts.enabled : t.alerts.disabled}</Chip>
                  <b>{r.name}</b>
                  <span className={s.sub}>
                    · {t.reports.types[r.report_type]} · {t.reports.periods[r.period]} · {r.format.toUpperCase()} · <span className={s.mono}>{r.cron}</span>
                  </span>
                </div>
                <div className={s.sub}>
                  {r.device_ids.map(deviceName).join(", ")}
                  {r.recipients.length > 0 && ` · ${t.reports.recipients}: ${r.recipients.join(", ")}`}
                  {r.last_run_at && ` · ${t.reports.lastRun}: ${formatDateTime(r.last_run_at)}`}
                </div>
              </div>
              <div className={s.actions}>
                <Button variant="secondary" onClick={() => runNow.mutate(r.id)} loading={runNow.isPending && runNow.variables === r.id}>
                  {t.reports.runNow}
                </Button>
                <Button variant="ghost" onClick={() => toggle.mutate(r)}>
                  {r.enabled ? t.alerts.disable : t.alerts.enable}
                </Button>
                <Button variant="danger" onClick={() => window.confirm(t.reports.deleteConfirm) && remove.mutate(r.id)}>
                  {t.common.delete}
                </Button>
              </div>
            </div>
          ))}
          {runNow.isSuccess && <Alert tone="ok">{t.reports.queued}</Alert>}
        </Card>
      )}
    </>
  );
}
