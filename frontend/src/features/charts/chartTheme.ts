/** Chart colours and helpers shared by every chart (docs/09 §Wykresy). */

export const SERIES_COLORS = ["#1e3b87", "#3f568c", "#8a5a00", "#1f7a3d", "#7c4dff", "#00838f"];

export function cssVar(name: string, fallback: string): string {
  if (typeof window === "undefined") return fallback;
  const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return value || fallback;
}

export function isDark(): boolean {
  return typeof document !== "undefined" && document.documentElement.getAttribute("data-theme") === "dark";
}

export function unitLabel(unit: string | null | undefined): string {
  if (!unit) return "";
  const map: Record<string, string> = {
    celsius: "°C",
    percent: "%",
    kilowattHour: "kWh",
    "kilowattHour/year": "kWh/rok",
    kilowatt: "kW",
    watt: "W",
    cubicMeter: "m³",
    hour: "h",
    minute: "min",
    liter: "l",
    bar: "bar",
    kelvin: "K",
    meter: "m",
    degree: "°",
  };
  return map[unit] ?? unit;
}

export const RESOLUTION_LABEL: Record<string, string> = {
  raw: "dane surowe",
  "1h": "średnie godzinowe",
  "1d": "średnie dobowe",
};

export function formatTs(ts: string | number | Date, withSeconds = false): string {
  const d = new Date(ts);
  return d.toLocaleString("pl-PL", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    ...(withSeconds ? { second: "2-digit" } : {}),
  });
}

/** File name per docs/09: termolink_<device>_<feature>_<from>_<to>.png, ASCII only. */
export function exportFileName(device: string, feature: string, from: Date, to: Date, ext: string): string {
  const slug = (s: string) =>
    s
      .normalize("NFD")
      .replace(/[̀-ͯ]/g, "")
      .replace(/ł/g, "l")
      .replace(/Ł/g, "L")
      .replace(/[^A-Za-z0-9._-]+/g, "_")
      .replace(/^_+|_+$/g, "");
  const day = (d: Date) => d.toISOString().slice(0, 10);
  return `termolink_${slug(device)}_${slug(feature)}_${day(from)}_${day(to)}.${ext}`;
}

/** Y axis "from a sensible minimum": counters and percentages start at 0, temperatures don't. */
export function axisFromZero(unit: string | null | undefined, feature: string): boolean {
  if (!unit) return false;
  if (["percent", "kilowattHour", "kilowattHour/year", "cubicMeter", "hour", "minute", "liter", "kilowatt", "watt"].includes(unit)) return true;
  return /statistics|consumption|production/.test(feature);
}
