import type { FeatureRow } from "@/api/devices";

export const GROUP_LABEL: Record<string, string> = {
  sensors: "Czujniki",
  dhw: "Ciepła woda",
  heat_source: "Źródło ciepła",
  solar: "Solar",
  ventilation: "Wentylacja",
  buffer: "Bufor",
  statistics: "Statystyki",
  messages: "Komunikaty",
  device: "Urządzenie",
  other: "Pozostałe",
};

export function groupLabel(key: string): string {
  if (key.startsWith("circuits.")) return `Obieg ${Number(key.split(".")[1]) + 1}`;
  return GROUP_LABEL[key] ?? key;
}

/** Rows that carry at least one value (docs/09: empty sections are not rendered). */
export function hasValues(row: FeatureRow): boolean {
  return Object.values(row.properties).some((p) => p.value !== null && p.value !== undefined);
}

export function groupRows(rows: FeatureRow[]): { key: string; rows: FeatureRow[] }[] {
  const out: { key: string; rows: FeatureRow[] }[] = [];
  for (const row of rows) {
    const last = out[out.length - 1];
    if (last && last.key === row.group_key) last.rows.push(row);
    else out.push({ key: row.group_key, rows: [row] });
  }
  return out;
}
