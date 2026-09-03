import { Field } from "@/components/ui";
import { t } from "@/i18n/pl";
import { ScheduleEditor, type Schedule } from "./ScheduleEditor";
import type { ParamSchema } from "./params";
import s from "./control.module.css";

export function ParamInputs({ schema, values, onChange, errors }: { schema: Record<string, ParamSchema>; values: Record<string, unknown>; onChange: (v: Record<string, unknown>) => void; errors: Record<string, string[]> }) {
  const set = (name: string, v: unknown) => onChange({ ...values, [name]: v });
  if (Object.keys(schema).length === 0) return <p className={s.sub}>{t.control.noParams}</p>;
  return (
    <>
      {Object.entries(schema).map(([name, def]) => {
        const kind = def.type.toLowerCase();
        const c = def.constraints ?? {};
        const err = errors[name];
        if (kind === "number") {
          const value = typeof values[name] === "number" ? (values[name] as number) : (c.min ?? 0);
          const step = c.stepping ?? 1;
          return (
            <div key={name} className={s.numberRow}>
              <Field label={name} type="number" min={c.min} max={c.max} step={step} value={value} onChange={(e) => set(name, e.target.value === "" ? "" : Number(e.target.value))} error={err} help={t.control.rangeHelp(c.min, c.max, step)} />
              {c.min !== undefined && c.max !== undefined && (
                <input type="range" aria-label={name} min={c.min} max={c.max} step={step} value={value} onChange={(e) => set(name, Number(e.target.value))} className={s.slider} />
              )}
            </div>
          );
        }
        if (kind === "boolean") {
          return (
            <label key={name} className={s.ack}>
              <input type="checkbox" checked={Boolean(values[name])} onChange={(e) => set(name, e.target.checked)} /> {name}
              {err && <span className={s.error}>{err.join(", ")}</span>}
            </label>
          );
        }
        if (kind === "string" && c.enum) {
          return (
            <div key={name} className={s.form}>
              <label className={s.sub} htmlFor={`p-${name}`}>
                {name}
              </label>
              <select id={`p-${name}`} value={String(values[name] ?? "")} onChange={(e) => set(name, e.target.value)} className={s.select}>
                {c.enum.map((o) => (
                  <option key={o} value={o}>
                    {t.control.enumLabel(o)}
                  </option>
                ))}
              </select>
              {err && <span className={s.error}>{err.join(", ")}</span>}
            </div>
          );
        }
        if (kind === "string") {
          return <Field key={name} label={name} maxLength={c.maxLength} value={String(values[name] ?? "")} onChange={(e) => set(name, e.target.value)} error={err} />;
        }
        if (kind === "schedule") {
          return <ScheduleEditor key={name} name={name} value={(values[name] as Schedule) ?? {}} constraints={c} onChange={(v) => set(name, v)} error={err} />;
        }
        return (
          <div key={name} className={s.form}>
            <label className={s.sub} htmlFor={`p-${name}`}>
              {name} (JSON)
            </label>
            <textarea id={`p-${name}`} className={s.textarea} rows={4} defaultValue={JSON.stringify(values[name] ?? null, null, 2)} onBlur={(e) => {
              try {
                set(name, JSON.parse(e.target.value));
              } catch {
                /* keep the previous value; the server validates */
              }
            }} />
            {err && <span className={s.error}>{err.join(", ")}</span>}
          </div>
        );
      })}
    </>
  );
}
