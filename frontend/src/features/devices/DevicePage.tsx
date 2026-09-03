import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { devicesApi, type FeatureRow } from "@/api/devices";
import { ApiError } from "@/api/client";
import { PageTitle } from "@/app/AppLayout";
import { Alert, Button, Card, Skeleton } from "@/components/ui";
import { ChartLine } from "@/features/charts/ChartLine";
import { useMe } from "@/features/auth/useMe";
import { t } from "@/i18n/pl";
import { ModeChip, StatusChip } from "./StatusChip";
import { PropertyWidget } from "./Widgets";
import { ControlTab } from "@/features/control/ControlTab";
import { formatDateTime, formatValue } from "./format";
import { groupLabel, groupRows, hasValues } from "./groups";
import s from "./devices.module.css";

type Tab = "overview" | "charts" | "control" | "all" | "messages";
const TABS: { key: Tab; label: string }[] = [
  { key: "overview", label: "Przegląd" },
  { key: "charts", label: "Wykresy" },
  { key: "control", label: t.control.tab },
  { key: "all", label: "Wszystkie cechy" },
  { key: "messages", label: "Komunikaty" },
];

export default function DevicePage() {
  const { tid = "", id = "" } = useParams();
  const [params, setParams] = useSearchParams();
  const tab = (params.get("tab") as Tab) || "overview";
  const me = useMe();
  const qc = useQueryClient();
  const device = useQuery({ queryKey: ["device", tid, id], queryFn: () => devicesApi.get(tid, id), refetchInterval: 30_000, staleTime: 10_000 });
  const features = useQuery({ queryKey: ["features", tid, id], queryFn: () => devicesApi.features(tid, id), refetchInterval: 60_000, staleTime: 10_000 });
  const refresh = useMutation({
    mutationFn: () => devicesApi.refresh(tid, id),
    onSuccess: () => setTimeout(() => qc.invalidateQueries({ queryKey: ["features", tid, id] }), 8000),
  });
  const rows = useMemo(() => features.data?.results ?? [], [features.data]);
  const enabledRows = useMemo(() => rows.filter((r) => r.is_enabled && hasValues(r)), [rows]);
  const groups = useMemo(() => groupRows(enabledRows), [enabledRows]);

  if (device.isPending) return <Skeleton height={48} />;
  if (device.isError || !device.data) return <Alert tone="error">{t.errors.notFound}</Alert>;
  const d = device.data;
  const canRefresh = me.data?.role !== "tenant_user";
  const canEdit = me.data?.role !== "tenant_user";

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
          {canEdit && (
            <Link to={`/t/${tid}/devices/${id}/settings`} className={s.buttonLink}>
              {t.devices.settings}
            </Link>
          )}
        </div>
      </div>
      <div className={s.sub} style={{ marginBottom: "var(--sp-3)" }}>
        {d.model || "—"}
        {d.location_text ? ` · ${d.location_text}` : ""}
        {d.description ? ` · ${d.description}` : ""} · {t.devices.lastSeen}: {formatDateTime(d.last_seen_at)}
      </div>
      {refresh.isSuccess && <Alert tone="ok">{t.devices.refreshQueued}</Alert>}
      {refresh.isError && (
        <Alert tone="error">{refresh.error instanceof ApiError && refresh.error.code === "budget_reserve_exhausted" ? t.devices.reserveExhausted : t.common.error}</Alert>
      )}
      {d.status_detail && d.status !== "online" && <Alert tone="warn">{d.status_detail}</Alert>}

      <div className={s.tabs} role="tablist">
        {TABS.map((tb) => (
          <button key={tb.key} type="button" role="tab" aria-selected={tab === tb.key} className={`${s.tab} ${tab === tb.key ? s.tabActive : ""}`} onClick={() => setParams({ tab: tb.key }, { replace: true })}>
            {tb.label}
          </button>
        ))}
      </div>

      {features.isPending && <Skeleton height={120} />}
      {features.data && features.data.count === 0 && (
        <Card>
          <p className={s.sub}>{t.devices.noFeatures}</p>
        </Card>
      )}

      {tab === "overview" &&
        groups
          .filter((g) => g.key !== "messages")
          .map((g) => (
            <section key={g.key} className={s.section}>
              <h2 className={s.sectionTitle}>{groupLabel(g.key)}</h2>
              <div className={s.widgets}>
                {g.rows.flatMap((row) =>
                  Object.entries(row.properties)
                    .filter(([, p]) => p.value !== null && p.value !== undefined)
                    .map(([prop, p]) => <PropertyWidget key={`${row.feature_name}:${prop}`} tid={tid} id={id} row={row} prop={prop} p={p} />),
                )}
              </div>
            </section>
          ))}

      {tab === "charts" && <ChartsTab tid={tid} id={id} rows={enabledRows} />}

      {tab === "control" && <ControlTab tid={tid} device={d} rows={rows} />}

      {tab === "all" && (
        <Card title={t.devices.allFeatures}>
          <AllFeaturesTable rows={rows} tid={tid} id={id} />
        </Card>
      )}

      {tab === "messages" && <MessagesTab tid={tid} id={id} />}
    </>
  );
}

function ChartsTab({ tid, id, rows }: { tid: string; id: string; rows: FeatureRow[] }) {
  const numeric = rows.flatMap((r) =>
    Object.entries(r.properties)
      .filter(([, p]) => p.type === "number" && typeof p.value === "number" && p.unit)
      .map(([prop]) => ({ row: r, prop })),
  );
  return (
    <div className={s.chartGrid}>
      {numeric.map(({ row, prop }) => (
        <MiniChart key={`${row.feature_name}:${prop}`} tid={tid} id={id} row={row} prop={prop} />
      ))}
      {numeric.length === 0 && <p className={s.sub}>{t.devices.noHistory}</p>}
    </div>
  );
}

function MiniChart({ tid, id, row, prop }: { tid: string; id: string; row: FeatureRow; prop: string }) {
  const to = new Date();
  const from = new Date(to.getTime() - 24 * 3600e3);
  const h = useQuery({
    queryKey: ["mini", tid, id, row.feature_name, prop, from.toISOString().slice(0, 13)],
    queryFn: () => devicesApi.history(tid, id, { feature: row.feature_name, property: prop, from: from.toISOString(), to: to.toISOString(), max_points: 400 }),
    staleTime: 60_000,
  });
  const label = `${row.label_pl ?? row.feature_name}${prop !== "value" ? ` · ${prop}` : ""}`;
  return (
    <Link to={`/t/${tid}/devices/${id}/chart?feature=${encodeURIComponent(row.feature_name)}&property=${encodeURIComponent(prop)}&range=day`} className={s.chartCard} title={t.charts.openExplorer}>
      <div className={s.chartCardTitle}>{label}</div>
      <div className={s.mono}>{row.feature_name}</div>
      {h.isPending && <Skeleton height={140} />}
      {h.data && h.data.points.length > 0 && <ChartLine series={[{ key: row.feature_name, label, history: h.data }]} height={160} compact />}
      {h.data && h.data.points.length === 0 && <p className={s.sub}>{t.devices.noHistory}</p>}
    </Link>
  );
}

function AllFeaturesTable({ rows, tid, id }: { rows: FeatureRow[]; tid: string; id: string }) {
  const groups = groupRows(rows);
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
            <GroupRows key={g.key} tid={tid} id={id} label={groupLabel(g.key)} rows={g.rows} />
          ))}
        </tbody>
      </table>
    </div>
  );
}

function GroupRows({ tid, id, label, rows }: { tid: string; id: string; label: string; rows: FeatureRow[] }) {
  return (
    <>
      <tr className={s.groupRow}>
        <td colSpan={4}>{label}</td>
      </tr>
      {rows.map((row) => {
        const entries = Object.entries(row.properties);
        const title = row.label_pl ?? row.feature_name.split(".").slice(-2).join(".");
        if (entries.length === 0) {
          return (
            <tr key={row.feature_name} className={s.disabled}>
              <td>
                <div>{title}</div>
                <div className={s.mono}>{row.feature_name}</div>
              </td>
              <td colSpan={3} className={s.sub}>
                {row.is_enabled ? t.devices.noValue : t.devices.disabledFeature}
              </td>
            </tr>
          );
        }
        return entries.map(([prop, p], i) => {
          const numeric = p.type === "number" && typeof p.value === "number";
          return (
            <tr key={`${row.feature_name}:${prop}`} className={row.is_enabled ? undefined : s.disabled}>
              <td>
                {i === 0 && (
                  <>
                    <div>
                      {title}
                      {row.is_enabled ? "" : ` (${t.devices.disabledFeature})`}
                    </div>
                    <div className={s.mono}>{row.feature_name}</div>
                  </>
                )}
              </td>
              <td className={s.mono}>{prop}</td>
              <td className={s.value}>
                {numeric ? (
                  <Link to={`/t/${tid}/devices/${id}/chart?feature=${encodeURIComponent(row.feature_name)}&property=${encodeURIComponent(prop)}`} style={{ color: "var(--accent)" }}>
                    {formatValue(p.value, p.unit)}
                  </Link>
                ) : (
                  formatValue(p.value, p.unit)
                )}
              </td>
              <td className={s.sub}>{formatDateTime(p.ts_device ?? p.ts_polled)}</td>
            </tr>
          );
        });
      })}
    </>
  );
}

function MessagesTab({ tid, id }: { tid: string; id: string }) {
  const q = useQuery({ queryKey: ["messages", tid, id], queryFn: () => devicesApi.messages(tid, id), refetchInterval: 60_000 });
  if (q.isPending) return <Skeleton height={80} />;
  if (q.isError || !q.data) return <Alert tone="error">{t.common.error}</Alert>;
  const active = q.data.features.flatMap((f) =>
    Object.entries(f.properties)
      .filter(([, p]) => Array.isArray(p.value) && p.value.length > 0)
      .map(([prop, p]) => ({ feature: f, prop, value: p.value as unknown[] })),
  );
  return (
    <>
      <Card title={t.messages.current}>
        {active.length === 0 && <p className={s.sub}>{t.messages.none}</p>}
        {active.map((a) => (
          <div key={`${a.feature.feature_name}:${a.prop}`} className={s.messageRow}>
            <div>
              <strong>{a.feature.label_pl ?? a.feature.feature_name}</strong> <span className={s.mono}>{a.feature.feature_name}</span>
            </div>
            <pre className={s.json}>{JSON.stringify(a.value, null, 2)}</pre>
          </div>
        ))}
      </Card>
      <div style={{ height: "var(--sp-4)" }} />
      <Card title={t.messages.history}>
        {q.data.history.length === 0 && <p className={s.sub}>{t.messages.noHistory}</p>}
        {q.data.history.map((h, i) => (
          <div key={i} className={s.messageRow}>
            <div className={s.sub}>
              {formatDateTime(h.ts)} · <span className={s.mono}>{h.feature_name}</span>
            </div>
            <pre className={s.json}>{JSON.stringify(h.value, null, 2)}</pre>
          </div>
        ))}
      </Card>
    </>
  );
}
