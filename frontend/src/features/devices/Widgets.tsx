import { Link } from "react-router-dom";
import type { FeatureProperty, FeatureRow } from "@/api/devices";
import { Chip } from "@/components/ui";
import { Sparkline } from "@/features/charts/Sparkline";
import { unitLabel } from "@/features/charts/chartTheme";
import { t } from "@/i18n/pl";
import { formatDateTime, formatValue } from "./format";
import s from "./devices.module.css";

/** Generic per-property widget (docs/09 §Karta urządzenia — Przegląd, rendering generyczny). */
export function PropertyWidget({ tid, id, row, prop, p }: { tid: string; id: string; row: FeatureRow; prop: string; p: FeatureProperty }) {
  const label = row.label_pl ?? row.feature_name.split(".").slice(-2).join(".");
  const propLabel = prop === "value" ? "" : ` · ${prop}`;
  const explorer = `/t/${tid}/devices/${id}/chart?feature=${encodeURIComponent(row.feature_name)}&property=${encodeURIComponent(prop)}`;

  if (p.type === "number" && typeof p.value === "number") {
    return (
      <Link to={explorer} className={s.tileLink} title={t.charts.openExplorer}>
        <div className={s.tileValue}>
          {Number.isInteger(p.value) ? p.value : p.value.toFixed(1)} <span className={s.tileUnit}>{unitLabel(p.unit)}</span>
        </div>
        <div className={s.tileLabel}>
          {label}
          {propLabel}
        </div>
        <Sparkline tid={tid} id={id} feature={row.feature_name} property={prop} />
        <div className={s.mono}>{row.feature_name}</div>
      </Link>
    );
  }
  if (p.type === "boolean") {
    return (
      <div className={s.tileStatic}>
        <div>
          <Chip tone={p.value ? "ok" : "read"}>{p.value ? t.widgets.on : t.widgets.off}</Chip>
        </div>
        <div className={s.tileLabel}>
          {label}
          {propLabel}
        </div>
        <div className={s.mono}>{row.feature_name}</div>
      </div>
    );
  }
  if (p.type === "schedule") {
    const days = p.value && typeof p.value === "object" ? Object.entries(p.value as Record<string, unknown[]>) : [];
    const total = days.reduce((n, [, entries]) => n + (Array.isArray(entries) ? entries.length : 0), 0);
    return (
      <div className={s.tileStatic}>
        <div className={s.tileValue} style={{ fontSize: "var(--fs-md)" }}>
          {t.widgets.scheduleSummary(days.length, total)}
        </div>
        <div className={s.tileLabel}>{label}</div>
        <div className={s.mono}>{row.feature_name}</div>
      </div>
    );
  }
  if (p.type === "array" || p.type === "object") {
    const empty = Array.isArray(p.value) ? p.value.length === 0 : !p.value || Object.keys(p.value as object).length === 0;
    return (
      <details className={s.tileStatic}>
        <summary className={s.tileLabel} style={{ cursor: "pointer" }}>
          {label}
          {propLabel} {empty ? <span className={s.mono}>{t.widgets.empty}</span> : ""}
        </summary>
        <pre className={s.json}>{JSON.stringify(p.value, null, 2)}</pre>
        <div className={s.mono}>{row.feature_name}</div>
      </details>
    );
  }
  return (
    <div className={s.tileStatic}>
      <div className={s.tileValue} style={{ fontSize: "var(--fs-md)" }}>{formatValue(p.value, p.unit)}</div>
      <div className={s.tileLabel}>
        {label}
        {propLabel} · {formatDateTime(p.ts_device ?? p.ts_polled)}
      </div>
      <div className={s.mono}>{row.feature_name}</div>
    </div>
  );
}
