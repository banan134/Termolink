import { api } from "./client";

export type AlertType = "device_offline" | "value_out_of_range" | "device_message" | "provider_account" | "verify_mismatch" | "worker_down";
export type Severity = "info" | "warning" | "critical";

export type AlertRow = {
  id: string;
  tenant_id: string | null;
  tenant_name?: string | null;
  device_id: string | null;
  device_name: string | null;
  rule_id: string | null;
  type: AlertType;
  severity: Severity;
  message: string;
  details: Record<string, unknown>;
  opened_at: string;
  closed_at: string | null;
  acknowledged_at: string | null;
  acknowledged_by: string | null;
  notified_at: string | null;
};

export type RuleConfig = { minutes?: number; email?: boolean; feature?: string; property?: string; min?: number | null; max?: number | null };

export type AlertRule = {
  id: string;
  device_id: string | null;
  device_name: string | null;
  type: "device_offline" | "value_out_of_range" | "device_message";
  config: RuleConfig;
  enabled: boolean;
  created_at: string;
};

export const alertsApi = {
  list: (tid: string, q: { open?: boolean; device?: string; page?: number; page_size?: number } = {}) => {
    const qs = new URLSearchParams();
    if (q.open) qs.set("open", "1");
    if (q.device) qs.set("device", q.device);
    if (q.page) qs.set("page", String(q.page));
    if (q.page_size) qs.set("page_size", String(q.page_size));
    const suffix = qs.toString() ? `?${qs}` : "";
    return api<{ results: AlertRow[]; count: number; open_count: number }>(`/tenants/${tid}/alerts${suffix}`);
  },
  acknowledge: (tid: string, id: string) => api<AlertRow>(`/tenants/${tid}/alerts/${id}`, { method: "PATCH", body: { acknowledged: true } }),
  rules: (tid: string) => api<{ results: AlertRule[] }>(`/tenants/${tid}/alert-rules`),
  createRule: (tid: string, body: { type: AlertRule["type"]; device_id?: string | null; config: RuleConfig; enabled?: boolean }) =>
    api<AlertRule>(`/tenants/${tid}/alert-rules`, { method: "POST", body }),
  updateRule: (tid: string, id: string, body: Partial<{ config: RuleConfig; enabled: boolean }>) =>
    api<AlertRule>(`/tenants/${tid}/alert-rules/${id}`, { method: "PATCH", body }),
  deleteRule: (tid: string, id: string) => api<void>(`/tenants/${tid}/alert-rules/${id}`, { method: "DELETE" }),
  adminOpen: () => api<{ results: AlertRow[]; count: number }>(`/admin/alerts`),
};
