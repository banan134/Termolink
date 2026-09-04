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
  if (typeof value === "string") return enumLabel(value);
  return JSON.stringify(value);
}

/** Polish names for the technical property keys of the Viessmann feature model (docs/05). */
const PROPERTY_LABELS: Record<string, string> = {
  value: "wartość",
  active: "aktywny",
  status: "stan",
  temperature: "temperatura",
  targetTemperature: "temperatura zadana",
  entries: "wpisy harmonogramu",
  demand: "zapotrzebowanie",
  name: "nazwa",
  shift: "przesunięcie",
  slope: "nachylenie",
  min: "minimum",
  max: "maksimum",
  enabled: "włączone",
  hours: "godziny pracy",
  starts: "liczba startów",
  day: "dzień",
  week: "tydzień",
  month: "miesiąc",
  year: "rok",
  currentDay: "bieżący dzień",
  lastSevenDays: "ostatnie 7 dni",
  currentMonth: "bieżący miesiąc",
  lastMonth: "poprzedni miesiąc",
  currentYear: "bieżący rok",
  lastYear: "poprzedni rok",
  startHour: "godzina startu",
  startMinute: "minuta startu",
  type: "typ",
  serial: "numer seryjny",
  modulation: "modulacja",
  phase: "faza",
  reason: "powód",
  overlapAllowed: "nakładanie dozwolone",
  maxEntries: "maks. wpisów",
  resolution: "rozdzielczość",
  defaultMode: "tryb domyślny",
  modes: "tryby",
  unit: "jednostka",
  time: "czas",
  date: "data",
};

export function propertyLabel(prop: string): string {
  return PROPERTY_LABELS[prop] ?? prop.replace(/([a-z])([A-Z])/g, "$1 $2").toLowerCase();
}

/** Polish labels for enum-like string values coming from the API. */
const ENUM_LABELS: Record<string, string> = {
  on: "włączone",
  off: "wyłączone",
  true: "tak",
  false: "nie",
  standby: "czuwanie",
  heating: "grzanie",
  cooling: "chłodzenie",
  dhw: "ciepła woda",
  dhwAndHeating: "c.w.u. + grzanie",
  normal: "normalny",
  reduced: "obniżony",
  comfort: "komfort",
  eco: "eko",
  fixed: "stały",
  forcedLastFromSchedule: "ostatni z harmonogramu",
  balanced: "zrównoważony",
  efficient: "oszczędny",
  temp2: "temp. 2",
  connected: "połączone",
  disconnected: "rozłączone",
  online: "online",
  offline: "offline",
  unknown: "nieznane",
  notConnected: "niepodłączone",
  error: "błąd",
  warning: "ostrzeżenie",
  ready: "gotowe",
  notReady: "niegotowe",
  active: "aktywny",
  inactive: "nieaktywny",
  enabled: "włączone",
  disabled: "wyłączone",
  manual: "ręczny",
  automatic: "automatyczny",
  summer: "lato",
  winter: "zima",
  none: "brak",
  nothing: "nic",
  hot: "gorący",
  cold: "zimny",
  charging: "ładowanie",
  idle: "bezczynny",
};

export function enumLabel(value: string): string {
  return ENUM_LABELS[value] ?? value;
}
