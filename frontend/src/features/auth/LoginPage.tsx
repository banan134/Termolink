import { useMutation, useQueryClient } from "@tanstack/react-query";
import { type FormEvent, useState } from "react";
import { Link, Navigate, useLocation, useNavigate } from "react-router-dom";
import { authApi } from "@/api/auth";
import { ApiError } from "@/api/client";
import { Alert, Button, Field } from "@/components/ui";
import { apiErrorMessage, t } from "@/i18n/pl";
import { AuthShell } from "./AuthShell";
import s from "./AuthShell.module.css";
import { ME_KEY, useMe } from "./useMe";

export default function LoginPage() {
  const me = useMe();
  const qc = useQueryClient();
  const navigate = useNavigate();
  const location = useLocation();
  const from = (location.state as { from?: string } | null)?.from ?? "/";

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [totp, setTotp] = useState("");
  const [step, setStep] = useState<"credentials" | "totp">("credentials");
  const [error, setError] = useState<string | null>(null);

  const login = useMutation({
    mutationFn: () => authApi.login({ email, password, totp: totp || undefined }),
    onSuccess: ({ user }) => {
      qc.setQueryData(ME_KEY, user);
      navigate(from, { replace: true });
    },
    onError: (err: unknown) => {
      if (!(err instanceof ApiError)) return setError(t.common.error);
      if (err.status === 428 && err.code === "totp_required") {
        setStep("totp");
        setError(null);
        return;
      }
      if (err.code === "login_locked" && err.retryAfterS) return setError(t.login.locked(err.retryAfterS));
      if (err.code === "invalid_totp") {
        setTotp("");
        return setError(t.login.invalidTotp);
      }
      if (err.code === "invalid_credentials") {
        setStep("credentials");
        setTotp("");
      }
      setError(apiErrorMessage(err.code, err.message || t.common.error));
    },
  });

  if (me.data) return <Navigate to="/" replace />;

  const submit = (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    login.mutate();
  };

  return (
    <AuthShell
      title={step === "totp" ? t.login.totpTitle : t.login.title}
      help={step === "totp" ? t.login.totpHelp : undefined}
    >
      <form onSubmit={submit} noValidate>
        {error && <Alert tone="error">{error}</Alert>}
        {step === "credentials" ? (
          <>
            <Field
              label={t.common.email}
              type="email"
              autoComplete="username"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
              autoFocus
            />
            <Field
              label={t.common.password}
              type="password"
              autoComplete="current-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
            />
          </>
        ) : (
          <Field
            label={t.common.totpCode}
            inputMode="numeric"
            autoComplete="one-time-code"
            value={totp}
            onChange={(e) => setTotp(e.target.value)}
            required
            autoFocus
          />
        )}
        <div className={s.actions}>
          {step === "credentials" ? (
            <Link className={s.link} to="/reset">
              {t.login.forgot}
            </Link>
          ) : (
            <Button type="button" variant="ghost" onClick={() => setStep("credentials")}>
              {t.common.cancel}
            </Button>
          )}
          <Button type="submit" loading={login.isPending}>
            {t.login.submit}
          </Button>
        </div>
      </form>
    </AuthShell>
  );
}
