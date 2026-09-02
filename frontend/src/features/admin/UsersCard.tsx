import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { type FormEvent, useState } from "react";
import type { Role } from "@/api/auth";
import { ApiError } from "@/api/client";
import { tenantsApi } from "@/api/tenants";
import { Alert, Button, Card, Chip, Field, Skeleton } from "@/components/ui";
import { t } from "@/i18n/pl";
import s from "./admin.module.css";

function formatDate(iso: string | null) {
  return iso ? new Date(iso).toLocaleString("pl-PL", { dateStyle: "short", timeStyle: "short" }) : "—";
}

/** Users + pending invitations of one tenant; used by operators (/admin) and tenant admins. */
export function UsersCard({ tenantId, scope }: { tenantId: string; scope: "admin" | "tenant" }) {
  const qc = useQueryClient();
  const key = ["tenant-users", scope, tenantId];
  const users = useQuery({ queryKey: key, queryFn: () => tenantsApi.users(tenantId, scope) });
  const [email, setEmail] = useState("");
  const [role, setRole] = useState<Role>("tenant_user");
  const invite = useMutation({
    mutationFn: () => tenantsApi.invite(tenantId, scope, { email, role }),
    onSuccess: () => {
      setEmail("");
      qc.invalidateQueries({ queryKey: key });
    },
  });
  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (email.trim()) invite.mutate();
  };
  const fields = invite.error instanceof ApiError ? invite.error.fields : {};

  return (
    <Card title={t.admin.users}>
      {users.isPending && <Skeleton height={48} />}
      {users.isError && <Alert tone="error">{t.common.error}</Alert>}
      {users.data?.results.map((u) => (
        <div className={s.row} key={u.id}>
          <div className={s.rowMain}>
            <span>{u.email}</span>
            <span className={s.muted}>
              {t.roles[u.role]} · {t.admin.lastLogin} {formatDate(u.last_login)}
            </span>
          </div>
          <span className={s.chips}>
            {u.totp_enabled && <Chip tone="ok">2FA</Chip>}
            {!u.is_active && <Chip tone="off">{t.admin.inactive}</Chip>}
          </span>
        </div>
      ))}
      {users.data?.invitations.map((i) => (
        <div className={s.row} key={i.id}>
          <div className={s.rowMain}>
            <span>{i.email}</span>
            <span className={s.muted}>
              {t.roles[i.role]} · {t.admin.invitationExpires} {formatDate(i.expires_at)}
            </span>
          </div>
          <Chip tone="neutral">{t.admin.invited}</Chip>
        </div>
      ))}

      <form onSubmit={submit} noValidate className={s.inviteForm}>
        <h3 className={s.subTitle}>{t.admin.invite}</h3>
        {invite.isSuccess && <Alert tone="ok">{t.admin.invitationSent}</Alert>}
        {invite.isError && !fields.email && (
          <Alert tone="error">
            {invite.error instanceof ApiError
              ? invite.error.code === "email_taken"
                ? t.admin.emailTaken
                : invite.error.message
              : t.common.error}
          </Alert>
        )}
        <Field
          label={t.common.email}
          type="email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          error={fields.email}
          required
        />
        <div className={s.radioRow} role="radiogroup" aria-label={t.admin.role}>
          <label>
            <input type="radio" checked={role === "tenant_user"} onChange={() => setRole("tenant_user")} />{" "}
            {t.roles.tenant_user}
          </label>
          <label>
            <input type="radio" checked={role === "tenant_admin"} onChange={() => setRole("tenant_admin")} />{" "}
            {t.roles.tenant_admin}
          </label>
        </div>
        <div className={s.actions}>
          <Button type="submit" loading={invite.isPending} disabled={!email.trim()}>
            {t.admin.sendInvitation}
          </Button>
        </div>
      </form>
    </Card>
  );
}
