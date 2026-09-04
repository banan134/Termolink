import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { alertsApi } from "@/api/alerts";
import { devicesApi, type OverviewDevice } from "@/api/devices";
import { PageTitle } from "@/app/AppLayout";
import { Card, Chip, EmptyState, Field, Skeleton } from "@/components/ui";
import { AlertItem } from "@/features/alerts/AlertsPage";
import { DeviceMap } from "@/features/devices/DeviceMap";
import { ModeChip, StatusChip } from "@/features/devices/StatusChip";
import { formatDateTime, formatValue } from "@/features/devices/format";
import { t } from "@/i18n/pl";
import s from "./home.module.css";

/** Panel operatora (docs/09): wszystkie kotły klientów na jednym ekranie + mapa. */
export function OperatorDashboard() {
  const overview = useQuery({ queryKey: ["overview"], queryFn: devicesApi.overview, refetchInterval: 30_000 });
  const alerts = useQuery({ queryKey: ["admin-alerts"], queryFn: alertsApi.adminOpen, refetchInterval: 30_000 });
  const [filter, setFilter] = useState("");
  const devices = useMemo(() => overview.data?.tenants.flatMap((tn) => tn.devices) ?? [], [overview.data]);
  const filtered = useMemo(() => {
    const f = filter.trim().toLowerCase();
    if (!f) return overview.data?.tenants ?? [];
    return (overview.data?.tenants ?? [])
      .map((tn) => ({ ...tn, devices: tn.devices.filter((d) => `${tn.name} ${d.display_name} ${d.model} ${d.location_text ?? ""}`.toLowerCase().includes(f)) }))
      .filter((tn) => tn.devices.length > 0 || tn.name.toLowerCase().includes(f));
  }, [overview.data, filter]);

  if (overview.isPending) return <Skeleton height={200} />;
  if (!overview.data) return <EmptyState title={t.common.error} />;
  const tot = overview.data.totals;
  const down = (tot.by_status.offline ?? 0) + (tot.by_status.error ?? 0);

  return (
    <>
      <PageTitle>{t.operator.title}</PageTitle>
      <div className={s.kpis}>
        <Kpi value={tot.tenants} label={t.operator.tenants} />
        <Kpi value={tot.devices} label={t.operator.devices} />
        <Kpi value={tot.by_status.online ?? 0} label={t.operator.online} tone="ok" />
        <Kpi value={down} label={t.operator.offline} tone={down ? "bad" : undefined} />
        <Kpi value={tot.open_alerts} label={t.operator.alerts} tone={tot.open_alerts ? "warn" : undefined} />
        <Kpi value={tot.control_mode} label={t.operator.control} />
      </div>

      <div className={s.grid}>
        <Card title={t.operator.map}>
          <DeviceMap devices={devices} linkFor={(d) => `/t/${d.tenant_id}/devices/${d.id}`} />
        </Card>
        <Card title={t.operator.alertsList}>
          {alerts.data && alerts.data.results.length === 0 && <p className={s.sub}>{t.operator.noAlerts}</p>}
          <div className={s.alerts}>
            {alerts.data?.results.slice(0, 8).map((a) => (
              <AlertItem key={a.id} alert={a} tid={a.tenant_id ?? undefined} />
            ))}
          </div>
        </Card>
      </div>

      <Card title={t.operator.devicesList}>
        <Field label={t.operator.filter} value={filter} onChange={(e) => setFilter(e.target.value)} />
        {filtered.map((tn) => (
          <section key={tn.id} className={s.tenant}>
            <div className={s.tenantHead}>
              <Link to={`/admin/tenants/${tn.id}`} className={s.link}>
                <b>{tn.name}</b>
              </Link>
              {tn.open_alerts > 0 && <Chip tone="off">{t.alerts.openCount(tn.open_alerts)}</Chip>}
              {!tn.control_allowed && <Chip tone="read">{t.admin.controlBlocked}</Chip>}
              <span style={{ flex: 1 }} />
              <Link to={`/t/${tn.id}`} className={s.link}>
                {t.operator.open}
              </Link>
            </div>
            <div className={s.tiles}>
              {tn.devices.map((d) => (
                <DeviceTile key={d.id} d={d} />
              ))}
            </div>
          </section>
        ))}
      </Card>

      <Card title={t.operator.accounts}>
        <div className={s.accounts}>
          {overview.data.accounts.map((a) => (
            <div key={a.id} className={s.account}>
              <div>
                <b>{a.tenant_name}</b> <span className={s.sub}>· {a.label || a.provider}</span>
              </div>
              <div className={s.sub}>
                {t.providers.status[a.status as keyof typeof t.providers.status] ?? a.status} · {a.budget.used} / {a.budget.limit} ({Math.round((100 * a.budget.used) / Math.max(a.budget.limit, 1))} %) · {t.providers.reserve}: {a.budget.reserve_used} / {a.budget.reserve}
              </div>
              <div className={s.bar}>
                <div className={s.barFill} style={{ width: `${Math.min(100, (100 * a.budget.used) / Math.max(a.budget.limit, 1))}%` }} />
              </div>
            </div>
          ))}
        </div>
      </Card>
    </>
  );
}

function Kpi({ value, label, tone }: { value: number; label: string; tone?: "ok" | "bad" | "warn" }) {
  return (
    <div className={`${s.kpi} ${tone ? s[`kpi_${tone}`] : ""}`}>
      <div className={s.kpiValue}>{value}</div>
      <div className={s.sub}>{label}</div>
    </div>
  );
}

function DeviceTile({ d }: { d: OverviewDevice }) {
  return (
    <Link to={`/t/${d.tenant_id}/devices/${d.id}`} className={`${s.tile} ${d.status !== "online" ? s.tileDown : ""}`}>
      <div className={s.tileTop}>
        <b>{d.display_name}</b>
        <StatusChip status={d.status} />
        <ModeChip mode={d.mode} />
        {d.open_alerts > 0 && <Chip tone="off">{d.open_alerts}</Chip>}
      </div>
      <div className={s.sub}>
        {d.model}
        {d.location_text ? ` · ${d.location_text}` : ""} · {formatDateTime(d.last_seen_at)}
      </div>
      <div className={s.highlights}>
        {d.highlights.slice(0, 3).map((h) => (
          <span key={`${h.feature}.${h.property}`}>
            {h.label}: <b>{formatValue(h.value, h.unit)}</b>
          </span>
        ))}
      </div>
    </Link>
  );
}
