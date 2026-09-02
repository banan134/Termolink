import { Navigate, useParams } from "react-router-dom";
import { PageTitle } from "@/app/AppLayout";
import { useMe } from "@/features/auth/useMe";
import { t } from "@/i18n/pl";
import { UsersCard } from "./UsersCard";

/** /t/:tid/users — tenant_admin manages the customer's users (docs/09, docs/14 B7). */
export default function TenantUsersPage() {
  const { tid = "" } = useParams();
  const me = useMe();
  if (!me.data) return null;
  if (me.data.role !== "tenant_admin" || me.data.tenant?.id !== tid) {
    return <Navigate to="/" replace />;
  }
  return (
    <>
      <PageTitle>{t.nav.users}</PageTitle>
      <UsersCard tenantId={tid} scope="tenant" />
    </>
  );
}
