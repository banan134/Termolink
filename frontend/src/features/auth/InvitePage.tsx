import { useMutation, useQueryClient } from "@tanstack/react-query";
import { type FormEvent, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { authApi } from "@/api/auth";
import { ApiError } from "@/api/client";
import { Alert, Button, Field } from "@/components/ui";
import { apiErrorMessage, t } from "@/i18n/pl";
import { AuthShell } from "./AuthShell";
import s from "./AuthShell.module.css";
import { ME_KEY } from "./useMe";

export default function InvitePage() {
  const { token = "" } = useParams();
  const qc = useQueryClient();
  const navigate = useNavigate();
  const [password, setPassword] = useState("");
  const [repeat, setRepeat] = useState("");
  const accept = useMutation({
    mutationFn: () => authApi.acceptInvitation({ token, password }),
    onSuccess: ({ user }) => {
      qc.setQueryData(ME_KEY, user);
      navigate("/", { replace: true });
    },
  });
  const mismatch = repeat.length > 0 && password !== repeat;
  const fieldErrors = accept.error instanceof ApiError ? accept.error.fields : {};

  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (!mismatch) accept.mutate();
  };

  return (
    <AuthShell title={t.invite.title} help={t.invite.help}>
      <form onSubmit={submit} noValidate>
        {accept.isError && (
          <Alert tone="error">
            {accept.error instanceof ApiError
              ? accept.error.code === "invalid_token"
                ? t.invite.invalidToken
                : apiErrorMessage(accept.error.code, accept.error.message)
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
          <Button type="submit" loading={accept.isPending} disabled={mismatch}>
            {t.invite.submit}
          </Button>
        </div>
      </form>
    </AuthShell>
  );
}
