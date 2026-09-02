import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { type FormEvent, useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { ApiError } from "@/api/client";
import { devicesApi, type DeviceMode } from "@/api/devices";
import { providersApi, type DiscoveredDeviceRow, type ProviderAccountRow } from "@/api/providers";
import { Alert, Button, Card, Chip, Field, Skeleton } from "@/components/ui";
import { t } from "@/i18n/pl";
import a from "./admin.module.css";
import s from "@/features/devices/devices.module.css";

const STATUS_TONE: Record<ProviderAccountRow["status"], "ok" | "off" | "ctrl" | "read"> = {
  active: "ok",
  reauth_required: "off",
  rate_limited: "ctrl",
  disabled: "read",
};

/** Operator: Viessmann accounts of a tenant + discover + add-device wizard (docs/02 §A, docs/09). */
export function ProviderAccountsCard({ tenantId }: { tenantId: string }) {
  const qc = useQueryClient();
  const [params, setParams] = useSearchParams();
  const accounts = useQuery({ queryKey: ["provider-accounts", tenantId], queryFn: () => providersApi.list(tenantId), refetchInterval: 30_000 });
  const [label, setLabel] = useState("");
  const authorize = useMutation({
    mutationFn: () => providersApi.authorize(tenantId, "viessmann", label),
    onSuccess: ({ redirect_url }) => {
      window.location.assign(redirect_url);
    },
  });
  const connected = params.get("connected");
  const oauthError = params.get("error");
  useEffect(() => {
    if (connected || oauthError) {
      qc.invalidateQueries({ queryKey: ["provider-accounts", tenantId] });
    }
  }, [connected, oauthError, qc, tenantId]);

  return (
    <Card title={t.providers.title}>
      {connected && (
        <Alert tone="ok">
          {t.providers.connected}{" "}
          <button type="button" className={a.link} style={{ background: "none", border: 0, cursor: "pointer" }} onClick={() => setParams({})}>
            {t.common.close}
          </button>
        </Alert>
      )}
      {oauthError && <Alert tone="error">{t.providers.oauthError(oauthError)}</Alert>}
      {accounts.isPending && <Skeleton height={48} />}
      {accounts.isError && <Alert tone="error">{t.common.error}</Alert>}
      {accounts.data?.results.map((acc) => (
        <AccountRow key={acc.id} tenantId={tenantId} acc={acc} />
      ))}
      <form
        className={s.form}
        onSubmit={(e: FormEvent) => {
          e.preventDefault();
          authorize.mutate();
        }}
      >
        <h3 className={a.subTitle}>{t.providers.connect}</h3>
        <p className={a.muted} style={{ whiteSpace: "normal" }}>
          {t.providers.connectHelp}
        </p>
        {authorize.isError && (
          <Alert tone="error">
            {authorize.error instanceof ApiError && authorize.error.code === "provider_not_configured" ? t.providers.notConfigured : t.common.error}
          </Alert>
        )}
        <Field label={t.providers.label} value={label} onChange={(e) => setLabel(e.target.value)} placeholder="np. dom Olsztyn" />
        <div className={a.actions}>
          <Button type="submit" loading={authorize.isPending}>
            {t.providers.connectButton}
          </Button>
        </div>
      </form>
    </Card>
  );
}

function AccountRow({ tenantId, acc }: { tenantId: string; acc: ProviderAccountRow }) {
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
  const discover = useMutation({
    mutationFn: () => providersApi.discover(tenantId, acc.id),
    onSuccess: () => {
      setOpen(true);
      setTimeout(() => qc.invalidateQueries({ queryKey: ["discovered", tenantId, acc.id] }), 6000);
    },
  });
  const disconnect = useMutation({
    mutationFn: () => providersApi.disconnect(tenantId, acc.id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["provider-accounts", tenantId] }),
  });
  const pct = Math.min(100, Math.round((100 * acc.budget.used) / acc.budget.limit));
  return (
    <div className={a.row} style={{ flexDirection: "column", alignItems: "stretch" }}>
      <div style={{ display: "flex", justifyContent: "space-between", gap: "var(--sp-2)", alignItems: "center" }}>
        <div className={a.rowMain}>
          <span>
            <strong>{acc.label || "Viessmann"}</strong> <Chip tone={STATUS_TONE[acc.status]}>{t.providers.status[acc.status]}</Chip>
          </span>
          <span className={a.muted}>
            {t.providers.budget}: {acc.budget.used} / {acc.budget.limit} ({pct}%) · {t.providers.reserve}: {acc.budget.reserve_used} / {acc.budget.reserve} · {t.providers.devices}: {acc.devices_count}
            {acc.status_reason ? ` · ${acc.status_reason}` : ""}
          </span>
          <div className={s.budgetBar}>
            <div className={s.budgetFill} style={{ width: `${pct}%` }} />
          </div>
        </div>
        {acc.status !== "disabled" && (
          <span className={a.chips}>
            <Button variant="secondary" loading={discover.isPending} onClick={() => discover.mutate()}>
              {t.providers.discover}
            </Button>
            <Button variant="ghost" onClick={() => setOpen((v) => !v)}>
              {open ? t.common.close : t.providers.showDevices}
            </Button>
            <Button
              variant="ghost"
              loading={disconnect.isPending}
              onClick={() => {
                if (window.confirm(t.providers.disconnectConfirm)) disconnect.mutate();
              }}
            >
              {t.providers.disconnect}
            </Button>
          </span>
        )}
      </div>
      {discover.isError && <Alert tone="error">{discover.error instanceof ApiError ? discover.error.message : t.common.error}</Alert>}
      {open && <DiscoveredList tenantId={tenantId} accountId={acc.id} />}
    </div>
  );
}

function DiscoveredList({ tenantId, accountId }: { tenantId: string; accountId: string }) {
  const tree = useQuery({ queryKey: ["discovered", tenantId, accountId], queryFn: () => providersApi.discovered(tenantId, accountId), refetchInterval: 10_000 });
  const [adding, setAdding] = useState<{ installationId: string; gatewaySerial: string; row: DiscoveredDeviceRow } | null>(null);
  if (tree.isPending) return <Skeleton height={40} />;
  if (tree.isError || !tree.data) return <Alert tone="error">{t.common.error}</Alert>;
  const installations = tree.data.installations;
  if (installations.length === 0) return <p className={a.muted}>{t.providers.nothingDiscovered}</p>;
  return (
    <div>
      {installations.map((inst) =>
        inst.gateways.map((gw) => (
          <ul className={s.tree} key={inst.installation_id + gw.gateway_serial}>
            <li style={{ borderTop: 0 }}>
              <span className={a.muted}>
                {t.providers.installation} {inst.installation_id} · {t.providers.gateway} {gw.gateway_serial}
              </span>
            </li>
            {gw.devices.map((row) => (
              <li key={row.device_id}>
                <span>
                  <strong>{row.model ?? row.device_id}</strong>{" "}
                  <span className={a.muted}>
                    id {row.device_id}
                    {row.device_type ? ` · ${row.device_type}` : ""}
                    {row.online === true ? " · online" : row.online === false ? " · offline" : ""}
                  </span>
                </span>
                {row.already_added ? (
                  <Chip tone="ok">{t.providers.added}</Chip>
                ) : row.is_gateway ? (
                  <Chip tone="read">{t.providers.gatewayRow}</Chip>
                ) : (
                  <Button variant="secondary" onClick={() => setAdding({ installationId: inst.installation_id, gatewaySerial: gw.gateway_serial, row })}>
                    {t.providers.add}
                  </Button>
                )}
              </li>
            ))}
          </ul>
        )),
      )}
      {adding && <AddDeviceForm tenantId={tenantId} accountId={accountId} target={adding} onDone={() => setAdding(null)} />}
    </div>
  );
}

function AddDeviceForm({
  tenantId,
  accountId,
  target,
  onDone,
}: {
  tenantId: string;
  accountId: string;
  target: { installationId: string; gatewaySerial: string; row: DiscoveredDeviceRow };
  onDone: () => void;
}) {
  const qc = useQueryClient();
  const [name, setName] = useState(target.row.model ?? "");
  const [location, setLocation] = useState("");
  const [mode, setMode] = useState<DeviceMode>("read");
  const create = useMutation({
    mutationFn: () =>
      devicesApi.create(tenantId, {
        provider_account_id: accountId,
        external_ids: { installationId: target.installationId, gatewaySerial: target.gatewaySerial, deviceId: target.row.device_id },
        display_name: name,
        location_text: location || undefined,
        mode,
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["discovered", tenantId, accountId] });
      qc.invalidateQueries({ queryKey: ["devices", tenantId] });
      qc.invalidateQueries({ queryKey: ["provider-accounts", tenantId] });
      onDone();
    },
  });
  return (
    <form
      className={s.form}
      onSubmit={(e: FormEvent) => {
        e.preventDefault();
        if (name.trim()) create.mutate();
      }}
    >
      <h3 className={a.subTitle}>
        {t.providers.addTitle}: {target.row.model ?? target.row.device_id}
      </h3>
      {create.isError && <Alert tone="error">{create.error instanceof ApiError ? create.error.message : t.common.error}</Alert>}
      <Field label={t.devices.name} value={name} onChange={(e) => setName(e.target.value)} required autoFocus />
      <Field label={t.devices.location} value={location} onChange={(e) => setLocation(e.target.value)} />
      <div className={s.radioRow} role="radiogroup" aria-label={t.devices.modeLabel}>
        <label>
          <input type="radio" checked={mode === "read"} onChange={() => setMode("read")} /> {t.devices.mode.read}
        </label>
        <label>
          <input type="radio" checked={mode === "control"} onChange={() => setMode("control")} /> {t.devices.mode.control}
        </label>
      </div>
      <p className={a.muted} style={{ whiteSpace: "normal" }}>
        {t.devices.modeHelp}
      </p>
      <div className={s.actions}>
        <Button type="button" variant="ghost" onClick={onDone}>
          {t.common.cancel}
        </Button>
        <Button type="submit" loading={create.isPending} disabled={!name.trim()}>
          {t.providers.addConfirm}
        </Button>
      </div>
    </form>
  );
}

export function TenantDevicesCard({ tenantId }: { tenantId: string }) {
  const devices = useQuery({ queryKey: ["devices", tenantId], queryFn: () => devicesApi.list(tenantId) });
  return (
    <Card title={t.devices.title}>
      {devices.isPending && <Skeleton height={40} />}
      {devices.data?.count === 0 && <p className={a.muted}>{t.devices.emptyOperator}</p>}
      {devices.data?.results.map((d) => (
        <div className={a.row} key={d.id}>
          <div className={a.rowMain}>
            <Link to={`/t/${tenantId}/devices/${d.id}`} className={a.link}>
              {d.display_name}
            </Link>
            <span className={a.muted}>
              {d.model || "—"} · {t.devices.status[d.status]} · {t.devices.mode[d.mode]}
            </span>
          </div>
        </div>
      ))}
      {devices.data && devices.data.count > 0 && (
        <p style={{ marginTop: "var(--sp-3)" }}>
          <Link to={`/t/${tenantId}`} className={a.link}>
            {t.devices.openDashboard}
          </Link>
        </p>
      )}
    </Card>
  );
}
