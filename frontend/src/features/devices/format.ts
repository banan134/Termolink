import { t } from "@/i18n/pl";

export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleString("pl-PL", { dateStyle: "short", timeStyle: "short" });
}

export function unitLabel(unit: string): string {
  const map: Record<string, string> = {
    celsius: "°C",
    percent: "%",
    kilowattHour: "kWh",
    kilowatt: "kW",
    watt: "W",
    cubicMeter: "m³",
    hour: "h",
    liter: "l",
    bar: "bar",
    kelvin: "K",
    minute: "min",
  };
  return map[unit] ?? unit;
}

export function formatValue(value: unknown, unit: string | null): string {
  if (value === null || value === undefined) return "—";
  if (typeof value === "number") {
    const text = Number.isInteger(value) ? String(value) : value.toFixed(1);
    return unit ? `${text} ${unitLabel(unit)}` : text;
  }
  if (typeof value === "boolean") return value ? t.common.yes : t.common.no;
  if (typeof value === "string") return value;
  return JSON.stringify(value);
}
