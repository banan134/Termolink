import { PageTitle } from "@/app/AppLayout";
import { Card, Chip } from "@/components/ui";
import { useMe } from "@/features/auth/useMe";
import { t } from "@/i18n/pl";

export default function HomePage() {
  const me = useMe();
  if (!me.data) return null;
  return (
    <>
      <PageTitle>{t.home.title}</PageTitle>
      <Card>
        <p>
          {t.home.signedInAs} <strong>{me.data.email}</strong>{" "}
          <Chip tone="neutral">{t.roles[me.data.role]}</Chip>
          {me.data.tenant && (
            <>
              {" "}
              · {me.data.tenant.name}
            </>
          )}
        </p>
        <p style={{ color: "var(--text-muted)" }}>{t.home.stage1}</p>
      </Card>
    </>
  );
}
