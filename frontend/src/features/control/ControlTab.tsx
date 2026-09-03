import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ApiError } from "@/api/client";
import { authApi } from "@/api/auth";
import { controlApi, TERMINAL, type Command } from "@/api/control";
import type { DeviceDetails, FeatureRow } from "@/api/devices";
import { Alert, Button, Card, Chip, Field } from "@/components/ui";
import { groupLabel, groupRows } from "@/features/devices/groups";
import { formatDateTime } from "@/features/devices/format";
import { t } from "@/i18n/pl";
import { ParamInputs } from "./ParamInputs";
import { defaultParams, type ParamSchema } from "./params";
import s from "./control.module.css";

type CommandTarget = { row: FeatureRow; command: string; schema: Record<string, ParamSchema> };

/** docs/09 §Sterowanie — controls per type, ConfirmDialog, ReauthDialog, status polling. */
export function ControlTab({ tid, device, rows }: { tid: string; device: DeviceDetails; rows: FeatureRow[] }) {
  const [target, setTarget] = useState<CommandTarget | null>(null);
  const executable = useMemo(
    () =>
      rows
        .filter((r) => r.is_enabled)
        .map((r) => ({ row: r, commands: Object.entries(r.commands).filter(([, c]) => c.executable) }))
        .filter((x) => x.commands.length > 0),
    [rows],
  );
  const groups = useMemo(() => groupRows(executable.map((x) => x.row)), [executable]);
  const byFeature = useMemo(() => new Map(executable.map((x) => [x.row.feature_name, x.commands])), [executable]);

  if (!device.capabilities.can_control) {
    return (
      <Card title={t.control.title}>
        <Alert tone="warn">{t.control.notAllowed}</Alert>
        <ul className={s.reasons}>
          {device.capabilities.reasons.map((r) => (
            <li key={r}>{t.control.reasons[r as keyof typeof t.control.reasons] ?? r}</li>
          ))}
        </ul>
      </Card>
    );
  }
  if (executable.length === 0) {
    return (
      <Card title={t.control.title}>
        <p className={s.sub}>{t.control.noCommands}</p>
      </Card>
    );
  }
  return (
    <>
      {groups.map((g) => (
        <section key={g.key} className={s.section}>
          <h2 className={s.sectionTitle}>{groupLabel(g.key)}</h2>
          <div className={s.list}>
            {g.rows.map((row) => (
              <div key={row.feature_name} className={s.item}>
                <div className={s.itemHead}>
                  <div>
                    <div className={s.itemLabel}>{row.label_pl ?? row.feature_name}</div>
                    <div className={s.mono}>{row.feature_name}</div>
                  </div>
                  <div className={s.current}>{currentValues(row)}</div>
                </div>
                <div className={s.itemActions}>
                  {(byFeature.get(row.feature_name) ?? []).map(([name, c]) => (
                    <Button key={name} variant="secondary" onClick={() => setTarget({ row, command: name, schema: (c.params as Record<string, ParamSchema>) ?? {} })}>
                      {t.control.commandLabel(name)}
                    </Button>
                  ))}
                </div>
              </div>
            ))}
          </div>
        </section>
      ))}
      {target && <CommandDialog tid={tid} deviceId={device.id} target={target} onClose={() => setTarget(null)} />}
    </>
  );
}

function currentValues(row: FeatureRow): string {
  return Object.entries(row.properties)
    .filter(([, p]) => p.value !== null && p.value !== undefined && typeof p.value !== "object")
    .map(([name, p]) => `${name}: ${String(p.value)}${p.unit ? ` ${p.unit}` : ""}`)
    .join(" · ");
}

/** Flow: form → draft → confirm (checkbox + countdown) → optional reauth → poll status. */
function CommandDialog({ tid, deviceId, target, onClose }: { tid: string; deviceId: string; target: CommandTarget; onClose: () => void }) {
  const qc = useQueryClient();
  const [params, setParams] = useState<Record<string, unknown>>(() => defaultParams(target.schema, target.row));
  const [draft, setDraft] = useState<Command | null>(null);
  const [ack, setAck] = useState(false);
  const [reauth, setReauth] = useState<{ password: string; totp: string } | null>(null);
  const [tracked, setTracked] = useState<string | null>(null);

  const create = useMutation({
    mutationFn: () => controlApi.createDraft(tid, deviceId, { feature_name: target.row.feature_name, command_name: target.command, params }),
    onSuccess: (c) => setDraft(c),
  });
  const confirm = useMutation({
    mutationFn: async () => {
      if (reauth) await authApi.reauth({ password: reauth.password, totp: reauth.totp || undefined });
      return controlApi.confirm(tid, draft!.id);
    },
    onSuccess: (c) => {
      setTracked(c.id);
      qc.invalidateQueries({ queryKey: ["commands", tid] });
    },
  });
  const status = useQuery({
    queryKey: ["command", tid, tracked],
    queryFn: () => controlApi.get(tid, tracked!),
    enabled: !!tracked,
    refetchInterval: (q) => (q.state.data && TERMINAL.includes(q.state.data.status) ? false : 3000),
    refetchIntervalInBackground: true,
  });
  useEffect(() => {
    if (status.data && TERMINAL.includes(status.data.status)) {
      qc.invalidateQueries({ queryKey: ["features", tid, deviceId] });
      qc.invalidateQueries({ queryKey: ["device", tid, deviceId] });
    }
  }, [status.data, qc, tid, deviceId]);

  const createErr = create.error instanceof ApiError ? create.error : null;
  const confirmErr = confirm.error instanceof ApiError ? confirm.error : null;
  const needsReauth = confirmErr?.code === "reauth_required" || confirmErr?.code === "totp_required";
  useEffect(() => {
    if (needsReauth && !reauth) setReauth({ password: "", totp: "" });
  }, [needsReauth, reauth]);

  const title = `${t.control.commandLabel(target.command)} — ${target.row.label_pl ?? target.row.feature_name}`;

  return (
    <div className={s.backdrop} role="dialog" aria-modal="true" aria-label={title}>
      <div className={s.dialog}>
        <h2 className={s.dialogTitle}>{title}</h2>
        <div className={s.mono}>{target.row.feature_name}</div>

        {!draft && (
          <form
            onSubmit={(e) => {
              e.preventDefault();
              create.mutate();
            }}
            noValidate
          >
            <ParamInputs schema={target.schema} values={params} onChange={setParams} errors={createErr?.fields ?? {}} />
            {createErr && createErr.code !== "constraint_violation" && (
              <Alert tone="error">
                {createErr.code === "control_not_allowed" ? t.control.notAllowed : createErr.message}
                {Array.isArray((createErr.extra as { reasons?: string[] } | undefined)?.reasons) && (
                  <ul className={s.reasons}>
                    {((createErr.extra as { reasons: string[] }).reasons ?? []).map((r) => (
                      <li key={r}>{t.control.reasons[r as keyof typeof t.control.reasons] ?? r}</li>
                    ))}
                  </ul>
                )}
              </Alert>
            )}
            <div className={s.actions}>
              <Button type="button" variant="ghost" onClick={onClose}>
                {t.common.cancel}
              </Button>
              <Button type="submit" loading={create.isPending}>
                {t.control.next}
              </Button>
            </div>
          </form>
        )}

        {draft && !tracked && (
          <form
            onSubmit={(e) => {
              e.preventDefault();
              confirm.mutate();
            }}
            noValidate
          >
            <ConfirmSummary draft={draft} />
            {draft.sensitive && <Alert tone="warn">{t.control.sensitive}</Alert>}
            {confirmErr && !needsReauth && <Alert tone="error">{confirmErr.code === "command_expired" ? t.control.expired : confirmErr.message}</Alert>}
            {reauth && (
              <div className={s.form}>
                <p className={s.sub}>{t.control.reauthHelp}</p>
                <Field label={t.common.password} type="password" autoComplete="current-password" value={reauth.password} onChange={(e) => setReauth({ ...reauth, password: e.target.value })} required />
                <Field label={t.common.totpCode} inputMode="numeric" autoComplete="one-time-code" value={reauth.totp} onChange={(e) => setReauth({ ...reauth, totp: e.target.value })} />
              </div>
            )}
            <label className={s.ack}>
              <input type="checkbox" checked={ack} onChange={(e) => setAck(e.target.checked)} /> {t.control.acknowledge}
            </label>
            <Countdown until={draft.expires_at} />
            <div className={s.actions}>
              <Button type="button" variant="ghost" onClick={onClose}>
                {t.common.cancel}
              </Button>
              <Button type="submit" variant={draft.sensitive ? "danger" : "primary"} loading={confirm.isPending} disabled={!ack || (reauth !== null && !reauth.password)}>
                {t.control.confirm}
              </Button>
            </div>
          </form>
        )}

        {tracked && (
          <div>
            <ConfirmSummary draft={draft!} />
            <div className={s.statusRow}>
              <StatusChip status={status.data?.status ?? "confirmed"} />
              <span className={s.sub}>{t.control.statusHelp[status.data?.status ?? "confirmed"]}</span>
            </div>
            {status.data?.reject_reason && <Alert tone="error">{status.data.reject_reason}</Alert>}
            {status.data?.job?.error && <Alert tone="error">{status.data.job.error}</Alert>}
            <div className={s.actions}>
              <Button type="button" onClick={onClose}>
                {t.common.close}
              </Button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

function ConfirmSummary({ draft }: { draft: Command }) {
  return (
    <div className={s.summary}>
      <div>
        <div className={s.sub}>{t.control.before}</div>
        <div className={s.value}>{fmt(draft.value_before)}</div>
      </div>
      <div className={s.arrow} aria-hidden="true">
        →
      </div>
      <div>
        <div className={s.sub}>{t.control.after}</div>
        <div className={s.value}>{fmt(draft.value_after)}</div>
      </div>
    </div>
  );
}

function fmt(v: Record<string, unknown> | null): string {
  if (!v || Object.keys(v).length === 0) return "—";
  return Object.entries(v)
    .map(([k, val]) => (typeof val === "object" ? `${k}: ${t.control.scheduleValue}` : `${k}: ${val === null || val === undefined ? "—" : String(val)}`))
    .join(" · ");
}

function Countdown({ until }: { until: string }) {
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    const id = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(id);
  }, []);
  const left = Math.max(0, Math.floor((new Date(until).getTime() - now) / 1000));
  return (
    <p className={s.sub}>
      {left > 0 ? t.control.expiresIn(left) : t.control.expired} · {formatDateTime(until)}
    </p>
  );
}

export function StatusChip({ status }: { status: Command["status"] }) {
  const tone = status === "verified" ? "ok" : status === "failed" || status === "rejected" || status === "expired" ? "off" : status === "verify_mismatch" ? "ctrl" : "neutral";
  return <Chip tone={tone}>{t.control.status[status]}</Chip>;
}
