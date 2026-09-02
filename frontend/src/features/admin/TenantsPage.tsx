import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { type FormEvent, useState } from "react";
import { Link } from "react-router-dom";
import { tenantsApi } from "@/api/tenants";
import { ApiError } from "@/api/client";
import { PageTitle } from "@/app/AppLayout";
import { Alert, Button, Card, Chip, EmptyState, Field, Skeleton } from "@/components/ui";
import { useMe } from "@/features/auth/useMe";
import { t } from "@/i18n/pl";
import s from "./admin.module.css";

export default function TenantsPage() {
  const me = useMe();
  const qc = useQueryClient();
  const tenants = useQuery({ queryKey: ["tenants"], queryFn: tenantsApi.list });
  const [name, setName] = useState("");
  const [type, setType] = useState<"company" | "person">("company");
  const create = useMutation({
    mutationFn: () => tenantsApi.create({ name, type }),
    onSuccess: () => {
      setName("");
      qc.invalidateQueries({ queryKey: ["tenants"] });
    },
  });
  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (name.trim()) create.mutate();
  };

  return (
    <>
      <PageTitle>{t.nav.tenants}</PageTitle>
      <div className={s.grid}>
        <Card>
          {tenants.isPending && <Skeleton height={48} />}
          {tenants.isError && <Alert tone="error">{t.common.error}</Alert>}
          {tenants.data?.count === 0 && <EmptyState title={t.admin.noTenants} />}
          {tenants.data?.results.map((row) => (
            <div className={s.row} key={row.id}>
              <div className={s.rowMain}>
                <Link to={`/admin/tenants/${row.id}`} className={s.link}>
                  {row.name}
                </Link>
                <span className={s.muted}>
                  {row.type === "company" ? t.admin.company : t.admin.person} · {t.admin.usersCount(row.users_count)}
                </span>
              </div>
              {row.control_allowed ? (
                <Chip tone="ctrl">{t.admin.controlAllowed}</Chip>
              ) : (
                <Chip tone="read">{t.admin.controlBlocked}</Chip>
              )}
            </div>
          ))}
        </Card>
        {me.data?.role === "superadmin" && (
          <Card title={t.admin.newTenant}>
            <form onSubmit={submit} noValidate>
              {create.isError && (
                <Alert tone="error">
                  {create.error instanceof ApiError ? create.error.message : t.common.error}
                </Alert>
              )}
              <Field
                label={t.admin.tenantName}
                value={name}
                onChange={(e) => setName(e.target.value)}
                required
              />
              <div className={s.radioRow} role="radiogroup" aria-label={t.admin.tenantType}>
                <label>
                  <input type="radio" checked={type === "company"} onChange={() => setType("company")} />{" "}
                  {t.admin.company}
                </label>
                <label>
                  <input type="radio" checked={type === "person"} onChange={() => setType("person")} />{" "}
                  {t.admin.person}
                </label>
              </div>
              <div className={s.actions}>
                <Button type="submit" loading={create.isPending} disabled={!name.trim()}>
                  {t.admin.create}
                </Button>
              </div>
            </form>
          </Card>
        )}
      </div>
    </>
  );
}
