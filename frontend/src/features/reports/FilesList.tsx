import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { reportsApi, type ReportFile } from "@/api/reports";
import { Button, Card, Chip } from "@/components/ui";
import { formatDateTime } from "@/features/devices/format";
import { t } from "@/i18n/pl";
import s from "./reports.module.css";

/** Generated files — polled while any is pending (docs/10: link, not attachment). */
export function FilesList({ tid, canManage }: { tid: string; canManage: boolean }) {
  const qc = useQueryClient();
  const files = useQuery({
    queryKey: ["report-files", tid],
    queryFn: () => reportsApi.files(tid),
    refetchInterval: (q) => (q.state.data?.results.some((f) => f.status === "pending") ? 3000 : 60_000),
    refetchIntervalInBackground: true,
  });
  const remove = useMutation({ mutationFn: (id: string) => reportsApi.deleteFile(tid, id), onSuccess: () => qc.invalidateQueries({ queryKey: ["report-files", tid] }) });
  const rows = files.data?.results ?? [];
  return (
    <Card title={t.reports.files}>
      {rows.length === 0 && <p className={s.sub}>{t.reports.noFiles}</p>}
      {rows.length > 0 && (
        <div className={s.tableWrap}>
          <table className={s.table}>
            <thead>
              <tr>
                <th>{t.reports.createdAt}</th>
                <th>{t.reports.type}</th>
                <th>{t.reports.format}</th>
                <th>{t.reports.range}</th>
                <th>{t.reports.status}</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {rows.map((f) => (
                <tr key={f.id}>
                  <td>
                    {formatDateTime(f.created_at)}
                    {f.schedule_name && <div className={s.sub}>{f.schedule_name}</div>}
                    {f.requested_by && !f.schedule_name && <div className={s.sub}>{f.requested_by}</div>}
                  </td>
                  <td>{t.reports.types[f.report_type]}</td>
                  <td>{f.format.toUpperCase()}</td>
                  <td>
                    {formatDateTime(f.params.from)} – {formatDateTime(f.params.to)}
                  </td>
                  <td>
                    <FileStatus f={f} />
                  </td>
                  <td className={s.rowActions}>
                    {f.status === "done" && (
                      <a href={reportsApi.downloadUrl(tid, f.id)} className={s.buttonLink} download={f.filename}>
                        {t.reports.download}
                        {f.size_bytes ? ` (${Math.max(1, Math.round(f.size_bytes / 1024))} KB)` : ""}
                      </a>
                    )}
                    {canManage && (
                      <Button variant="ghost" onClick={() => remove.mutate(f.id)} loading={remove.isPending && remove.variables === f.id}>
                        {t.common.delete}
                      </Button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}

function FileStatus({ f }: { f: ReportFile }) {
  if (f.status === "done") return <Chip tone="ok">{t.reports.fileStatus.done}</Chip>;
  if (f.status === "failed")
    return (
      <span>
        <Chip tone="off">{t.reports.fileStatus.failed}</Chip>
        {f.error && <div className={s.sub}>{f.error}</div>}
      </span>
    );
  return <Chip tone="neutral">{t.reports.fileStatus.pending}</Chip>;
}
