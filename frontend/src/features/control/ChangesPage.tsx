import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { controlApi } from "@/api/control";
import { Card, EmptyState, Skeleton } from "@/components/ui";
import { PageTitle } from "@/app/AppLayout";
import { formatDateTime } from "@/features/devices/format";
import { t } from "@/i18n/pl";
import { StatusChip } from "./ControlTab";
import s from "./control.module.css";

/** Dziennik zmian (docs/04 GET /tenants/{tid}/commands). */
export default function ChangesPage() {
  const { tid = "" } = useParams();
  const [status, setStatus] = useState("");
  const [page, setPage] = useState(1);
  const list = useQuery({ queryKey: ["commands", tid, status, page], queryFn: () => controlApi.list(tid, { status, page, page_size: 50 }), refetchInterval: 15_000 });
  const pages = Math.max(1, Math.ceil((list.data?.count ?? 0) / 50));
  return (
    <>
      <PageTitle>{t.nav.changes}</PageTitle>
      <div className={s.filters}>
        <select value={status} onChange={(e) => (setStatus(e.target.value), setPage(1))} className={s.select} aria-label={t.control.filterStatus}>
          <option value="">{t.control.allStatuses}</option>
          {Object.entries(t.control.status).map(([k, v]) => (
            <option key={k} value={k}>
              {v}
            </option>
          ))}
        </select>
      </div>
      {list.isPending && <Skeleton height={120} />}
      {list.data && list.data.count === 0 && <EmptyState title={t.control.noChanges} />}
      {list.data && list.data.count > 0 && (
        <Card>
          <div className={s.tableWrap}>
            <table className={s.table}>
              <thead>
                <tr>
                  <th>{t.control.when}</th>
                  <th>{t.devices.title}</th>
                  <th>{t.control.what}</th>
                  <th>{t.control.before}</th>
                  <th>{t.control.after}</th>
                  <th>{t.control.who}</th>
                  <th>{t.control.statusLabel}</th>
                </tr>
              </thead>
              <tbody>
                {list.data.results.map((c) => (
                  <tr key={c.id}>
                    <td>{formatDateTime(c.created_at)}</td>
                    <td>
                      <Link to={`/t/${tid}/devices/${c.device_id}?tab=control`} style={{ color: "var(--accent)" }}>
                        {c.device_name}
                      </Link>
                    </td>
                    <td>
                      {t.control.commandLabel(c.command_name)}
                      <div className={s.mono}>{c.feature_name}</div>
                    </td>
                    <td>{short(c.value_before)}</td>
                    <td>{short(c.value_after)}</td>
                    <td>
                      {c.user_email ?? "—"}
                      {c.acted_as_operator && <span className={s.sub}> ({t.control.operator})</span>}
                    </td>
                    <td>
                      <StatusChip status={c.status} />
                      {c.reject_reason && <div className={s.sub}>{c.reject_reason}</div>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {pages > 1 && (
            <div className={s.actions}>
              <button type="button" className={s.linkButton} disabled={page <= 1} onClick={() => setPage(page - 1)}>
                ◀
              </button>
              <span className={s.sub}>
                {page} / {pages}
              </span>
              <button type="button" className={s.linkButton} disabled={page >= pages} onClick={() => setPage(page + 1)}>
                ▶
              </button>
            </div>
          )}
        </Card>
      )}
    </>
  );
}

function short(v: Record<string, unknown> | null): string {
  if (!v) return "—";
  return Object.values(v)
    .map((x) => (x === null || x === undefined ? "—" : typeof x === "object" ? t.control.scheduleValue : String(x)))
    .join(", ");
}
