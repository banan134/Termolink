import { api } from "./client";
import type { Role } from "./auth";

export type TenantRow = {
  id: string;
  name: string;
  type: "company" | "person";
  control_allowed: boolean;
  report_header_text: string | null;
  timezone: string;
  created_at: string;
  archived_at: string | null;
  users_count: number;
  devices_count: number;
  online_count: number;
};

export type UserRow = {
  id: string;
  email: string;
  role: Role;
  totp_enabled: boolean;
  is_active: boolean;
  last_login: string | null;
  created_at: string;
};

export type InvitationRow = {
  id: string;
  email: string;
  role: Role;
  expires_at: string;
  created_at: string;
};

export type UsersResponse = { results: UserRow[]; count: number; invitations: InvitationRow[] };

export const tenantsApi = {
  list: () => api<{ results: TenantRow[]; count: number }>("/admin/tenants"),
  create: (body: { name: string; type: "company" | "person" }) =>
    api<TenantRow>("/admin/tenants", { method: "POST", body }),
  get: (id: string) => api<TenantRow>(`/admin/tenants/${id}`),
  patch: (id: string, body: Partial<Pick<TenantRow, "name" | "control_allowed" | "report_header_text">>) =>
    api<TenantRow>(`/admin/tenants/${id}`, { method: "PATCH", body }),
  // operator and tenant_admin share the same shape; the route differs (docs/04)
  users: (tenantId: string, scope: "admin" | "tenant") =>
    api<UsersResponse>(`/${scope === "admin" ? "admin/tenants" : "tenants"}/${tenantId}/users`),
  invite: (tenantId: string, scope: "admin" | "tenant", body: { email: string; role: Role }) =>
    api<InvitationRow>(`/${scope === "admin" ? "admin/tenants" : "tenants"}/${tenantId}/invitations`, {
      method: "POST",
      body,
    }),
};
