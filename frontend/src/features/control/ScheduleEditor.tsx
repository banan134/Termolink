import { Button } from "@/components/ui";
import { t } from "@/i18n/pl";
import s from "./control.module.css";

export type ScheduleEntry = { start: string; end: string; mode?: string; position?: number };
export type Schedule = Record<string, ScheduleEntry[]>;

const DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"] as const;

/** Simple schedule editor (docs/13 stage 4): per day a list of start–end(–mode) rows + copy to all days. */
export function ScheduleEditor({ name, value, constraints, onChange, error }: { name: string; value: Schedule; constraints: { modes?: string[]; maxEntries?: number }; onChange: (v: Schedule) => void; error?: string[] }) {
  const update = (day: string, entries: ScheduleEntry[]) => onChange({ ...value, [day]: entries });
  const modes = constraints.modes ?? [];
  return (
    <div className={s.schedule}>
      <div className={s.sub}>{name}</div>
      {DAYS.map((day) => {
        const entries = value[day] ?? [];
        return (
          <div key={day} className={s.scheduleDay}>
            <div className={s.scheduleDayName}>{t.control.days[day]}</div>
            <div className={s.scheduleEntries}>
              {entries.map((e, i) => (
                <div key={i} className={s.scheduleEntry}>
                  <input type="time" value={e.start} aria-label={`${t.control.days[day]} start`} onChange={(ev) => update(day, entries.map((x, j) => (j === i ? { ...x, start: ev.target.value } : x)))} />
                  <span>–</span>
                  <input type="time" value={e.end} aria-label={`${t.control.days[day]} koniec`} onChange={(ev) => update(day, entries.map((x, j) => (j === i ? { ...x, end: ev.target.value } : x)))} />
                  {modes.length > 0 && (
                    <select value={e.mode ?? modes[0]} aria-label="tryb" onChange={(ev) => update(day, entries.map((x, j) => (j === i ? { ...x, mode: ev.target.value } : x)))}>
                      {modes.map((m) => (
                        <option key={m} value={m}>
                          {t.control.enumLabel(m)}
                        </option>
                      ))}
                    </select>
                  )}
                  <button type="button" className={s.linkButton} onClick={() => update(day, entries.filter((_, j) => j !== i))} aria-label={t.common.cancel}>
                    ✕
                  </button>
                </div>
              ))}
              {(constraints.maxEntries === undefined || entries.length < constraints.maxEntries) && (
                <button type="button" className={s.linkButton} onClick={() => update(day, [...entries, { start: "06:00", end: "22:00", mode: modes[0], position: entries.length }])}>
                  + {t.control.addEntry}
                </button>
              )}
              {day === "mon" && entries.length > 0 && (
                <Button type="button" variant="ghost" onClick={() => onChange(Object.fromEntries(DAYS.map((d) => [d, entries.map((e) => ({ ...e }))])))}>
                  {t.control.copyToAll}
                </Button>
              )}
            </div>
          </div>
        );
      })}
      {error && <span className={s.error}>{error.join(" ")}</span>}
    </div>
  );
}
