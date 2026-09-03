import type { FeatureRow } from "@/api/devices";

export type ParamSchema = {
  type: string;
  required?: boolean;
  constraints?: { min?: number; max?: number; stepping?: number; enum?: string[]; maxLength?: number; modes?: string[]; maxEntries?: number; resolution?: number; overlapAllowed?: boolean };
};

/** Prefill from the current property values so the user edits, not re-types (docs/09). */
export function defaultParams(schema: Record<string, ParamSchema>, row: FeatureRow): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  const map = Object.values(row.commands).find((c) => c.property_map)?.property_map ?? {};
  for (const [name, def] of Object.entries(schema)) {
    const prop = map[name] ?? (row.properties[name] ? name : Object.keys(row.properties).length === 1 ? Object.keys(row.properties)[0] : null);
    const current = prop ? row.properties[prop]?.value : undefined;
    const kind = def.type.toLowerCase();
    if (kind === "number") out[name] = typeof current === "number" ? current : (def.constraints?.min ?? 0);
    else if (kind === "boolean") out[name] = typeof current === "boolean" ? current : false;
    else if (kind === "string") out[name] = typeof current === "string" ? current : (def.constraints?.enum?.[0] ?? "");
    else if (kind === "schedule") out[name] = current && typeof current === "object" ? current : {};
    else out[name] = current ?? null;
  }
  return out;
}
