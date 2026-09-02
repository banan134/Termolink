import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { devicesApi, type FeatureRow } from "@/api/devices";
import { ApiError } from "@/api/client";
import { PageTitle } from "@/app/AppLayout";
import { Alert, Button, Card, Skeleton } from "@/components/ui";
import { useMe } from "@/features/auth/useMe";
import { t } from "@/i18n/pl";
import { HistoryChart } from "./HistoryChart";
import { ModeChip, StatusChip } from "./StatusChip";
import { formatDateTime, formatValue } from "./format";
import s from "./devices.module.css";

const GROUP_LABEL: Record<string, string> = {
  sensors: "Czujniki",
  dhw: "Ciepła woda",
  heat_source: "Źródło ciepła",
  solar: "Solar",
  ventilation: "Wentylacja",
  buffer: "Bufor",
  statistics: "Statystyki",
  messages: "Komunikaty",
  device: "Urządzenie",
  other: "Pozostałe",
};

function groupLabel(key: string) {
  if (key.startsWith("circuits.")) return `Obieg ${Number(key.split(".")[1]) + 1}`;
  return GROUP_LABEL[key] ?? key;
}

function FeaturesTable({ rows, onPick, picked }: { rows: FeatureRow[]; onPick: (f: string, p: string) => void; picked: string }) {
  const groups = useMemo(() => {
    const out: { key: string; rows: FeatureRow[] }[] = [];
    for (const row of rows) {
      const last = out[out.length - 1];
      if (last && last.key === row.group_key) last.rows.push(row);
      else out.push({ key: row.group_key, rows: [row] });
    }
    return out;
  }, [rows]);
  return (
    <div className={s.scroll}>
      <table className={s.table}>
        <thead>
          <tr>
            <th>{t.devices.feature}</th>
            <th>{t.devices.property}</th>
            <th>{t.devices.value}</th>
            <th>{t.devices.measured}</th>
          </tr>
        </thead>
        <tbody>
          {groups.map((g) => (
            <GroupRows key={g.key} label={groupLabel(g.key)} rows={g.rows} onPick={onPick} picked={picked} />
          ))}
        </tbody>
      </table>
    </div>
  );
}

function GroupRows({ label, rows, onPick, picked }: { label: string; rows: FeatureRow[]; onPick: (f: string, p: string) => void; picked: string }) {
  return (
    <>
      <tr className={s.groupRow}>
        <td colSpan={4}>{label}</td>
      </tr>
      {rows.map((row) =>
        Object.entries(row.properties).map(([prop, p], i) => {
          const key = `${row.feature_name}:${prop}`;
          const numeric = p.type === "number" && typeof p.value === "number";
          return (
            <tr key={key} className={row.is_enabled ? undefined : s.disabled} style={picked === key ? { background: "var(--accent-bg)" } : undefined}>
              <td>
                {i === 0 && (
                  <>
                    <div>{row.label_pl ?? row.feature_name.split(".").slice(-2).join(".")}</div>
                    <div className={s.mono}>{row.feature_name}</div>
                  </>
                )}
              </td>
              <td className={s.mono}>{prop}</td>
              <td className={s.value}>
                {numeric ? (
                  <button type="button" className={s.value} style={{ background: "none", border: 0, cursor: "pointer", color: "var(--accent)", font: "inherit", padding: 0 }} onClick={() => onPick(row.feature_name, prop)}>
                    {formatValue(p.value, p.unit)}
                  </button>
                ) : (
                  formatValue(p.value, p.unit)
                )}
              </td>
              <td className={s.sub}>{formatDateTime(p.ts_device ?? p.ts_polled)}</td>
            </tr>
          );
        }),
      )}
    </>
  );
}

export default function DevicePage() {
  const { tid = "", id = "" } = useParams();
  const me = useMe();
  const qc = useQueryClient();
  const device = useQuery({ queryKey: ["device", tid, id], queryFn: () => devicesApi.get(tid, id), refetchInterval: 30_000 });
  const features = useQuery({ queryKey: ["features", tid, id], queryFn: () => devicesApi.features(tid, id), refetchInterval: 60_000 });
  const [picked, setPicked] = useState<{ feature: string; property: string } | null>(null);
  const refresh = useMutation({
    mutationFn: () => devicesApi.refresh(tid, id),
    onSuccess: () => setTimeout(() => qc.invalidateQueries({ queryKey: ["features", tid, id] }), 8000),
  });

  if (device.isPending) return <Skeleton height={48} />;
  if (device.isError || !device.data) return <Alert tone="error">{t.errors.notFound}</Alert>;
  const d = device.data;
  const canRefresh = me.data?.role !== "tenant_user";
  const selected = picked ?? firstNumeric(features.data?.results ?? []);

  return (
    <>
      <p className={s.sub}>
        <Link to={`/t/${tid}`} style={{ color: "var(--accent)" }}>{t.devices.title}</Link> / {d.display_name}
      </p>
      <div className={s.header}>
        <PageTitle>{d.display_name}</PageTitle>
        <StatusChip status={d.status} />
        <ModeChip mode={d.mode} />
        <div className={s.headerActions}>
          {canRefresh && (
            <Button variant="secondary" loading={refresh.isPending} onClick={() => refresh.mutate()}>
              {t.devices.refreshNow}
            </Button>
          )}
        </div>
      </div>
      {refresh.isSuccess && <Alert tone="ok">{t.devices.refreshQueued}</Alert>}
      {refresh.isError && (
        <Alert tone="error">{refresh.error instanceof ApiError && refresh.error.code === "budget_reserve_exhausted" ? t.devices.reserveExhausted : t.common.error}</Alert>
      )}
      <div className={s.meta}>
        <Meta label={t.devices.model} value={d.model || "—"} />
        <Meta label={t.devices.location} value={d.location_text || "—"} />
        <Meta label={t.devices.lastSeen} value={formatDateTime(d.last_seen_at)} />
        <Meta label={t.devices.interval} value={`${Math.round(d.effective_interval_s / 60)} min`} />
        <div className={s.metaItem}>
          <div className={s.metaLabel}>{t.devices.budget}</div>
          <div>
            {d.budget.used} / {d.budget.limit}
          </div>
          <div className={s.budgetBar}>
            <div className={s.budgetFill} style={{ width: `${Math.min(100, (100 * d.budget.used) / d.budget.limit)}%` }} />
          </div>
        </div>
      </div>
      {d.status_detail && d.status !== "online" && <Alert tone="warn">{d.status_detail}</Alert>}

      {selected && (
        <Card title={`${t.devices.chart}: ${selected.feature}`}>
          <HistoryChart tid={tid} id={id} feature={selected.feature} property={selected.property} />
        </Card>
      )}

      <div style={{ height: "var(--sp-4)" }} />
      <Card title={t.devices.allFeatures}>
        {features.isPending && <Skeleton height={80} />}
        {features.data && features.data.count === 0 && <p className={s.sub}>{t.devices.noFeatures}</p>}
        {features.data && features.data.count > 0 && (
          <FeaturesTable rows={features.data.results} onPick={(feature, property) => setPicked({ feature, property })} picked={selected ? `${selected.feature}:${selected.property}` : ""} />
        )}
      </Card>
    </>
  );
}

function Meta({ label, value }: { label: string; value: string }) {
  return (
    <div className={s.metaItem}>
      <div className={s.metaLabel}>{label}</div>
      <div>{value}</div>
    </div>
  );
}

function firstNumeric(rows: FeatureRow[]): { feature: string; property: string } | null {
  for (const row of rows) {
    if (!row.is_enabled) continue;
    for (const [prop, p] of Object.entries(row.properties)) {
      if (p.type === "number" && typeof p.value === "number" && p.unit) return { feature: row.feature_name, property: prop };
    }
  }
  return null;
}
