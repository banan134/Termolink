import { useState } from "react";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { devicesApi, type InsightItem } from "@/api/devices";
import { Card, Skeleton } from "@/components/ui";
import { unitLabel } from "@/features/charts/chartTheme";
import { t } from "@/i18n/pl";
import { propertyLabel } from "./format";
import s from "./devices.module.css";

function fmt(v: number | null, unit: string | null): string {
  if (v === null) return "—";
  const text = Number.isInteger(v) ? String(v) : Math.abs(v) >= 100 ? v.toFixed(0) : v.toFixed(1);
  return unit ? `${text} ${unitLabel(unit)}` : text;
}

/** „Co się zmieniło” — period-over-period sentences with a link to the explorer overlay. */
export function InsightsCard({ tid, id }: { tid: string; id: string }) {
  const [period, setPeriod] = useState<"week" | "month">("week");
  const q = useQuery({ queryKey: ["insights", tid, id, period], queryFn: () => devicesApi.insights(tid, id, period), staleTime: 60_000 });
  return (
    <Card title={t.insights.title}>
      <div className={s.compareBar}>
        <button type="button" className={`${s.tab} ${period === "week" ? s.tabActive : ""}`} onClick={() => setPeriod("week")}>
          {t.insights.week}
        </button>
        <button type="button" className={`${s.tab} ${period === "month" ? s.tabActive : ""}`} onClick={() => setPeriod("month")}>
          {t.insights.month}
        </button>
      </div>
      {q.isPending && <Skeleton height={60} />}
      {q.data && q.data.items.filter((i) => i.current !== null && i.previous !== null).length === 0 && <p className={s.sub}>{t.insights.noData}</p>}
      {q.data && (
        <div className={s.insights}>
          {q.data.items
            .filter((i) => i.current !== null || i.previous !== null)
            .map((i) => (
              <Insight key={`${i.kind}:${i.feature}:${i.property}`} item={i} tid={tid} id={id} range={period} />
            ))}
        </div>
      )}
    </Card>
  );
}

function Insight({ item, tid, id, range }: { item: InsightItem; tid: string; id: string; range: "week" | "month" }) {
  const d = item.delta;
  const flat = d === null || Math.abs(d) < 1e-9;
  const tone = flat ? s.flat : d > 0 ? s.up : s.down;
  const deltaText = d === null ? "" : flat ? t.insights.unchanged : `${d > 0 ? "▲" : "▼"} ${fmt(Math.abs(d), item.unit)}${item.delta_pct !== null && Math.abs(item.delta_pct) >= 0.5 ? ` (${item.delta_pct > 0 ? "+" : ""}${item.delta_pct} %)` : ""}`;
  const name = item.property && item.property !== "value" ? `${item.label} (${propertyLabel(item.property)})` : item.label;
  const body = (
    <>
      <div className={s.tileLabel}>
        {name}
        {item.kind !== "availability" && <span className={s.sub}> · {t.insights.kinds[item.kind]}</span>}
      </div>
      <div className={s.insightValue}>{fmt(item.current, item.unit)}</div>
      <div className={`${s.insightDelta} ${tone}`}>
        {deltaText} <span className={s.sub}>· {t.insights.vsPrevious}: {fmt(item.previous, item.unit)}</span>
      </div>
    </>
  );
  if (!item.feature) return <div className={s.insight}>{body}</div>;
  return (
    <Link to={`/t/${tid}/devices/${id}/chart?feature=${encodeURIComponent(item.feature)}&property=${encodeURIComponent(item.property ?? "value")}&range=${range}&overlay=1`} className={s.insight} title={t.charts.openExplorer}>
      {body}
    </Link>
  );
}
