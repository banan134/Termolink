import { api } from "./client";

export type CommandStatus =
  | "draft"
  | "confirmed"
  | "executing"
  | "succeeded"
  | "failed"
  | "verify_pending"
  | "verified"
  | "verify_mismatch"
  | "rejected"
  | "expired";

export type Command = {
  id: string;
  device_id: string;
  device_name?: string;
  feature_name: string;
  command_name: string;
  params: Record<string, unknown>;
  value_before: Record<string, unknown> | null;
  value_after: Record<string, unknown> | null;
  status: CommandStatus;
  sensitive: boolean;
  reject_reason: string | null;
  api_status: number | null;
  user_email: string | null;
  acted_as_operator: boolean;
  created_at: string;
  expires_at: string;
  confirmed_at: string | null;
  executed_at: string | null;
  verified_at: string | null;
  job?: { kind: string; status: string; error: string | null } | null;
};

export const TERMINAL: CommandStatus[] = ["failed", "verified", "verify_mismatch", "rejected", "expired"];

export const controlApi = {
  createDraft: (tid: string, deviceId: string, body: { feature_name: string; command_name: string; params: Record<string, unknown> }) =>
    api<Command>(`/tenants/${tid}/devices/${deviceId}/commands`, { method: "POST", body }),
  confirm: (tid: string, commandId: string) => api<Command>(`/tenants/${tid}/commands/${commandId}/confirm`, { method: "POST", body: { acknowledged: true } }),
  get: (tid: string, commandId: string) => api<Command>(`/tenants/${tid}/commands/${commandId}`),
  list: (tid: string, q: { device?: string; status?: string; page?: number; page_size?: number } = {}) => {
    const qs = new URLSearchParams();
    Object.entries(q).forEach(([k, v]) => v !== undefined && v !== "" && qs.set(k, String(v)));
    const suffix = qs.toString() ? `?${qs}` : "";
    return api<{ results: Command[]; count: number }>(`/tenants/${tid}/commands${suffix}`);
  },
};
