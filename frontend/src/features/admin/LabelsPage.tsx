import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { labelsApi, type FeatureLabelRow } from "@/api/devices";
import { ApiError } from "@/api/client";
import { PageTitle } from "@/app/AppLayout";
import { Alert, Button, Card, Field, Skeleton } from "@/components/ui";
import { t } from "@/i18n/pl";
import a from "./admin.module.css";
import d from "@/features/devices/devices.module.css";

const GROUPS = ["", "sensors", "dhw", "heat_source", "solar", "ventilation", "buffer", "statistics", "messages", "device", "other"];

/** /admin/labels — operator dictionary editor (docs/13 stage 3). Saves the whole table (PUT). */
export default function LabelsPage() {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["labels"], queryFn: labelsApi.list });
  const [rows, setRows] = useState<FeatureLabelRow[]>([]);
  const [filter, setFilter] = useState("");
  useEffect(() => {
    if (q.data) setRows(q.data.results);
  }, [q.data]);
  const save = useMutation({
    mutationFn: () => labelsApi.replace(rows),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["labels"] }),
  });
  const update = (i: number, patch: Partial<FeatureLabelRow>) => setRows((r) => r.map((row, j) => (j === i ? { ...row, ...patch } : row)));
  const visible = rows.map((row, i) => ({ row, i })).filter(({ row }) => !filter || row.pattern.includes(filter) || row.label_pl.toLowerCase().includes(filter.toLowerCase()));

  return (
    <>
      <PageTitle>{t.nav.labels}</PageTitle>
      <Card>
        <p className={a.muted} style={{ whiteSpace: "normal" }}>{t.labels.help}</p>
        {save.isSuccess && <Alert tone="ok">{t.labels.saved}</Alert>}
        {save.isError && <Alert tone="error">{save.error instanceof ApiError ? save.error.message : t.common.error}</Alert>}
        <div className={d.header}>
          <Field label={t.labels.filter} value={filter} onChange={(e) => setFilter(e.target.value)} />
          <div className={d.headerActions}>
            <Button variant="secondary" onClick={() => setRows((r) => [{ pattern: "", label_pl: "", description_pl: "", group_key: null, sort: 100, highlight: false, report_default: false, command_property_map: {} }, ...r])}>
              {t.labels.add}
            </Button>
            <Button loading={save.isPending} onClick={() => save.mutate()} disabled={rows.some((r) => !r.pattern.trim())}>
              {t.common.save}
            </Button>
          </div>
        </div>
        {q.isPending && <Skeleton height={80} />}
        <div className={d.scroll}>
          <table className={d.table}>
            <thead>
              <tr>
                <th>{t.labels.pattern}</th>
                <th>{t.labels.label}</th>
                <th>{t.labels.group}</th>
                <th>{t.labels.sort}</th>
                <th>{t.labels.highlight}</th>
                <th>{t.labels.report}</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {visible.map(({ row, i }) => (
                <tr key={i}>
                  <td><input className={d.cellInput} value={row.pattern} onChange={(e) => update(i, { pattern: e.target.value })} /></td>
                  <td><input className={d.cellInput} value={row.label_pl} onChange={(e) => update(i, { label_pl: e.target.value })} /></td>
                  <td>
                    <select className={d.cellInput} value={row.group_key ?? ""} onChange={(e) => update(i, { group_key: e.target.value || null })}>
                      {GROUPS.map((g) => (
                        <option key={g} value={g}>{g || t.labels.groupAuto}</option>
                      ))}
                    </select>
                  </td>
                  <td><input className={d.cellInput} type="number" value={row.sort} onChange={(e) => update(i, { sort: Number(e.target.value) })} style={{ width: 70 }} /></td>
                  <td><input type="checkbox" checked={row.highlight} onChange={(e) => update(i, { highlight: e.target.checked })} /></td>
                  <td><input type="checkbox" checked={row.report_default} onChange={(e) => update(i, { report_default: e.target.checked })} /></td>
                  <td><button type="button" className={d.iconButton} onClick={() => setRows((r) => r.filter((_, j) => j !== i))} aria-label={t.labels.remove}>×</button></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
    </>
  );
}
