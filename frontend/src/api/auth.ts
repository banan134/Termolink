import { api } from "./client";

export type Role = "superadmin" | "technician" | "tenant_admin" | "tenant_user";
export type UiTheme = "light" | "dark";

export type Me = {
  id: string;
  email: string;
  role: Role;
  tenant: { id: string; name: string } | null;
  totp_enabled: boolean;
  allowed_tenants: string[];
  ui_theme: UiTheme;
};

export type SessionRow = {
  id: string;
  ip: string | null;
  user_agent: string;
  created_at: string;
  last_seen_at: string;
  current: boolean;
};

export const authApi = {
  me: () => api<Me>("/auth/me"),
  login: (body: { email: string; password: string; totp?: string }) =>
    api<{ user: Me }>("/auth/login", { method: "POST", body }),
  logout: () => api<void>("/auth/logout", { method: "POST" }),
  patchMe: (body: { ui_theme: UiTheme }) => api<Me>("/auth/me", { method: "PATCH", body }),
  changePassword: (body: { old_password: string; new_password: string }) =>
    api<void>("/auth/password/change", { method: "POST", body }),
  resetRequest: (body: { email: string }) =>
    api<void>("/auth/password/reset-request", { method: "POST", body }),
  reset: (body: { token: string; password: string }) =>
    api<void>("/auth/password/reset", { method: "POST", body }),
  acceptInvitation: (body: { token: string; password: string }) =>
    api<{ user: Me }>("/auth/invitations/accept", { method: "POST", body }),
  reauth: (body: { password: string; totp?: string }) =>
    api<void>("/auth/reauth", { method: "POST", body }),
  totpSetup: () => api<{ secret: string; otpauth_url: string }>("/auth/totp/setup", { method: "POST" }),
  totpEnable: (body: { code: string }) =>
    api<{ backup_codes: string[] }>("/auth/totp/enable", { method: "POST", body }),
  totpDisable: (body: { password: string; code: string }) =>
    api<void>("/auth/totp/disable", { method: "POST", body }),
  sessions: () => api<{ results: SessionRow[] }>("/auth/sessions"),
  revokeSession: (id: string) => api<void>(`/auth/sessions/${id}`, { method: "DELETE" }),
};

export const isOperator = (me: Me | null | undefined) =>
  me?.role === "superadmin" || me?.role === "technician";
