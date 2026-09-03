import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { alertsApi, type AlertRow } from "@/api/alerts";
import { PageTitle } from "@/app/AppLayout";
import { Button, Card, Chip, EmptyState, Skeleton } from "@/components/ui";
import { useMe } from "@/features/auth/useMe";
import { formatDateTime } from "@/features/devices/format";
import { t } from "@/i18n/pl";
import s from "./alerts.module.css";

/** Alarmy klienta: otwarte/wszystkie, potwierdzanie (docs/10 §Alarmy, docs/04 §Alarmy). */
export default function AlertsPage() {
  const { tid = "" } = useParams();
  const me = useMe();
  const qc = useQueryClient();
  const [onlyOpen, setOnlyOpen] = useState(true);
  const [page, setPage] = useState(1);
  const list = useQuery({ queryKey: ["alerts", tid, onlyOpen, page], queryFn: () => alertsApi.list(tid, { open: onlyOpen, page, page_size: 50 }), refetchInterval: 30_000 });
  const ack = useMutation({ mutationFn: (id: string) => alertsApi.acknowledge(tid, id), onSuccess: () => qc.invalidateQueries({ queryKey: ["alerts", tid] }) });
  const canManage = me.data?.role !== "tenant_user";
  const pages = Math.max(1, Math.ceil((list.data?.count ?? 0) / 50));

  return (
    <>
      <div className={s.header}>
        <PageTitle>{t.alerts.title}</PageTitle>
        {list.data && list.data.open_count > 0 && <Chip tone="off">{t.alerts.openCount(list.data.open_count)}</Chip>}
        <span style={{ flex: 1 }} />
        <label className={s.toggle}>
          <input type="checkbox" checked={onlyOpen} onChange={(e) => (setOnlyOpen(e.target.checked), setPage(1))} /> {t.alerts.onlyOpen}
        </label>
        {canManage && (
          <Link to={`/t/${tid}/alert-rules`} className={s.buttonLink}>
            {t.alerts.rules}
          </Link>
        )}
      </div>
      {list.isPending && <Skeleton height={120} />}
      {list.data && list.data.count === 0 && <EmptyState title={onlyOpen ? t.alerts.noneOpen : t.alerts.none} />}
      {list.data && list.data.count > 0 && (
        <div className={s.list}>
          {list.data.results.map((a) => (
            <AlertItem key={a.id} alert={a} tid={tid} onAck={canManage ? () => ack.mutate(a.id) : undefined} acking={ack.isPending && ack.variables === a.id} />
          ))}
        </div>
      )}
      {pages > 1 && (
        <div className={s.pager}>
          <button type="button" className={s.linkButton} disabled={page <= 1} onClick={() => setPage(page - 1)}>
            ◀
          </button>
          <span>
            {page} / {pages}
          </span>
          <button type="button" className={s.linkButton} disabled={page >= pages} onClick={() => setPage(page + 1)}>
            ▶
          </button>
        </div>
      )}
    </>
  );
}

export function AlertItem({ alert, tid, onAck, acking }: { alert: AlertRow; tid?: string; onAck?: () => void; acking?: boolean }) {
  const open = alert.closed_at === null;
  return (
    <Card>
      <div className={`${s.item} ${open ? s[`sev_${alert.severity}`] : s.closed}`}>
        <div className={s.itemMain}>
          <div className={s.itemTop}>
            <Chip tone={open ? (alert.severity === "critical" ? "off" : "ctrl") : "neutral"}>{open ? t.alerts.severity[alert.severity] : t.alerts.closed}</Chip>
            <span className={s.type}>{t.alerts.types[alert.type] ?? alert.type}</span>
            {alert.tenant_name && <span className={s.sub}>· {alert.tenant_name}</span>}
            {alert.device_id && tid && (
              <Link to={`/t/${tid}/devices/${alert.device_id}`} className={s.deviceLink}>
                {alert.device_name}
              </Link>
            )}
          </div>
          <div className={s.message}>{alert.message}</div>
          <div className={s.sub}>
            {t.alerts.openedAt}: {formatDateTime(alert.opened_at)}
            {alert.closed_at && ` · ${t.alerts.closedAt}: ${formatDateTime(alert.closed_at)}`}
            {alert.acknowledged_at && ` · ${t.alerts.ackedBy(alert.acknowledged_by ?? "", formatDateTime(alert.acknowledged_at))}`}
            {alert.notified_at && ` · ${t.alerts.emailSent}`}
          </div>
        </div>
        {open && !alert.acknowledged_at && onAck && (
          <Button variant="secondary" loading={acking} onClick={onAck}>
            {t.alerts.acknowledge}
          </Button>
        )}
      </div>
    </Card>
  );
}
