import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";
import { tenantsApi } from "@/api/tenants";
import { PageTitle } from "@/app/AppLayout";
import { Alert, Button, Card, Chip, Skeleton } from "@/components/ui";
import { t } from "@/i18n/pl";
import { UsersCard } from "./UsersCard";
import s from "./admin.module.css";

export default function TenantDetailPage() {
  const { id = "" } = useParams();
  const qc = useQueryClient();
  const tenant = useQuery({ queryKey: ["tenant", id], queryFn: () => tenantsApi.get(id) });
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
        <UsersCard tenantId={id} scope="admin" />
      </div>
    </>
  );
}
