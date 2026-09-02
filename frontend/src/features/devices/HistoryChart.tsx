import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { devicesApi, type HistoryPoint } from "@/api/devices";
import { Button, Skeleton } from "@/components/ui";
import { t } from "@/i18n/pl";
import { unitLabel } from "./format";
import s from "./devices.module.css";

const RANGES: { key: string; label: string; hours: number }[] = [
  { key: "day", label: "Dzień", hours: 24 },
  { key: "week", label: "Tydzień", hours: 24 * 7 },
  { key: "month", label: "Miesiąc", hours: 24 * 30 },
];

/** Minimal SVG line chart (stage 2). ECharts explorer with drill-down arrives in stage 3. */
export function HistoryChart({ tid, id, feature, property }: { tid: string; id: string; feature: string; property: string }) {
  const [range, setRange] = useState("week");
  const hours = RANGES.find((r) => r.key === range)?.hours ?? 168;
  const to = new Date();
  const from = new Date(to.getTime() - hours * 3600 * 1000);
  const history = useQuery({
    queryKey: ["history", tid, id, feature, property, range],
    queryFn: () => devicesApi.history(tid, id, { feature, property, from: from.toISOString(), to: to.toISOString() }),
    staleTime: 30_000,
  });

  return (
    <div>
      <div className={s.chips} style={{ marginBottom: "var(--sp-2)" }}>
        {RANGES.map((r) => (
          <Button key={r.key} variant={r.key === range ? "primary" : "ghost"} onClick={() => setRange(r.key)}>
            {r.label}
          </Button>
        ))}
        {history.data && (
          <span className={s.sub} style={{ alignSelf: "center" }}>
            {history.data.resolution === "raw" ? t.devices.resRaw : history.data.resolution === "1h" ? t.devices.res1h : t.devices.res1d}
            {history.data.unit ? ` · ${unitLabel(history.data.unit)}` : ""}
          </span>
        )}
      </div>
      {history.isPending && <Skeleton height={220} />}
      {history.data && history.data.points.length === 0 && <p className={s.sub}>{t.devices.noHistory}</p>}
      {history.data && history.data.points.length > 0 && <LineSvg points={history.data.points} raw={history.data.resolution === "raw"} />}
      {history.data?.stats && (
        <div className={s.sub}>
          min {history.data.stats.min.toFixed(1)} · śr. {history.data.stats.avg.toFixed(1)} · max {history.data.stats.max.toFixed(1)} · {t.devices.samples}: {history.data.stats.count}
        </div>
      )}
    </div>
  );
}

function LineSvg({ points, raw }: { points: HistoryPoint[]; raw: boolean }) {
  const W = 800;
  const H = 220;
  const pad = { l: 44, r: 12, t: 12, b: 24 };
  const xs = points.map((p) => new Date(p.ts).getTime());
  const ys = points.map((p) => (raw ? (p.value as number) : (p.avg as number)));
  const xMin = Math.min(...xs);
  const xMax = Math.max(...xs);
  const yMin = Math.min(...ys);
  const yMax = Math.max(...ys);
  const ySpan = yMax - yMin || 1;
  const x = (v: number) => pad.l + ((v - xMin) / (xMax - xMin || 1)) * (W - pad.l - pad.r);
  const y = (v: number) => pad.t + (1 - (v - yMin) / ySpan) * (H - pad.t - pad.b);
  const path = points.map((_, i) => `${i === 0 ? "M" : "L"}${x(xs[i]).toFixed(1)},${y(ys[i]).toFixed(1)}`).join(" ");
  const band = raw
    ? null
    : points.map((p, i) => `${i === 0 ? "M" : "L"}${x(xs[i]).toFixed(1)},${y(p.max as number).toFixed(1)}`).join(" ") +
      " " +
      [...points].reverse().map((p, i) => `L${x(xs[points.length - 1 - i]).toFixed(1)},${y(p.min as number).toFixed(1)}`).join(" ") +
      " Z";
  const ticks = [yMin, yMin + ySpan / 2, yMax];
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className={s.chart} role="img" aria-label="Wykres historii">
      {ticks.map((v) => (
        <g key={v}>
          <line x1={pad.l} x2={W - pad.r} y1={y(v)} y2={y(v)} stroke="var(--border)" strokeWidth="1" />
          <text x={pad.l - 6} y={y(v) + 4} textAnchor="end" fontSize="11" fill="var(--text-muted)">
            {v.toFixed(1)}
          </text>
        </g>
      ))}
      {band && <path d={band} fill="var(--accent-bg)" stroke="none" />}
      <path d={path} fill="none" stroke="var(--brand-primary)" strokeWidth="2" />
      <text x={pad.l} y={H - 6} fontSize="11" fill="var(--text-muted)">
        {new Date(xMin).toLocaleString("pl-PL", { dateStyle: "short", timeStyle: "short" })}
      </text>
      <text x={W - pad.r} y={H - 6} fontSize="11" fill="var(--text-muted)" textAnchor="end">
        {new Date(xMax).toLocaleString("pl-PL", { dateStyle: "short", timeStyle: "short" })}
      </text>
    </svg>
  );
}
