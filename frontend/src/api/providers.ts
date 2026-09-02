import { api } from "./client";
import type { BudgetInfo } from "./devices";

export type ProviderAccountRow = {
  id: string;
  provider: string;
  label: string;
  external_user_id: string | null;
  status: "active" | "reauth_required" | "rate_limited" | "disabled";
  status_reason: string | null;
  status_since: string;
  status_until: string | null;
  budget: BudgetInfo;
  budget_reserve_pct: number;
  budget_overcommitted: boolean;
  devices_count: number;
  recent_errors: { ts: string; kind: string; http_status: number | null; error_type: string | null }[];
  created_at: string;
};

export type DiscoveredDeviceRow = {
  device_id: string;
  model: string | null;
  device_type: string | null;
  online: boolean | null;
  seen_at: string;
  already_added: boolean;
  is_gateway: boolean;
};

export type DiscoveredTree = {
  installations: { installation_id: string; gateways: { gateway_serial: string; devices: DiscoveredDeviceRow[] }[] }[];
  discovered_at: string | null;
};

export const providersApi = {
  list: (tid: string) => api<{ results: ProviderAccountRow[]; count: number }>(`/tenants/${tid}/provider-accounts`),
  authorize: (tid: string, provider: string, label: string) =>
    api<{ redirect_url: string }>(`/tenants/${tid}/provider-accounts/${provider}/authorize`, { method: "POST", body: { label } }),
  discover: (tid: string, accountId: string) =>
    api<{ job_id: string }>(`/tenants/${tid}/provider-accounts/${accountId}/discover`, { method: "POST" }),
  discovered: (tid: string, accountId: string) => api<DiscoveredTree>(`/tenants/${tid}/provider-accounts/${accountId}/discovered`),
  disconnect: (tid: string, accountId: string) => api<void>(`/tenants/${tid}/provider-accounts/${accountId}`, { method: "DELETE" }),
};
