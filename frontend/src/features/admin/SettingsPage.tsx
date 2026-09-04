import { useEffect, useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ApiError } from "@/api/client";
import { settingsApi, type MailSettings } from "@/api/settings";
import { PageTitle } from "@/app/AppLayout";
import { Alert, Button, Card, Chip, Field, Skeleton } from "@/components/ui";
import { formatDateTime } from "@/features/devices/format";
import { t } from "@/i18n/pl";
import s from "./admin.module.css";

/** /admin/settings — serwer pocztowy (superadmin). Hasło nigdy nie wraca z API. */
export default function SettingsPage() {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["settings", "mail"], queryFn: settingsApi.mail });
  const [form, setForm] = useState<Partial<MailSettings> & { password?: string }>({});
  const [testTo, setTestTo] = useState("");
  useEffect(() => {
    if (q.data) setForm({ ...q.data });
  }, [q.data]);
  const save = useMutation({
    mutationFn: () => settingsApi.saveMail(form),
    onSuccess: (row) => {
      qc.setQueryData(["settings", "mail"], row);
      setForm({ ...row });
    },
  });
  const test = useMutation({ mutationFn: () => settingsApi.testMail(testTo), onSuccess: (row) => qc.setQueryData(["settings", "mail"], row) });
  const err = save.error instanceof ApiError ? save.error : null;
  if (q.isPending) return <Skeleton height={120} />;
  if (q.isError) return <Alert tone="error">{t.errors.forbidden}</Alert>;
  const set = <K extends keyof typeof form>(k: K, v: (typeof form)[K]) => setForm({ ...form, [k]: v });

  return (
    <>
      <PageTitle>{t.settings.title}</PageTitle>
      <div className={s.grid}>
        <Card title={t.settings.mail}>
          <p className={s.muted}>{t.settings.mailHelp}</p>
          <form
            noValidate
            onSubmit={(e: FormEvent) => {
              e.preventDefault();
              save.mutate();
            }}
          >
            {err && !Object.keys(err.fields).length && <Alert tone="error">{err.message}</Alert>}
            <label className={s.toggle}>
              <input type="checkbox" checked={!!form.enabled} onChange={(e) => set("enabled", e.target.checked)} /> {t.settings.enabled}
            </label>
            <Field label={t.settings.host} value={form.host ?? ""} onChange={(e) => set("host", e.target.value)} placeholder="smtp.example.com" error={err?.fields.host} />
            <div className={s.twoCols}>
              <Field label={t.settings.port} type="number" min={1} max={65535} value={form.port ?? 587} onChange={(e) => set("port", Number(e.target.value))} error={err?.fields.port} />
              <Field label={t.settings.timeout} type="number" min={3} max={120} value={form.timeout_s ?? 15} onChange={(e) => set("timeout_s", Number(e.target.value))} />
            </div>
            <Field label={t.settings.username} value={form.username ?? ""} onChange={(e) => set("username", e.target.value)} autoComplete="off" />
            <Field label={t.settings.password} type="password" value={form.password ?? ""} onChange={(e) => set("password", e.target.value)} autoComplete="new-password" help={q.data?.has_password ? t.settings.passwordStored : t.settings.passwordHelp} />
            <div className={s.twoCols}>
              <label className={s.toggle}>
                <input type="radio" checked={!!form.use_tls && !form.use_ssl} onChange={() => setForm({ ...form, use_tls: true, use_ssl: false })} /> STARTTLS (587)
              </label>
              <label className={s.toggle}>
                <input type="radio" checked={!!form.use_ssl} onChange={() => setForm({ ...form, use_tls: false, use_ssl: true })} /> SSL (465)
              </label>
              <label className={s.toggle}>
                <input type="radio" checked={!form.use_tls && !form.use_ssl} onChange={() => setForm({ ...form, use_tls: false, use_ssl: false })} /> {t.settings.plain}
              </label>
            </div>
            <Field label={t.settings.from} value={form.from_email ?? ""} onChange={(e) => set("from_email", e.target.value)} placeholder="Termolink <termolink@wodmiar.pl>" error={err?.fields.from_email} />
            <div className={s.actions}>
              {save.isSuccess && <Chip tone="ok">{t.common.saved}</Chip>}
              <Button type="submit" loading={save.isPending}>
                {t.common.save}
              </Button>
            </div>
          </form>
        </Card>

        <Card title={t.settings.test}>
          <p className={s.muted}>{t.settings.testHelp}</p>
          <Field label={t.settings.testTo} type="email" value={testTo} onChange={(e) => setTestTo(e.target.value)} />
          <div className={s.actions}>
            <Button variant="secondary" loading={test.isPending} disabled={!testTo} onClick={() => test.mutate()}>
              {t.settings.sendTest}
            </Button>
          </div>
          {q.data?.last_test_at && (
            <div className={s.muted} style={{ marginTop: "var(--sp-2)" }}>
              {t.settings.lastTest}: {formatDateTime(q.data.last_test_at)} ·{" "}
              {q.data.last_test_ok ? <Chip tone="ok">{t.settings.testOk}</Chip> : <Chip tone="off">{t.settings.testFailed}</Chip>}
              {q.data.last_test_error && <div className={s.error}>{q.data.last_test_error}</div>}
            </div>
          )}
        </Card>
      </div>
    </>
  );
}
