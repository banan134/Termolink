import { useQuery } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";
import { devicesApi, type DeviceCard } from "@/api/devices";
import { PageTitle } from "@/app/AppLayout";
import { Alert, EmptyState, Skeleton } from "@/components/ui";
import { useMe } from "@/features/auth/useMe";
import { t } from "@/i18n/pl";
import { ModeChip, StatusChip } from "./StatusChip";
import { formatDateTime, formatValue } from "./format";
import s from "./devices.module.css";

function Card({ tid, d }: { tid: string; d: DeviceCard }) {
  return (
    <Link to={`/t/${tid}/devices/${d.id}`} className={s.card}>
      <div className={s.cardHead}>
        <div>
          <h3 className={s.name}>{d.display_name}</h3>
          <div className={s.sub}>
            {d.model || "—"}
            {d.location_text ? ` · ${d.location_text}` : ""}
          </div>
        </div>
        <div className={s.chips}>
          <StatusChip status={d.status} />
          <ModeChip mode={d.mode} />
        </div>
      </div>
      {d.highlights.length > 0 && (
        <div className={s.tiles}>
          {d.highlights.map((h) => (
            <div className={s.tile} key={h.feature + h.property}>
              <div className={s.tileValue}>{formatValue(h.value, h.unit)}</div>
              <div className={s.tileLabel}>{h.label}</div>
            </div>
          ))}
        </div>
      )}
      <div className={s.sub} style={{ marginTop: "var(--sp-2)" }}>
        {t.devices.lastSeen}: {formatDateTime(d.last_seen_at)}
      </div>
    </Link>
  );
}

/** /t/:tid — customer dashboard: device cards (docs/09). Operators see the banner. */
export default function DevicesPage() {
  const { tid = "" } = useParams();
  const me = useMe();
  const devices = useQuery({ queryKey: ["devices", tid], queryFn: () => devicesApi.list(tid), refetchInterval: 60_000 });
  const title = me.data?.tenant && me.data.tenant.id === tid ? me.data.tenant.name : t.devices.title;
  return (
    <>
      <PageTitle>{title}</PageTitle>
      {devices.isPending && <Skeleton height={120} />}
      {devices.isError && <Alert tone="error">{t.errors.notFound}</Alert>}
      {devices.data?.count === 0 && <EmptyState title={t.devices.empty}>{t.devices.emptyHelp}</EmptyState>}
      <div className={s.grid}>{devices.data?.results.map((d) => <Card key={d.id} tid={tid} d={d} />)}</div>
    </>
  );
}
