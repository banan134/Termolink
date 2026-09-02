import { useMutation } from "@tanstack/react-query";
import { type FormEvent, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { authApi } from "@/api/auth";
import { ApiError } from "@/api/client";
import { Alert, Button, Field } from "@/components/ui";
import { apiErrorMessage, t } from "@/i18n/pl";
import { AuthShell } from "./AuthShell";
import s from "./AuthShell.module.css";

function RequestForm() {
  const [email, setEmail] = useState("");
  const request = useMutation({ mutationFn: () => authApi.resetRequest({ email }) });
  const submit = (e: FormEvent) => {
    e.preventDefault();
    request.mutate();
  };
  return (
    <AuthShell title={t.reset.title} help={t.reset.help}>
      {request.isSuccess ? (
        <>
          <Alert tone="ok">{t.reset.sent}</Alert>
          <Link className={s.link} to="/login">
            {t.reset.backToLogin}
          </Link>
        </>
      ) : (
        <form onSubmit={submit} noValidate>
          {request.isError && (
            <Alert tone="error">
              {request.error instanceof ApiError
                ? apiErrorMessage(request.error.code, request.error.message)
                : t.common.error}
            </Alert>
          )}
          <Field
            label={t.common.email}
            type="email"
            autoComplete="username"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            required
            autoFocus
          />
          <div className={s.actions}>
            <Link className={s.link} to="/login">
              {t.reset.backToLogin}
            </Link>
            <Button type="submit" loading={request.isPending}>
              {t.reset.submit}
            </Button>
          </div>
        </form>
      )}
    </AuthShell>
  );
}

function NewPasswordForm({ token }: { token: string }) {
  const [password, setPassword] = useState("");
  const [repeat, setRepeat] = useState("");
  const reset = useMutation({ mutationFn: () => authApi.reset({ token, password }) });
  const mismatch = repeat.length > 0 && password !== repeat;
  const fieldErrors = reset.error instanceof ApiError ? reset.error.fields : {};
  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (!mismatch) reset.mutate();
  };
  return (
    <AuthShell title={t.reset.newTitle}>
      {reset.isSuccess ? (
        <>
          <Alert tone="ok">{t.reset.done}</Alert>
          <Link className={s.link} to="/login">
            {t.reset.backToLogin}
          </Link>
        </>
      ) : (
        <form onSubmit={submit} noValidate>
          {reset.isError && (
            <Alert tone="error">
              {reset.error instanceof ApiError
                ? apiErrorMessage(reset.error.code, reset.error.message)
                : t.common.error}
            </Alert>
          )}
          <Field
            label={t.common.newPassword}
            type="password"
            autoComplete="new-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            error={fieldErrors.password}
            required
            autoFocus
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
            <span />
            <Button type="submit" loading={reset.isPending} disabled={mismatch}>
              {t.reset.newSubmit}
            </Button>
          </div>
        </form>
      )}
    </AuthShell>
  );
}

export default function ResetPage() {
  const [params] = useSearchParams();
  const token = params.get("token");
  return token ? <NewPasswordForm token={token} /> : <RequestForm />;
}
