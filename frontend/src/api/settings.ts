import { api } from "./client";

export type MailSettings = {
  enabled: boolean;
  host: string;
  port: number;
  username: string;
  has_password: boolean;
  use_tls: boolean;
  use_ssl: boolean;
  from_email: string;
  timeout_s: number;
  updated_at: string;
  last_test_at: string | null;
  last_test_ok: boolean | null;
  last_test_error: string;
};

export const settingsApi = {
  mail: () => api<MailSettings>("/admin/settings/mail"),
  saveMail: (body: Partial<MailSettings> & { password?: string }) => {
    const readOnly = new Set(["has_password", "updated_at", "last_test_at", "last_test_ok", "last_test_error"]);
    const rest = Object.fromEntries(Object.entries(body).filter(([k]) => !readOnly.has(k)));
    return api<MailSettings>("/admin/settings/mail", { method: "PUT", body: rest });
  },
  testMail: (to: string) => api<MailSettings & { ok: boolean; error: string }>("/admin/settings/mail/test", { method: "POST", body: { to } }),
};
