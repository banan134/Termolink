import { useState, type FormEvent } from "react";
import { Link, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { alertsApi, type AlertRule, type RuleConfig } from "@/api/alerts";
import { ApiError } from "@/api/client";
import { devicesApi } from "@/api/devices";
import { PageTitle } from "@/app/AppLayout";
import { Alert, Button, Card, Chip, Field, Skeleton } from "@/components/ui";
import { t } from "@/i18n/pl";
import s from "./alerts.module.css";

type RuleType = AlertRule["type"];

/** Reguły alarmów (docs/10): offline po N min, wartość poza zakresem, komunikaty urządzenia. */
export default function AlertRulesPage() {
  const { tid = "" } = useParams();
  const qc = useQueryClient();
  const rules = useQuery({ queryKey: ["alert-rules", tid], queryFn: () => alertsApi.rules(tid) });
  const devices = useQuery({ queryKey: ["devices", tid], queryFn: () => devicesApi.list(tid) });
  const invalidate = () => qc.invalidateQueries({ queryKey: ["alert-rules", tid] });
  const toggle = useMutation({ mutationFn: (r: AlertRule) => alertsApi.updateRule(tid, r.id, { enabled: !r.enabled }), onSuccess: invalidate });
  const remove = useMutation({ mutationFn: (id: string) => alertsApi.deleteRule(tid, id), onSuccess: invalidate });

  const [type, setType] = useState<RuleType>("device_offline");
  const [deviceId, setDeviceId] = useState("");
  const [minutes, setMinutes] = useState("30");
  const [feature, setFeature] = useState("");
  const [property, setProperty] = useState("value");
  const [min, setMin] = useState("");
  const [max, setMax] = useState("");
  const [email, setEmail] = useState(true);
  const create = useMutation({
    mutationFn: () => {
      const config: RuleConfig = { email };
      if (type === "device_offline") config.minutes = Number(minutes);
      if (type === "value_out_of_range") {
        config.feature = feature.trim();
        config.property = property.trim() || "value";
        config.min = min === "" ? null : Number(min);
        config.max = max === "" ? null : Number(max);
      }
      return alertsApi.createRule(tid, { type, device_id: deviceId || null, config });
    },
    onSuccess: () => {
      invalidate();
      setFeature("");
      setMin("");
      setMax("");
    },
  });
  const err = create.error instanceof ApiError ? create.error : null;
  const deviceList = devices.data?.results ?? [];

  return (
    <>
      <p className={s.sub}>
        <Link to={`/t/${tid}/alerts`} style={{ color: "var(--accent)" }}>{t.alerts.title}</Link> / {t.alerts.rules}
      </p>
      <PageTitle>{t.alerts.rules}</PageTitle>
      <p className={s.sub}>{t.alerts.rulesHelp}</p>

      <Card title={t.alerts.newRule}>
        <form
          onSubmit={(e: FormEvent) => {
            e.preventDefault();
            create.mutate();
          }}
          noValidate
          className={s.form}
        >
          {err && <Alert tone="error">{err.message}</Alert>}
          <div className={s.row}>
            <label className={s.field}>
              <span className={s.sub}>{t.alerts.type}</span>
              <select value={type} onChange={(e) => setType(e.target.value as RuleType)} className={s.select}>
                <option value="device_offline">{t.alerts.types.device_offline}</option>
                <option value="value_out_of_range">{t.alerts.types.value_out_of_range}</option>
                <option value="device_message">{t.alerts.types.device_message}</option>
              </select>
            </label>
            <label className={s.field}>
              <span className={s.sub}>{t.alerts.device}</span>
              <select value={deviceId} onChange={(e) => setDeviceId(e.target.value)} className={s.select}>
                <option value="">{t.alerts.allDevices}</option>
                {deviceList.map((d) => (
                  <option key={d.id} value={d.id}>
                    {d.display_name}
                  </option>
                ))}
              </select>
            </label>
          </div>
          {type === "device_offline" && <Field label={t.alerts.minutes} type="number" min={1} max={10080} value={minutes} onChange={(e) => setMinutes(e.target.value)} error={err?.fields.minutes} />}
          {type === "value_out_of_range" && (
            <>
              <Field label={t.alerts.feature} value={feature} onChange={(e) => setFeature(e.target.value)} placeholder="heating.sensors.temperature.outside" error={err?.fields.feature} required />
              <div className={s.row}>
                <Field label={t.alerts.property} value={property} onChange={(e) => setProperty(e.target.value)} />
                <Field label={t.alerts.min} type="number" step="any" value={min} onChange={(e) => setMin(e.target.value)} error={err?.fields.min} />
                <Field label={t.alerts.max} type="number" step="any" value={max} onChange={(e) => setMax(e.target.value)} error={err?.fields.max} />
              </div>
            </>
          )}
          {type === "device_message" && <p className={s.sub}>{t.alerts.messageHelp}</p>}
          <label className={s.toggle}>
            <input type="checkbox" checked={email} onChange={(e) => setEmail(e.target.checked)} /> {t.alerts.emailNotify}
          </label>
          <div className={s.actions}>
            <Button type="submit" loading={create.isPending} disabled={type === "value_out_of_range" && !feature.trim()}>
              {t.common.add}
            </Button>
          </div>
        </form>
      </Card>

      {rules.isPending && <Skeleton height={80} />}
      {rules.data && (
        <Card title={t.alerts.rulesList}>
          {rules.data.results.length === 0 && <p className={s.sub}>{t.alerts.noRules}</p>}
          <div className={s.list}>
            {rules.data.results.map((r) => (
              <div key={r.id} className={s.rule}>
                <div className={s.itemMain}>
                  <div className={s.itemTop}>
                    <Chip tone={r.enabled ? "ok" : "neutral"}>{r.enabled ? t.alerts.enabled : t.alerts.disabled}</Chip>
                    <span className={s.type}>{t.alerts.types[r.type]}</span>
                    <span className={s.sub}>· {r.device_name ?? t.alerts.allDevices}</span>
                  </div>
                  <div className={s.sub}>{describe(r)}</div>
                </div>
                <div className={s.actions}>
                  <Button variant="ghost" onClick={() => toggle.mutate(r)} loading={toggle.isPending && toggle.variables?.id === r.id}>
                    {r.enabled ? t.alerts.disable : t.alerts.enable}
                  </Button>
                  <Button variant="danger" onClick={() => window.confirm(t.alerts.deleteConfirm) && remove.mutate(r.id)}>
                    {t.common.delete}
                  </Button>
                </div>
              </div>
            ))}
          </div>
        </Card>
      )}
    </>
  );
}

function describe(r: AlertRule): string {
  const parts: string[] = [];
  if (r.type === "device_offline") parts.push(t.alerts.offlineAfter(r.config.minutes ?? 30));
  if (r.type === "value_out_of_range") parts.push(`${r.config.feature}.${r.config.property ?? "value"} ∉ [${r.config.min ?? "−∞"}, ${r.config.max ?? "∞"}]`);
  if (r.type === "device_message") parts.push(t.alerts.messageHelp);
  parts.push(r.config.email === false ? t.alerts.emailOff : t.alerts.emailOn);
  return parts.join(" · ");
}
