import { useQuery } from "@tanstack/react-query";
import { devicesApi } from "@/api/devices";

/** 24 h raw sparkline for tiles (docs/09): tiny SVG, no axes, no interaction. */
export function Sparkline({ tid, id, feature, property = "value", width = 120, height = 28 }: { tid: string; id: string; feature: string; property?: string; width?: number; height?: number }) {
  const to = new Date();
  const from = new Date(to.getTime() - 24 * 3600 * 1000);
  const q = useQuery({
    queryKey: ["spark", tid, id, feature, property, from.toISOString().slice(0, 13)],
    queryFn: () => devicesApi.history(tid, id, { feature, property, from: from.toISOString(), to: to.toISOString(), resolution: "raw", max_points: 120 }),
    staleTime: 60_000,
  });
  const pts = q.data?.points ?? [];
  if (pts.length < 2) return <svg width={width} height={height} aria-hidden="true" />;
  const ys = pts.map((p) => p.value as number);
  const min = Math.min(...ys);
  const max = Math.max(...ys);
  const span = max - min || 1;
  const d = pts
    .map((p, i) => `${i === 0 ? "M" : "L"}${((i / (pts.length - 1)) * (width - 2) + 1).toFixed(1)},${(height - 2 - ((Number(p.value) - min) / span) * (height - 4)).toFixed(1)}`)
    .join(" ");
  return (
    <svg width={width} height={height} aria-hidden="true">
      <path d={d} fill="none" stroke="var(--brand-primary)" strokeWidth="1.5" />
    </svg>
  );
}
