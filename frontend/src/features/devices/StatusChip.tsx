import type { DeviceMode, DeviceStatus } from "@/api/devices";
import { Chip } from "@/components/ui";
import { t } from "@/i18n/pl";

export function StatusChip({ status }: { status: DeviceStatus }) {
  const tone = status === "online" ? "ok" : status === "offline" || status === "error" ? "off" : "read";
  return <Chip tone={tone}>{t.devices.status[status]}</Chip>;
}

export function ModeChip({ mode }: { mode: DeviceMode }) {
  return <Chip tone={mode === "control" ? "ctrl" : "read"}>{t.devices.mode[mode]}</Chip>;
}
