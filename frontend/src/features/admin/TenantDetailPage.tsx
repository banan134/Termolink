import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";
import { ApiError } from "@/api/client";
import { tenantsApi } from "@/api/tenants";
import { PageTitle } from "@/app/AppLayout";
import { Alert, Button, Card, Chip, Skeleton } from "@/components/ui";
import { t } from "@/i18n/pl";
import { ProviderAccountsCard, TenantDevicesCard } from "./ProviderAccountsCard";
import { UsersCard } from "./UsersCard";
import s from "./admin.module.css";

export default function TenantDetailPage() {
  const { id = "" } = useParams();
  const qc = useQueryClient();
  const tenant = useQuery({ queryKey: ["tenant", id], queryFn: () => tenantsApi.get(id) });
  const uploadLogo = useMutation({
    mutationFn: (file: File) => tenantsApi.uploadLogo(id, file),
    onSuccess: (row) => qc.setQueryData(["tenant", id], row),
  });
  const removeLogo = useMutation({
    mutationFn: () => tenantsApi.removeLogo(id),
    onSuccess: (row) => qc.setQueryData(["tenant", id], row),
  });
  const toggleControl = useMutation({
    mutationFn: (control_allowed: boolean) => tenantsApi.patch(id, { control_allowed }),
    onSuccess: (row) => {
      qc.setQueryData(["tenant", id], row);
      qc.invalidateQueries({ queryKey: ["tenants"] });
    },
  });

  if (tenant.isPending) return <Skeleton height={32} />;
  if (tenant.isError || !tenant.data) return <Alert tone="error">{t.errors.notFound}</Alert>;
  const row = tenant.data;

  return (
    <>
      <p className={s.breadcrumb}>
        <Link to="/admin/tenants" className={s.link}>
          {t.nav.tenants}
        </Link>{" "}
        / {row.name}
      </p>
      <PageTitle>{row.name}</PageTitle>
      <div className={s.grid}>
        <Card title={t.admin.tenantSettings}>
          <div className={s.row}>
            <div className={s.rowMain}>
              <span>{t.admin.tenantType}</span>
              <span className={s.muted}>{row.type === "company" ? t.admin.company : t.admin.person}</span>
            </div>
          </div>
          <div className={s.row}>
            <div className={s.rowMain}>
              <span>{t.admin.logo}</span>
              <span className={s.muted}>{t.admin.logoHelp}</span>
              {uploadLogo.error instanceof ApiError && <span className={s.error}>{uploadLogo.error.fields.file?.join(" ") ?? uploadLogo.error.message}</span>}
            </div>
            <span className={s.chips}>
              {row.logo_path ? <Chip tone="ok">{t.admin.logoSet}</Chip> : <Chip tone="neutral">{t.admin.logoNone}</Chip>}
              <label className={s.fileButton}>
                {uploadLogo.isPending ? t.common.loading : t.admin.logoUpload}
                <input type="file" accept="image/png,image/jpeg" hidden onChange={(e) => e.target.files?.[0] && uploadLogo.mutate(e.target.files[0])} />
              </label>
              {row.logo_path && (
                <Button variant="ghost" loading={removeLogo.isPending} onClick={() => removeLogo.mutate()}>
                  {t.common.delete}
                </Button>
              )}
            </span>
          </div>
          <div className={s.row}>
            <div className={s.rowMain}>
              <span>{t.admin.control}</span>
              <span className={s.muted}>{t.admin.controlHelp}</span>
            </div>
            <span className={s.chips}>
              {row.control_allowed ? (
                <Chip tone="ctrl">{t.admin.controlAllowed}</Chip>
              ) : (
                <Chip tone="read">{t.admin.controlBlocked}</Chip>
              )}
              <Button
                variant="secondary"
                loading={toggleControl.isPending}
                onClick={() => toggleControl.mutate(!row.control_allowed)}
              >
                {row.control_allowed ? t.admin.blockControl : t.admin.allowControl}
              </Button>
            </span>
          </div>
          <div className={s.row}>
            <div className={s.rowMain}>
              <span>{t.admin.timezone}</span>
              <span className={s.muted}>{row.timezone}</span>
            </div>
          </div>
        </Card>
        <ProviderAccountsCard tenantId={id} />
        <TenantDevicesCard tenantId={id} />
        <UsersCard tenantId={id} scope="admin" />
      </div>
    </>
  );
}
