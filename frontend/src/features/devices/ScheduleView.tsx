import { t } from "@/i18n/pl";
import { enumLabel } from "./format";
import s from "./devices.module.css";

type Entry = { start?: string; end?: string; mode?: string; position?: number };
type Schedule = Record<string, Entry[]>;
const DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"] as const;

/** Readable weekly schedule: one line per day, "06:00–22:00 komfort · …" (docs/09 widget schedule). */
export function ScheduleView({ value, compact = false }: { value: unknown; compact?: boolean }) {
  if (!value || typeof value !== "object" || Array.isArray(value)) return <span>{t.widgets.empty}</span>;
  const schedule = value as Schedule;
  const days = DAYS.filter((d) => Array.isArray(schedule[d]));
  if (days.length === 0) return <span>{t.widgets.empty}</span>;
  // collapse identical consecutive days ("Pon–Pt")
  const groups: { from: string; to: string; entries: Entry[] }[] = [];
  for (const d of days) {
    const entries = [...schedule[d]].sort((a, b) => (a.start ?? "").localeCompare(b.start ?? ""));
    const last = groups[groups.length - 1];
    if (last && JSON.stringify(last.entries) === JSON.stringify(entries) && DAYS.indexOf(d) === DAYS.indexOf(last.to as (typeof DAYS)[number]) + 1) last.to = d;
    else groups.push({ from: d, to: d, entries });
  }
  return (
    <div className={compact ? s.scheduleCompact : s.schedule}>
      {groups.map((g) => (
        <div key={g.from} className={s.scheduleRow}>
          <span className={s.scheduleDay}>
            {t.control.days[g.from as keyof typeof t.control.days]}
            {g.to !== g.from ? `–${t.control.days[g.to as keyof typeof t.control.days]}` : ""}
          </span>
          <span className={s.scheduleEntries}>
            {g.entries.length === 0 && <span className={s.sub}>{t.widgets.scheduleNone}</span>}
            {g.entries.map((e, i) => (
              <span key={i} className={s.scheduleEntry}>
                {e.start}–{e.end}
                {e.mode ? ` ${enumLabel(e.mode)}` : ""}
              </span>
            ))}
          </span>
        </div>
      ))}
    </div>
  );
}
