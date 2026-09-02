import { api } from "./client";

export type DeviceStatus = "unknown" | "online" | "offline" | "error" | "rate_limited";
export type DeviceMode = "read" | "control";

export type Highlight = { feature: string; property: string; label: string; value: number; unit: string | null };

export type DeviceCard = {
  id: string;
  display_name: string;
  model: string;
  location_text: string | null;
  description: string | null;
  mode: DeviceMode;
  status: DeviceStatus;
  status_since: string;
  status_detail: string | null;
  last_seen_at: string | null;
  last_polled_at: string | null;
  next_poll_at: string;
  highlights: Highlight[];
};

export type BudgetInfo = {
  used: number;
  limit: number;
  reset_at: string;
  poll_used: number;
  poll_budget: number;
  reserve_used: number;
  reserve: number;
};

export type DeviceDetails = DeviceCard & {
  provider: string;
  provider_account_id: string;
  external_ids: Record<string, string>;
  serial: string | null;
  lat: number | null;
  lon: number | null;
  poll_interval_s: number | null;
  effective_interval_s: number;
  commands_per_hour_limit: number;
  budget: BudgetInfo;
  account_status: string;
  capabilities: { can_control: boolean; reasons: string[] };
  created_at: string;
};

export type FeatureProperty = {
  type: string;
  unit: string | null;
  value: unknown;
  ts_device: string | null;
  ts_polled: string | null;
};

export type FeatureRow = {
  feature_name: string;
  label_pl: string | null;
  group_key: string;
  is_enabled: boolean;
  is_ready: boolean;
  properties: Record<string, FeatureProperty>;
  commands: Record<string, { executable: boolean; params: Record<string, unknown> }>;
  unsupported_commands: string[];
  last_seen_at: string;
};

export type HistoryPoint = { ts: string; value?: number; min?: number; avg?: number; max?: number; last?: number; count?: number };
export type HistoryResponse = {
  feature: string;
  property: string;
  unit: string | null;
  resolution: "raw" | "1h" | "1d";
  from: string;
  to: string;
  points: HistoryPoint[];
  stats: { min: number; max: number; avg: number; last: number; count: number } | null;
};

export type StatusHistoryRow = { status: DeviceStatus; since: string; until: string | null; detail: string | null };

export type DeviceCreate = {
  provider_account_id: string;
  external_ids: { installationId: string; gatewaySerial: string; deviceId: string };
  display_name: string;
  description?: string;
  location_text?: string;
  mode?: DeviceMode;
  poll_interval_s?: number | null;
};

export const devicesApi = {
  list: (tid: string) => api<{ results: DeviceCard[]; count: number }>(`/tenants/${tid}/devices`),
  get: (tid: string, id: string) => api<DeviceDetails>(`/tenants/${tid}/devices/${id}`),
  create: (tid: string, body: DeviceCreate) => api<DeviceDetails>(`/tenants/${tid}/devices`, { method: "POST", body }),
  patch: (tid: string, id: string, body: Partial<DeviceCreate> & { commands_per_hour_limit?: number }) =>
    api<DeviceDetails>(`/tenants/${tid}/devices/${id}`, { method: "PATCH", body }),
  archive: (tid: string, id: string) => api<void>(`/tenants/${tid}/devices/${id}`, { method: "DELETE" }),
  refresh: (tid: string, id: string) => api<{ job_id: string }>(`/tenants/${tid}/devices/${id}/refresh`, { method: "POST" }),
  features: (tid: string, id: string) => api<{ results: FeatureRow[]; count: number }>(`/tenants/${tid}/devices/${id}/features`),
  history: (tid: string, id: string, params: { feature: string; property?: string; from?: string; to?: string; resolution?: string }) => {
    const q = new URLSearchParams();
    Object.entries(params).forEach(([k, v]) => v && q.set(k, v));
    return api<HistoryResponse>(`/tenants/${tid}/devices/${id}/history?${q.toString()}`);
  },
  statusHistory: (tid: string, id: string) =>
    api<{ results: StatusHistoryRow[]; count: number }>(`/tenants/${tid}/devices/${id}/status-history`),
  job: (id: string) => api<{ id: string; status: string; result: unknown; error: string | null }>(`/jobs/${id}`),
};
