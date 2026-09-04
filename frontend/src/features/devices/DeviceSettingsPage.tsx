import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { type FormEvent, useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { authApi, isOperator } from "@/api/auth";
import { ApiError } from "@/api/client";
import { devicesApi, type DeviceMode } from "@/api/devices";
import { PageTitle } from "@/app/AppLayout";
import { Alert, Button, Card, Field } from "@/components/ui";
import { useMe } from "@/features/auth/useMe";
import { t } from "@/i18n/pl";
import { LocationPicker } from "./LocationPicker";
import s from "./devices.module.css";

/** /t/:tid/devices/:id/settings (docs/09): tenant_admin edits name/location/description;
 *  operators additionally mode (with reauth), interval and command limit. */
export default function DeviceSettingsPage() {
  const { tid = "", id = "" } = useParams();
  const me = useMe();
  const qc = useQueryClient();
  const navigate = useNavigate();
  const device = useQuery({ queryKey: ["device", tid, id], queryFn: () => devicesApi.get(tid, id) });
  const [name, setName] = useState("");
  const [location, setLocation] = useState("");
  const [description, setDescription] = useState("");
  const [coords, setCoords] = useState<{ lat: number | null; lon: number | null }>({ lat: null, lon: null });
  const [mode, setMode] = useState<DeviceMode>("read");
  const [interval, setInterval] = useState("");
  const [limit, setLimit] = useState("10");
  const [reauth, setReauth] = useState<{ password: string; totp: string } | null>(null);
  useEffect(() => {
    if (device.data) {
      setName(device.data.display_name);
      setLocation(device.data.location_text ?? "");
      setCoords({ lat: device.data.lat, lon: device.data.lon });
      setDescription(device.data.description ?? "");
      setMode(device.data.mode);
      setInterval(device.data.poll_interval_s ? String(device.data.poll_interval_s) : "");
      setLimit(String(device.data.commands_per_hour_limit));
    }
  }, [device.data]);

  const operator = isOperator(me.data);
  const save = useMutation({
    mutationFn: async () => {
      if (operator && reauth) await authApi.reauth({ password: reauth.password, totp: reauth.totp || undefined });
      return devicesApi.patch(tid, id, {
        display_name: name,
        location_text: location || null,
        lat: coords.lat,
        lon: coords.lon,
        description: description || null,
        ...(operator ? { mode, poll_interval_s: interval ? Number(interval) : null, commands_per_hour_limit: Number(limit) } : {}),
      });
    },
    onSuccess: (row) => {
      qc.setQueryData(["device", tid, id], row);
      qc.invalidateQueries({ queryKey: ["devices", tid] });
      navigate(`/t/${tid}/devices/${id}`);
    },
  });
  const remove = useMutation({
    mutationFn: () => devicesApi.remove(tid, id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["devices", tid] });
      navigate(`/t/${tid}`);
    },
  });
  const archive = useMutation({
    mutationFn: () => devicesApi.archive(tid, id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["devices", tid] });
      navigate(`/t/${tid}`);
    },
  });

  if (!device.data) return null;
  const modeChanged = operator && mode !== device.data.mode;
  const err = save.error instanceof ApiError ? save.error : null;
  const needsReauth = err?.code === "reauth_required" || err?.code === "totp_required";

  return (
    <>
      <p className={s.sub}>
        <Link to={`/t/${tid}/devices/${id}`} style={{ color: "var(--accent)" }}>{device.data.display_name}</Link> / {t.devices.settings}
      </p>
      <PageTitle>{t.devices.settings}</PageTitle>
      <Card>
        <form
          onSubmit={(e: FormEvent) => {
            e.preventDefault();
            if (modeChanged && !reauth) {
              setReauth({ password: "", totp: "" });
              return;
            }
            save.mutate();
          }}
          noValidate
        >
          {err && !needsReauth && <Alert tone="error">{err.message}</Alert>}
          <Field label={t.devices.name} value={name} onChange={(e) => setName(e.target.value)} required />
          <Field label={t.devices.location} value={location} onChange={(e) => setLocation(e.target.value)} />
          <LocationPicker value={coords} onChange={setCoords} />
          <Field label={t.devices.description} value={description} onChange={(e) => setDescription(e.target.value)} />
          {operator && (
            <>
              <div className={s.radioRow} role="radiogroup" aria-label={t.devices.modeLabel}>
                <label>
                  <input type="radio" checked={mode === "read"} onChange={() => setMode("read")} /> {t.devices.mode.read}
                </label>
                <label>
                  <input type="radio" checked={mode === "control"} onChange={() => setMode("control")} /> {t.devices.mode.control}
                </label>
              </div>
              <p className={s.sub}>{t.devices.modeHelp}</p>
              <Field label={t.devices.intervalManual} type="number" min={60} max={86400} value={interval} onChange={(e) => setInterval(e.target.value)} help={t.devices.intervalHelp(device.data.effective_interval_s)} />
              <Field label={t.devices.commandsLimit} type="number" min={0} max={1000} value={limit} onChange={(e) => setLimit(e.target.value)} />
            </>
          )}
          {(modeChanged || needsReauth) && reauth && (
            <div className={s.form}>
              <p className={s.sub}>{t.devices.reauthHelp}</p>
              {needsReauth && <Alert tone="warn">{err?.message}</Alert>}
              <Field label={t.common.password} type="password" autoComplete="current-password" value={reauth.password} onChange={(e) => setReauth({ ...reauth, password: e.target.value })} required />
              <Field label={t.common.totpCode} inputMode="numeric" autoComplete="one-time-code" value={reauth.totp} onChange={(e) => setReauth({ ...reauth, totp: e.target.value })} />
            </div>
          )}
          <div className={s.actions}>
            {operator && (
              <Button type="button" variant="danger" loading={archive.isPending} onClick={() => window.confirm(t.devices.archiveConfirm) && archive.mutate()}>
                {t.devices.archive}
              </Button>
            )}
            {operator && (
              <Button type="button" variant="danger" loading={remove.isPending} onClick={() => window.prompt(t.devices.deleteConfirm(device.data!.display_name)) === device.data!.display_name && remove.mutate()}>
                {t.devices.deletePermanently}
              </Button>
            )}
            <span style={{ flex: 1 }} />
            <Link to={`/t/${tid}/devices/${id}`} className={s.buttonLink}>{t.common.cancel}</Link>
            <Button type="submit" loading={save.isPending} disabled={!name.trim()}>
              {t.common.save}
            </Button>
          </div>
        </form>
      </Card>
    </>
  );
}
