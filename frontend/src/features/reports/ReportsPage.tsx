import { useMemo, useState, type FormEvent } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ApiError } from "@/api/client";
import { devicesApi, type HistoryResponse } from "@/api/devices";
import { reportsApi, type ReportData, type ReportDevice, type ReportFormat, type ReportParams, type ReportSeries, type ReportType } from "@/api/reports";
import { PageTitle } from "@/app/AppLayout";
import { Alert, Button, Card, Chip, Field, Skeleton } from "@/components/ui";
import { useMe } from "@/features/auth/useMe";
import { ChartLine } from "@/features/charts/ChartLine";
import { RESOLUTION_LABEL, unitLabel } from "@/features/charts/chartTheme";
import { formatDateTime } from "@/features/devices/format";
import { t } from "@/i18n/pl";
import { FilesList } from "./FilesList";
import s from "./reports.module.css";

const TYPES: ReportType[] = ["operation", "energy", "availability", "changes"];

function isoLocal(d: Date): string {
  const off = d.getTimezoneOffset() * 60_000;
  return new Date(d.getTime() - off).toISOString().slice(0, 16);
}

/** /t/:tid/reports — parametry → podgląd (wykresy + tabele) → PDF/CSV (docs/10). */
export default function ReportsPage() {
  const { tid = "" } = useParams();
  const [params] = useSearchParams();
  const me = useMe();
  const qc = useQueryClient();
  const devices = useQuery({ queryKey: ["devices", tid], queryFn: () => devicesApi.list(tid) });
  const now = useMemo(() => new Date(), []);
  const [type, setType] = useState<ReportType>((params.get("type") as ReportType) || "operation");
  const [deviceIds, setDeviceIds] = useState<string[]>(params.get("device") ? [params.get("device")!] : []);
  const [from, setFrom] = useState(params.get("from") ? isoLocal(new Date(params.get("from")!)) : isoLocal(new Date(now.getTime() - 30 * 86_400_000)));
  const [to, setTo] = useState(params.get("to") ? isoLocal(new Date(params.get("to")!)) : isoLocal(now));
  const [resolution, setResolution] = useState<ReportParams["resolution"]>("auto");
  const [features, setFeatures] = useState(params.get("features") ?? "");
  const [preview, setPreview] = useState<ReportData | null>(null);

  const body = (): ReportParams => ({
    report_type: type,
    device_ids: deviceIds,
    from: new Date(from).toISOString(),
    to: new Date(to).toISOString(),
    resolution,
    features: features
      .split(/[,\n]/)
      .map((x) => x.trim())
      .filter(Boolean),
  });
  const run = useMutation({ mutationFn: () => reportsApi.preview(tid, body()), onSuccess: setPreview });
  const request = useMutation({
    mutationFn: (format: ReportFormat) => reportsApi.requestFile(tid, { ...body(), format }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["report-files", tid] }),
  });
  const err = (run.error ?? request.error) instanceof ApiError ? ((run.error ?? request.error) as ApiError) : null;
  const allDevices = devices.data?.results ?? [];
  const canManage = me.data?.role !== "tenant_user";

  return (
    <>
      <div className={s.header}>
        <PageTitle>{t.reports.title}</PageTitle>
        <span style={{ flex: 1 }} />
        {canManage && (
          <Link to={`/t/${tid}/reports/schedules`} className={s.buttonLink}>
            {t.reports.schedules}
          </Link>
        )}
      </div>

      <Card title={t.reports.params}>
        <form
          className={s.form}
          noValidate
          onSubmit={(e: FormEvent) => {
            e.preventDefault();
            run.mutate();
          }}
        >
          <div className={s.row}>
            <label className={s.field}>
              <span className={s.sub}>{t.reports.type}</span>
              <select value={type} onChange={(e) => setType(e.target.value as ReportType)} className={s.select}>
                {TYPES.map((k) => (
                  <option key={k} value={k}>
                    {t.reports.types[k]}
                  </option>
                ))}
              </select>
            </label>
            <label className={s.field}>
              <span className={s.sub}>{t.reports.resolution}</span>
              <select value={resolution} onChange={(e) => setResolution(e.target.value as ReportParams["resolution"])} className={s.select} disabled={type === "availability" || type === "changes"}>
                <option value="auto">auto</option>
                <option value="raw">{RESOLUTION_LABEL.raw}</option>
                <option value="1h">{RESOLUTION_LABEL["1h"]}</option>
                <option value="1d">{RESOLUTION_LABEL["1d"]}</option>
              </select>
            </label>
            <Field label={t.reports.from} type="datetime-local" value={from} onChange={(e) => setFrom(e.target.value)} error={err?.fields.from} />
            <Field label={t.reports.to} type="datetime-local" value={to} onChange={(e) => setTo(e.target.value)} />
          </div>
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
          {type === "operation" && (
            <Field label={t.reports.features} value={features} onChange={(e) => setFeatures(e.target.value)} help={t.reports.featuresHelp} placeholder="heating.sensors.temperature.outside, heating.circuits.0.sensors.temperature.supply" />
          )}
          {err && !err.fields.from && !err.fields.device_ids && <Alert tone="error">{err.code === "too_many_points" ? t.reports.tooManyPoints : err.message}</Alert>}
          <div className={s.actions}>
            <Button type="submit" loading={run.isPending} disabled={deviceIds.length === 0}>
              {t.reports.preview}
            </Button>
            <Button type="button" variant="secondary" loading={request.isPending && request.variables === "csv"} disabled={deviceIds.length === 0} onClick={() => request.mutate("csv")}>
              {t.reports.makeCsv}
            </Button>
            <Button type="button" variant="secondary" loading={request.isPending && request.variables === "pdf"} disabled={deviceIds.length === 0} onClick={() => request.mutate("pdf")}>
              {t.reports.makePdf}
            </Button>
          </div>
          {request.isSuccess && <Alert tone="ok">{t.reports.queued}</Alert>}
        </form>
      </Card>

      {preview && <Preview data={preview} tid={tid} />}

      <FilesList tid={tid} canManage={canManage} />
    </>
  );
}

function toHistory(d: ReportDevice, sr: ReportSeries, data: ReportData): HistoryResponse {
  return {
    device_id: d.id,
    device_name: d.name,
    feature: sr.feature,
    property: sr.property,
    unit: sr.unit,
    resolution: data.resolution,
    downsampled: false,
    from: data.from,
    to: data.to,
    points: sr.points,
    gaps: (d.offline ?? []).map((g) => ({ from: g.from, to: g.to })),
    stats: sr.stats,
    markers: sr.markers,
  };
}

function Preview({ data, tid }: { data: ReportData; tid: string }) {
  return (
    <section className={s.preview}>
      <div className={s.previewHead}>
        <h2 className={s.h2}>
          {t.reports.types[data.report_type]} · {formatDateTime(data.from)} – {formatDateTime(data.to)}
        </h2>
        <span className={s.sub}>
          {RESOLUTION_LABEL[data.resolution]} · {t.reports.points(data.total_points)}
        </span>
      </div>
      {data.devices.map((d) => (
        <Card key={d.id} title={`${d.name}${d.model ? ` · ${d.model}` : ""}${d.location ? ` · ${d.location}` : ""}`}>
          <div className={s.kpis}>
            <span>
              {t.reports.availability}: <b>{d.availability_pct} %</b>
            </span>
            {d.offline && (
              <span>
                {t.reports.gaps}: <b>{d.offline.length}</b>
              </span>
            )}
            <Link to={`/t/${tid}/devices/${d.id}`} className={s.deviceLink}>
              {t.reports.openDevice}
            </Link>
          </div>
          {data.report_type === "energy" && d.energy_available === false && <Alert tone="warn">{t.reports.noEnergy}</Alert>}
          {d.series.map((sr) => (
            <div key={`${sr.feature}.${sr.property}`} className={s.block}>
              <ChartLine series={[{ key: sr.feature, label: sr.label, history: toHistory(d, sr, data) }]} height={220} title={`${sr.label}${sr.property !== "value" ? ` · ${sr.property}` : ""}`} subtitle={sr.feature} compact />
              {sr.stats && (
                <div className={s.stats}>
                  {sr.counter && sr.stats.delta != null && (
                    <span>
                      {t.reports.delta}: <b>{fmt(sr.stats.delta)}</b> {unitLabel(sr.unit)}
                    </span>
                  )}
                  <span>
                    min <b>{fmt(sr.stats.min.value)}</b> ({formatDateTime(sr.stats.min.ts)})
                  </span>
                  <span>
                    max <b>{fmt(sr.stats.max.value)}</b> ({formatDateTime(sr.stats.max.ts)})
                  </span>
                  <span>
                    {t.charts.avg} <b>{fmt(sr.stats.avg)}</b>
                  </span>
                  <span>
                    {t.charts.samples} <b>{sr.stats.count}</b>
                  </span>
                </div>
              )}
              {!sr.stats && <p className={s.sub}>{t.reports.noData}</p>}
            </div>
          ))}
          {d.offline && d.offline.length > 0 && (
            <details className={s.block}>
              <summary className={s.sub}>{t.reports.gapsList(d.offline.length)}</summary>
              <table className={s.table}>
                <thead>
                  <tr>
                    <th>{t.reports.gapFrom}</th>
                    <th>{t.reports.gapTo}</th>
                    <th>{t.reports.duration}</th>
                  </tr>
                </thead>
                <tbody>
                  {d.offline.map((g, i) => (
                    <tr key={i}>
                      <td>{formatDateTime(g.from)}</td>
                      <td>{formatDateTime(g.to)}</td>
                      <td>{duration(g.seconds)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </details>
          )}
          {d.alerts && (
            <div className={s.block}>
              <h3 className={s.h3}>{t.alerts.title}</h3>
              {d.alerts.length === 0 && <p className={s.sub}>{t.reports.noAlerts}</p>}
              {d.alerts.length > 0 && (
                <table className={s.table}>
                  <thead>
                    <tr>
                      <th>{t.alerts.openedAt}</th>
                      <th>{t.alerts.closedAt}</th>
                      <th>{t.alerts.type}</th>
                      <th>{t.reports.message}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {d.alerts.map((a, i) => (
                      <tr key={i}>
                        <td>{formatDateTime(a.opened_at)}</td>
                        <td>{a.closed_at ? formatDateTime(a.closed_at) : <Chip tone="off">{t.alerts.severity[a.severity]}</Chip>}</td>
                        <td>{t.alerts.types[a.type] ?? a.type}</td>
                        <td>{a.message}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          )}
          {d.commands && (
            <div className={s.block}>
              <h3 className={s.h3}>{t.nav.changes}</h3>
              {d.commands.length === 0 && <p className={s.sub}>{t.control.noChanges}</p>}
              {d.commands.length > 0 && (
                <table className={s.table}>
                  <thead>
                    <tr>
                      <th>{t.control.when}</th>
                      <th>{t.control.what}</th>
                      <th>{t.control.before}</th>
                      <th>{t.control.after}</th>
                      <th>{t.control.who}</th>
                      <th>{t.control.statusLabel}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {d.commands.map((c, i) => (
                      <tr key={i}>
                        <td>{formatDateTime(c.created_at)}</td>
                        <td>
                          {t.control.commandLabel(c.command)}
                          <div className={s.mono}>{c.feature}</div>
                        </td>
                        <td>{kv(c.value_before)}</td>
                        <td>{kv(c.value_after)}</td>
                        <td>
                          {c.user ?? "—"}
                          {c.acted_as_operator ? ` (${t.control.operator})` : ""}
                        </td>
                        <td>{t.control.status[c.status] ?? c.status}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          )}
        </Card>
      ))}
    </section>
  );
}

function fmt(v: number | null | undefined): string {
  if (v === null || v === undefined) return "—";
  return Number.isInteger(v) ? String(v) : v.toFixed(2).replace(/\.?0+$/, "");
}

function kv(v: Record<string, unknown> | null): string {
  if (!v) return "—";
  return Object.entries(v)
    .map(([k, x]) => `${k}: ${typeof x === "object" ? t.control.scheduleValue : String(x)}`)
    .join(", ");
}

function duration(seconds: number): string {
  if (seconds < 3600) return `${Math.round(seconds / 60)} min`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)} h ${Math.round((seconds % 3600) / 60)} min`;
  return `${Math.floor(seconds / 86400)} d ${Math.floor((seconds % 86400) / 3600)} h`;
}
