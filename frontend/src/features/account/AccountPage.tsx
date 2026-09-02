import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import QRCode from "qrcode";
import { type FormEvent, useEffect, useState } from "react";
import { authApi, isOperator, type Me } from "@/api/auth";
import { ApiError } from "@/api/client";
import { PageTitle } from "@/app/AppLayout";
import { Alert, Button, Card, Chip, Field, Mono, Skeleton } from "@/components/ui";
import { ME_KEY, useMe, useSetTheme } from "@/features/auth/useMe";
import { apiErrorMessage, t } from "@/i18n/pl";
import s from "./AccountPage.module.css";

function errorText(err: unknown): string {
  return err instanceof ApiError ? apiErrorMessage(err.code, err.message) : t.common.error;
}

// ---------- profile / theme ----------
function ProfileCard({ me }: { me: Me }) {
  const setTheme = useSetTheme();
  return (
    <Card title={t.account.profile}>
      <div className={s.row}>
        <div className={s.rowMain}>
          <strong>{me.email}</strong>
          <span className={s.muted}>
            {t.roles[me.role]}
            {me.tenant ? ` · ${me.tenant.name}` : ""}
          </span>
        </div>
      </div>
      <div className={s.row}>
        <span>{t.account.theme}</span>
        <div className={s.themeRow}>
          <Button
            variant={me.ui_theme === "light" ? "primary" : "secondary"}
            onClick={() => setTheme.mutate("light")}
          >
            {t.nav.themeLight}
          </Button>
          <Button
            variant={me.ui_theme === "dark" ? "primary" : "secondary"}
            onClick={() => setTheme.mutate("dark")}
          >
            {t.nav.themeDark}
          </Button>
        </div>
      </div>
    </Card>
  );
}

// ---------- password ----------
function PasswordCard() {
  const [old, setOld] = useState("");
  const [next, setNext] = useState("");
  const [repeat, setRepeat] = useState("");
  const change = useMutation({
    mutationFn: () => authApi.changePassword({ old_password: old, new_password: next }),
    onSuccess: () => {
      setOld("");
      setNext("");
      setRepeat("");
    },
  });
  const mismatch = repeat.length > 0 && next !== repeat;
  const fields = change.error instanceof ApiError ? change.error.fields : {};
  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (!mismatch) change.mutate();
  };
  return (
    <Card title={t.account.passwordTitle}>
      <form onSubmit={submit} noValidate>
        {change.isSuccess && <Alert tone="ok">{t.account.passwordChanged}</Alert>}
        {change.isError && !fields.old_password && !fields.new_password && (
          <Alert tone="error">{errorText(change.error)}</Alert>
        )}
        <Field
          label={t.account.oldPassword}
          type="password"
          autoComplete="current-password"
          value={old}
          onChange={(e) => setOld(e.target.value)}
          error={fields.old_password}
          required
        />
        <Field
          label={t.common.newPassword}
          type="password"
          autoComplete="new-password"
          value={next}
          onChange={(e) => setNext(e.target.value)}
          error={fields.new_password}
          required
        />
        <Field
          label={t.common.repeatPassword}
          type="password"
          autoComplete="new-password"
          value={repeat}
          onChange={(e) => setRepeat(e.target.value)}
          error={mismatch ? t.common.passwordsDiffer : undefined}
          required
        />
        <div className={s.actions}>
          <Button type="submit" loading={change.isPending} disabled={mismatch}>
            {t.common.save}
          </Button>
        </div>
      </form>
    </Card>
  );
}

// ---------- 2FA ----------
function TwoFactorCard({ me }: { me: Me }) {
  const qc = useQueryClient();
  const [setup, setSetup] = useState<{ secret: string; otpauth_url: string } | null>(null);
  const [qr, setQr] = useState<string>("");
  const [code, setCode] = useState("");
  const [backupCodes, setBackupCodes] = useState<string[] | null>(null);
  const [disabling, setDisabling] = useState(false);
  const [password, setPassword] = useState("");

  const start = useMutation({
    mutationFn: () => authApi.totpSetup(),
    onSuccess: (data) => {
      setSetup(data);
      setCode("");
    },
  });
  const enable = useMutation({
    mutationFn: () => authApi.totpEnable({ code }),
    onSuccess: ({ backup_codes }) => {
      setBackupCodes(backup_codes);
      setSetup(null);
      qc.setQueryData(ME_KEY, { ...me, totp_enabled: true });
    },
  });
  const disable = useMutation({
    mutationFn: () => authApi.totpDisable({ password, code }),
    onSuccess: () => {
      setDisabling(false);
      setPassword("");
      setCode("");
      qc.setQueryData(ME_KEY, { ...me, totp_enabled: false });
    },
  });

  useEffect(() => {
    if (!setup) return setQr("");
    QRCode.toDataURL(setup.otpauth_url, { margin: 1, width: 360 })
      .then(setQr)
      .catch(() => setQr(""));
  }, [setup]);

  const operatorPending = isOperator(me) && !me.totp_enabled;

  return (
    <Card title={t.account.twoFactor} id="2fa">
      {operatorPending && <Alert tone="warn">{t.account.twoFactorRequired}</Alert>}
      <div className={s.row}>
        <span>
          {me.totp_enabled ? (
            <Chip tone="ok">{t.account.twoFactorOn}</Chip>
          ) : (
            <Chip tone="off">{t.account.twoFactorOff}</Chip>
          )}
        </span>
        {!me.totp_enabled && !setup && (
          <Button onClick={() => start.mutate()} loading={start.isPending}>
            {t.account.enable2fa}
          </Button>
        )}
        {me.totp_enabled && !isOperator(me) && !disabling && (
          <Button variant="secondary" onClick={() => setDisabling(true)}>
            {t.account.disable2fa}
          </Button>
        )}
      </div>

      {start.isError && <Alert tone="error">{errorText(start.error)}</Alert>}

      {setup && (
        <form
          onSubmit={(e) => {
            e.preventDefault();
            enable.mutate();
          }}
          noValidate
        >
          <p className={s.muted} style={{ whiteSpace: "normal" }}>
            {t.account.setupHelp}
          </p>
          {qr && <img className={s.qr} src={qr} alt="Kod QR do aplikacji uwierzytelniającej" />}
          <p>
            {t.account.secret}: <Mono>{setup.secret}</Mono>
          </p>
          {enable.isError && !(enable.error instanceof ApiError && enable.error.fields.code) && (
            <Alert tone="error">{errorText(enable.error)}</Alert>
          )}
          <Field
            label={t.account.confirmCode}
            inputMode="numeric"
            autoComplete="one-time-code"
            value={code}
            onChange={(e) => setCode(e.target.value)}
            error={enable.error instanceof ApiError ? enable.error.fields.code : undefined}
            required
            autoFocus
          />
          <div className={s.actions}>
            <Button type="button" variant="ghost" onClick={() => setSetup(null)}>
              {t.common.cancel}
            </Button>
            <Button type="submit" loading={enable.isPending}>
              {t.account.enable2fa}
            </Button>
          </div>
        </form>
      )}

      {backupCodes && (
        <div>
          <h3 style={{ margin: "var(--sp-4) 0 var(--sp-1)" }}>{t.account.backupCodesTitle}</h3>
          <p className={s.muted} style={{ whiteSpace: "normal" }}>
            {t.account.backupCodesHelp}
          </p>
          <ul className={s.codes}>
            {backupCodes.map((c) => (
              <li key={c}>{c}</li>
            ))}
          </ul>
          <div className={s.actions}>
            <Button variant="secondary" onClick={() => setBackupCodes(null)}>
              {t.common.close}
            </Button>
          </div>
        </div>
      )}

      {disabling && (
        <form
          onSubmit={(e) => {
            e.preventDefault();
            disable.mutate();
          }}
          noValidate
        >
          <p className={s.muted} style={{ whiteSpace: "normal" }}>
            {t.account.disableHelp}
          </p>
          {disable.isError && <Alert tone="error">{errorText(disable.error)}</Alert>}
          <Field
            label={t.common.password}
            type="password"
            autoComplete="current-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
          />
          <Field
            label={t.common.totpCode}
            inputMode="numeric"
            autoComplete="one-time-code"
            value={code}
            onChange={(e) => setCode(e.target.value)}
            required
          />
          <div className={s.actions}>
            <Button type="button" variant="ghost" onClick={() => setDisabling(false)}>
              {t.common.cancel}
            </Button>
            <Button type="submit" variant="danger" loading={disable.isPending}>
              {t.account.disable2fa}
            </Button>
          </div>
        </form>
      )}
    </Card>
  );
}

// ---------- sessions ----------
function formatDate(iso: string) {
  return new Date(iso).toLocaleString("pl-PL", { dateStyle: "short", timeStyle: "short" });
}

function SessionsCard() {
  const qc = useQueryClient();
  const sessions = useQuery({ queryKey: ["sessions"], queryFn: () => authApi.sessions() });
  const revoke = useMutation({
    mutationFn: (id: string) => authApi.revokeSession(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["sessions"] }),
  });
  return (
    <Card title={t.account.sessions}>
      {sessions.isPending && <Skeleton height={40} />}
      {sessions.isError && <Alert tone="error">{errorText(sessions.error)}</Alert>}
      {sessions.data?.results.map((row) => (
        <div className={s.row} key={row.id}>
          <div className={s.rowMain}>
            <span>
              {row.ip ?? "—"} {row.current && <Chip tone="neutral">{t.account.thisSession}</Chip>}
            </span>
            <span className={s.muted} title={row.user_agent}>
              {t.account.created} {formatDate(row.created_at)} · {t.account.lastSeen}{" "}
              {formatDate(row.last_seen_at)} · {row.user_agent}
            </span>
          </div>
          {!row.current && (
            <Button
              variant="secondary"
              onClick={() => revoke.mutate(row.id)}
              loading={revoke.isPending && revoke.variables === row.id}
            >
              {t.account.revoke}
            </Button>
          )}
        </div>
      ))}
    </Card>
  );
}

export default function AccountPage() {
  const me = useMe();
  if (!me.data) return null;
  return (
    <>
      <PageTitle>{t.account.title}</PageTitle>
      <div className={s.grid}>
        <ProfileCard me={me.data} />
        <TwoFactorCard me={me.data} />
        <PasswordCard />
        <SessionsCard />
      </div>
    </>
  );
}
