import { useQuery } from "@tanstack/react-query";
import { useCallback, useMemo, useRef, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { devicesApi, type FeatureRow, type HistoryResponse } from "@/api/devices";
import { PageTitle } from "@/app/AppLayout";
import { Alert, Button, Card, Skeleton } from "@/components/ui";
import { useMe } from "@/features/auth/useMe";
import { t } from "@/i18n/pl";
import { ChartLine, type ChartHandle, type ChartSeries } from "./ChartLine";
import { RESOLUTION_LABEL, exportFileName, formatTs, unitLabel } from "./chartTheme";
import s from "./charts.module.css";

const RANGES = [
  { key: "day", label: "Dzień", ms: 24 * 3600e3 },
  { key: "week", label: "Tydzień", ms: 7 * 24 * 3600e3 },
  { key: "month", label: "Miesiąc", ms: 30 * 24 * 3600e3 },
  { key: "quarter", label: "Kwartał", ms: 91 * 24 * 3600e3 },
  { key: "half", label: "Półrocze", ms: 182 * 24 * 3600e3 },
  { key: "year", label: "Rok", ms: 365 * 24 * 3600e3 },
];
const MAX_MANUAL_POINTS = 20000;

type SeriesRef = { feature: string; property: string; deviceId?: string };

function parseSeries(raw: string | null): SeriesRef[] {
  if (!raw) return [];
  const out: SeriesRef[] = [];
  for (const item of raw.split(",")) {
    const [dev, feat, prop] = item.split("|");
    if (dev && feat) out.push({ deviceId: dev === "-" ? undefined : dev, feature: feat, property: prop || "value" });
  }
  return out;
}

function serializeSeries(list: SeriesRef[]): string {
  return list.map((x) => `${x.deviceId ?? "-"}|${x.feature}|${x.property}`).join(",");
}

function labelFor(features: FeatureRow[] | undefined, ref: SeriesRef, deviceName?: string): string {
  const row = features?.find((f) => f.feature_name === ref.feature);
  const base = row?.label_pl ?? ref.feature;
  const prop = ref.property !== "value" ? ` · ${ref.property}` : "";
  return deviceName ? `${base}${prop} · ${deviceName}` : `${base}${prop}`;
}

/** /t/:tid/devices/:id/chart — drill-down explorer with URL state (docs/09 §Drążenie). */
export default function ChartExplorerPage() {
  const { tid = "", id = "" } = useParams();
  const [params, setParams] = useSearchParams();
  const me = useMe();
  const chartRef = useRef<ChartHandle>(null);

  const feature = params.get("feature") ?? "";
  const property = params.get("property") ?? "value";
  const rangeKey = params.get("range") ?? "week";
  const res = params.get("res") ?? "";
  const overlay = params.get("overlay") === "1";
  const extra = useMemo(() => parseSeries(params.get("series")), [params]);
  // "now" rounded to the minute so the query key (and the fetch) is stable between renders
  const nowMinute = Math.floor(Date.now() / 60_000) * 60_000;
  const paramFrom = params.get("from");
  const paramTo = params.get("to");
  const { from, to } = useMemo(() => {
    const end = paramTo ? new Date(paramTo) : new Date(nowMinute);
    const span = RANGES.find((r) => r.key === rangeKey)?.ms ?? RANGES[1].ms;
    const start = paramFrom ? new Date(paramFrom) : new Date(end.getTime() - span);
    return { from: start, to: end };
  }, [paramFrom, paramTo, rangeKey, nowMinute]);
  const [customFrom, setCustomFrom] = useState(() => from.toISOString().slice(0, 16));
  const [customTo, setCustomTo] = useState(() => to.toISOString().slice(0, 16));
  const [pickerOpen, setPickerOpen] = useState(false);

  const update = useCallback(
    (patch: Record<string, string | null>) => {
      const next = new URLSearchParams(params);
      Object.entries(patch).forEach(([k, v]) => (v === null || v === "" ? next.delete(k) : next.set(k, v)));
      setParams(next, { replace: true });
    },
    [params, setParams],
  );

  const device = useQuery({ queryKey: ["device", tid, id], queryFn: () => devicesApi.get(tid, id) });
  const features = useQuery({ queryKey: ["features", tid, id], queryFn: () => devicesApi.features(tid, id) });
  const devices = useQuery({ queryKey: ["devices", tid], queryFn: () => devicesApi.list(tid) });

  const allSeries: SeriesRef[] = useMemo(() => (feature ? [{ feature, property }, ...extra] : extra), [feature, property, extra]);
  const spanMs = to.getTime() - from.getTime();
  const historyQuery = useQuery({
    queryKey: ["explorer", tid, id, allSeries, from.toISOString(), to.toISOString(), res, overlay],
    enabled: allSeries.length > 0,
    queryFn: async () => {
      const body = {
        series: allSeries.map((x) => ({ device_id: x.deviceId ?? id, feature: x.feature, property: x.property })),
        from: from.toISOString(),
        to: to.toISOString(),
        resolution: res || undefined,
        max_points: 2000,
      };
      const current = await devicesApi.historyMulti(tid, body);
      let previous: HistoryResponse[] = [];
      if (overlay && allSeries[0]) {
        const prev = await devicesApi.historyMulti(tid, {
          ...body,
          series: [body.series[0]],
          from: new Date(from.getTime() - spanMs).toISOString(),
          to: from.toISOString(),
        });
        previous = prev.results;
      }
      return { current: current.results, previous };
    },
    staleTime: 30_000,
  });

  const deviceNames = useMemo(() => Object.fromEntries((devices.data?.results ?? []).map((d) => [d.id, d.display_name])), [devices.data]);
  const chartSeries: ChartSeries[] = useMemo(() => {
    if (!historyQuery.data) return [];
    const out: ChartSeries[] = historyQuery.data.current.map((h, i) => ({
      key: `${h.device_id}|${h.feature}|${h.property}`,
      label: labelFor(features.data?.results, allSeries[i], allSeries[i].deviceId && allSeries[i].deviceId !== id ? deviceNames[allSeries[i].deviceId!] : undefined),
      history: h,
    }));
    for (const h of historyQuery.data.previous) {
      out.push({ key: `prev|${h.feature}`, label: `${labelFor(features.data?.results, allSeries[0])} — poprzedni okres`, history: h, dashed: true, shiftMs: spanMs });
    }
    return out;
  }, [historyQuery.data, features.data, allSeries, deviceNames, id, spanMs]);

  const numericFeatures = useMemo(
    () =>
      (features.data?.results ?? []).flatMap((f) =>
        Object.entries(f.properties)
          .filter(([, p]) => p.type === "number" && typeof p.value === "number")
          .map(([prop]) => ({ feature: f.feature_name, property: prop, label: `${f.label_pl ?? f.feature_name}${prop !== "value" ? ` · ${prop}` : ""}` })),
      ),
    [features.data],
  );

  const primary = historyQuery.data?.current[0];
  const stats = primary?.stats;
  const points = primary?.points.length ?? 0;
  const manualDisabled = points > MAX_MANUAL_POINTS;

  const shift = (dir: -1 | 1) => update({ from: new Date(from.getTime() + dir * spanMs).toISOString(), to: new Date(to.getTime() + dir * spanMs).toISOString() });
  const setRange = (key: string) => update({ range: key, from: null, to: null });
  const onZoom = useCallback((f: Date, tt: Date) => update({ from: f.toISOString(), to: tt.toISOString(), res: tt.getTime() - f.getTime() <= 48 * 3600e3 ? "raw" : "" }), [update]);

  const downloadPng = (large = false) => {
    if (!primary) return;
    const footer = `${formatTs(from)} – ${formatTs(to)} · ${RESOLUTION_LABEL[primary.resolution]} · Europe/Warsaw · Termolink · ${me.data?.tenant?.name ?? ""} · ${formatTs(new Date())}`;
    const url = chartRef.current?.toPng({ footer, pixelRatio: large ? 4 : 2 });
    if (!url) return;
    const a = document.createElement("a");
    a.href = url;
    a.download = exportFileName(device.data?.display_name ?? "urzadzenie", primary.feature, from, to, "png");
    a.click();
  };

  if (!feature) {
    return (
      <>
        <PageTitle>{t.charts.explorer}</PageTitle>
        <Card>
          <p className={s.muted}>{t.charts.pickFeature}</p>
          <ul className={s.list}>
            {numericFeatures.map((f) => (
              <li key={`${f.feature}:${f.property}`}>
                <button type="button" className={s.linkButton} onClick={() => update({ feature: f.feature, property: f.property })}>
                  {f.label}
                </button>
              </li>
            ))}
          </ul>
        </Card>
      </>
    );
  }

  return (
    <>
      <p className={s.muted}>
        <Link to={`/t/${tid}`} className={s.link}>{t.devices.title}</Link> / <Link to={`/t/${tid}/devices/${id}`} className={s.link}>{device.data?.display_name ?? "…"}</Link> / {t.charts.explorer}
      </p>
      <PageTitle>{labelFor(features.data?.results, allSeries[0])}</PageTitle>
      <div className={s.toolbar}>
        <Button variant="ghost" onClick={() => shift(-1)} aria-label="Poprzedni okres">◀</Button>
        {RANGES.map((r) => (
          <Button key={r.key} variant={rangeKey === r.key && !params.get("from") ? "primary" : "ghost"} onClick={() => setRange(r.key)}>
            {r.label}
          </Button>
        ))}
        <Button variant={pickerOpen || params.get("from") ? "secondary" : "ghost"} onClick={() => setPickerOpen((v) => !v)}>
          {t.charts.custom}
        </Button>
        <Button variant="ghost" onClick={() => shift(1)} aria-label="Następny okres">▶</Button>
        <Button variant="ghost" onClick={() => update({ from: null, to: null })}>{t.charts.today}</Button>
        <span className={s.spacer} />
        <select className={s.select} value={res} disabled={manualDisabled} onChange={(e) => update({ res: e.target.value })} aria-label="Rozdzielczość" title={manualDisabled ? t.charts.tooManyPoints : undefined}>
          <option value="">auto</option>
          <option value="raw">{RESOLUTION_LABEL.raw}</option>
          <option value="1h">{RESOLUTION_LABEL["1h"]}</option>
          <option value="1d">{RESOLUTION_LABEL["1d"]}</option>
        </select>
        <Button variant={overlay ? "secondary" : "ghost"} onClick={() => update({ overlay: overlay ? null : "1" })}>{t.charts.overlayPrevious}</Button>
        <Button variant="ghost" onClick={() => chartRef.current?.resetZoom()}>{t.charts.resetZoom}</Button>
      </div>
      {pickerOpen && (
        <form
          className={s.picker}
          onSubmit={(e) => {
            e.preventDefault();
            const f = new Date(customFrom);
            const tt = new Date(customTo);
            if (f >= tt) return;
            if (tt.getTime() - f.getTime() > 5 * 366 * 24 * 3600e3) return;
            update({ from: f.toISOString(), to: tt.toISOString() });
            setPickerOpen(false);
          }}
        >
          <label>
            {t.charts.from} <input type="datetime-local" value={customFrom} onChange={(e) => setCustomFrom(e.target.value)} />
          </label>
          <label>
            {t.charts.to} <input type="datetime-local" value={customTo} onChange={(e) => setCustomTo(e.target.value)} />
          </label>
          <Button type="submit" variant="secondary">{t.charts.apply}</Button>
          {new Date(customFrom) >= new Date(customTo) && <span className={s.error}>{t.charts.invalidRange}</span>}
        </form>
      )}

      <Card>
        {historyQuery.isPending && <Skeleton height={320} />}
        {historyQuery.isError && <Alert tone="error">{t.common.error}</Alert>}
        {historyQuery.data && chartSeries.length > 0 && (
          <ChartLine ref={chartRef} series={chartSeries} height={380} title={labelFor(features.data?.results, allSeries[0], device.data?.display_name)} subtitle={feature} showLegend enableZoom onZoom={onZoom} />
        )}
        {historyQuery.data && primary && primary.points.length === 0 && <p className={s.muted}>{t.devices.noHistory}</p>}
        <div className={s.toolbar} style={{ marginTop: "var(--sp-3)" }}>
          <Button variant="secondary" onClick={() => downloadPng(false)}>{t.charts.png}</Button>
          <Button variant="ghost" onClick={() => downloadPng(true)}>{t.charts.pngLarge}</Button>
          <a className={s.link} href={devicesApi.historyCsvUrl(tid, id, { feature, property, from: from.toISOString(), to: to.toISOString(), resolution: res || undefined })}>
            {t.charts.csv}
          </a>
          <span className={s.spacer} />
          <AddSeries options={numericFeatures} devices={devices.data?.results ?? []} currentDevice={id} feature={feature} onAdd={(ref) => extra.length < 5 && update({ series: serializeSeries([...extra, ref]) })} disabled={extra.length >= 5} />
        </div>
        {extra.length > 0 && (
          <div className={s.chips}>
            {extra.map((x, i) => (
              <span key={i} className={s.chip}>
                {labelFor(features.data?.results, x, x.deviceId && x.deviceId !== id ? deviceNames[x.deviceId] : undefined)}
                <button type="button" onClick={() => update({ series: serializeSeries(extra.filter((_, j) => j !== i)) || null })} aria-label="Usuń serię">×</button>
              </span>
            ))}
          </div>
        )}
      </Card>

      {stats && (
        <div className={s.stats}>
          <Stat label={t.charts.min} value={`${stats.min.value.toFixed(1)} ${unitLabel(primary?.unit)}`} sub={formatTs(stats.min.ts)} />
          <Stat label={t.charts.max} value={`${stats.max.value.toFixed(1)} ${unitLabel(primary?.unit)}`} sub={formatTs(stats.max.ts)} />
          <Stat label={t.charts.avg} value={`${stats.avg.toFixed(1)} ${unitLabel(primary?.unit)}`} />
          <Stat label={t.charts.last} value={`${Number(stats.last).toFixed(1)} ${unitLabel(primary?.unit)}`} />
          <Stat label={t.charts.samples} value={String(stats.count)} />
          <Stat label={t.charts.availability} value={`${stats.availability_pct.toFixed(1)} %`} />
          {stats.delta !== undefined && stats.delta !== null && <Stat label={t.charts.delta} value={`${stats.delta.toFixed(1)} ${unitLabel(primary?.unit)}`} />}
        </div>
      )}
    </>
  );
}

function Stat({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className={s.stat}>
      <div className={s.statLabel}>{label}</div>
      <div className={s.statValue}>{value}</div>
      {sub && <div className={s.statSub}>{sub}</div>}
    </div>
  );
}

function AddSeries({ options, devices, currentDevice, feature, onAdd, disabled }: { options: { feature: string; property: string; label: string }[]; devices: { id: string; display_name: string }[]; currentDevice: string; feature: string; onAdd: (ref: SeriesRef) => void; disabled: boolean }) {
  const [open, setOpen] = useState(false);
  const [deviceId, setDeviceId] = useState(currentDevice);
  const [pick, setPick] = useState("");
  return (
    <span className={s.addSeries}>
      <Button variant="ghost" disabled={disabled} onClick={() => setOpen((v) => !v)}>{t.charts.addSeries}</Button>
      {open && (
        <span className={s.addSeriesForm}>
          <select className={s.select} value={deviceId} onChange={(e) => setDeviceId(e.target.value)} aria-label="Urządzenie">
            {devices.map((d) => (
              <option key={d.id} value={d.id}>{d.display_name}</option>
            ))}
          </select>
          <select className={s.select} value={pick} onChange={(e) => setPick(e.target.value)} aria-label="Cecha">
            <option value="">{t.charts.pickFeature}</option>
            {(deviceId === currentDevice ? options : [{ feature, property: "value", label: t.charts.sameFeature }]).map((o) => (
              <option key={`${o.feature}:${o.property}`} value={`${o.feature}|${o.property}`}>{o.label}</option>
            ))}
          </select>
          <Button variant="secondary" disabled={!pick} onClick={() => { const [f, p] = pick.split("|"); onAdd({ deviceId: deviceId === currentDevice ? undefined : deviceId, feature: f, property: p }); setOpen(false); setPick(""); }}>
            {t.common.save}
          </Button>
        </span>
      )}
    </span>
  );
}
