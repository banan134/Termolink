import * as echarts from "echarts";
import { useEffect, useImperativeHandle, useRef, forwardRef } from "react";
import type { HistoryResponse } from "@/api/devices";
import { RESOLUTION_LABEL, SERIES_COLORS, axisFromZero, cssVar, formatTs, isDark, unitLabel } from "./chartTheme";

export type ChartSeries = {
  key: string;
  label: string; // Polish label
  history: HistoryResponse;
  dashed?: boolean; // previous-period overlay
  shiftMs?: number; // shift x by this amount (overlay alignment)
};

export type ChartHandle = {
  /** PNG per docs/09: white background, footer with range/resolution/timezone/client. */
  toPng: (opts: { footer: string; pixelRatio?: number }) => string | null;
  resetZoom: () => void;
};

type Props = {
  series: ChartSeries[];
  height?: number;
  title?: string;
  subtitle?: string;
  showLegend?: boolean;
  enableZoom?: boolean;
  onZoom?: (from: Date, to: Date) => void;
  hiddenSeries?: Set<string>;
  onLegendToggle?: (key: string, visible: boolean) => void;
  compact?: boolean;
};

export const ChartLine = forwardRef<ChartHandle, Props>(function ChartLine(
  { series, height = 320, title, subtitle, showLegend, enableZoom = false, onZoom, compact = false },
  ref,
) {
  const el = useRef<HTMLDivElement>(null);
  const chart = useRef<echarts.ECharts | null>(null);

  useImperativeHandle(ref, () => ({
    toPng: ({ footer, pixelRatio = 2 }) => {
      const c = chart.current;
      if (!c) return null;
      const prev = c.getOption();
      c.setOption({ backgroundColor: "#ffffff", graphic: [{ type: "text", left: 12, bottom: 6, style: { text: footer, fill: "#5a6275", font: "11px Inter, sans-serif" } }] }, false);
      const url = c.getDataURL({ type: "png", pixelRatio, backgroundColor: "#ffffff" });
      c.setOption({ backgroundColor: "transparent", graphic: [] }, false);
      void prev;
      return url;
    },
    resetZoom: () => chart.current?.dispatchAction({ type: "dataZoom", start: 0, end: 100 }),
  }));

  useEffect(() => {
    if (!el.current) return;
    chart.current = echarts.init(el.current, undefined, { renderer: "canvas" });
    const resize = () => chart.current?.resize();
    window.addEventListener("resize", resize);
    const observer = new ResizeObserver(resize);
    observer.observe(el.current);
    return () => {
      window.removeEventListener("resize", resize);
      observer.disconnect();
      chart.current?.dispose();
      chart.current = null;
    };
  }, []);

  useEffect(() => {
    const c = chart.current;
    if (!c) return;
    const dark = isDark();
    const text = cssVar("--text", dark ? "#e9ecf4" : "#1c1c1c");
    const muted = cssVar("--text-muted", "#5a6275");
    const grid = cssVar("--border", dark ? "#2b3653" : "#d7dce8");
    const units = Array.from(new Set(series.map((s) => s.history.unit ?? "")));
    const yAxes = units.map((u, i) => ({
      type: "value" as const,
      name: unitLabel(u),
      nameTextStyle: { color: muted },
      position: i === 0 ? ("left" as const) : ("right" as const),
      scale: !series.some((s) => (s.history.unit ?? "") === u && axisFromZero(s.history.unit, s.history.feature)),
      axisLabel: { color: muted },
      splitLine: { show: i === 0, lineStyle: { color: grid } },
    }));

    const gaps = series[0]?.history.gaps ?? [];
    const markers = series.flatMap((s) => s.history.markers ?? []);

    const echartsSeries = series.flatMap((s, idx) => {
      const color = SERIES_COLORS[idx % SERIES_COLORS.length];
      const raw = s.history.resolution === "raw";
      const shift = s.shiftMs ?? 0;
      const yAxisIndex = units.indexOf(s.history.unit ?? "");
      const line = {
        name: s.label,
        type: "line" as const,
        yAxisIndex,
        showSymbol: false,
        connectNulls: false,
        sampling: "lttb" as const,
        lineStyle: { width: compact ? 1.5 : 2, type: s.dashed ? ("dashed" as const) : ("solid" as const), color },
        itemStyle: { color },
        data: s.history.points.map((p) => [new Date(p.ts).getTime() + shift, raw ? p.value : p.avg]),
        markArea:
          idx === 0 && gaps.length
            ? {
                silent: true,
                itemStyle: { color: dark ? "rgba(163,173,198,0.18)" : "rgba(90,98,117,0.12)" },
                data: gaps.map((g) => [{ xAxis: new Date(g.from).getTime(), name: "offline" }, { xAxis: new Date(g.to).getTime() }]),
              }
            : undefined,
        markLine:
          idx === 0 && markers.length
            ? {
                symbol: "none",
                lineStyle: { color: "#8a5a00", type: "dotted" },
                label: { formatter: (p: { name: string }) => p.name, color: muted },
                data: markers.map((m) => ({ xAxis: new Date(m.ts).getTime(), name: m.label })),
              }
            : undefined,
      };
      if (raw) return [line];
      const band = {
        name: `${s.label} (min–max)`,
        type: "line" as const,
        yAxisIndex,
        showSymbol: false,
        lineStyle: { opacity: 0 },
        stack: `band-${idx}`,
        silent: true,
        data: s.history.points.map((p) => [new Date(p.ts).getTime() + shift, p.min]),
        tooltip: { show: false },
      };
      const bandTop = {
        ...band,
        name: `${s.label} (max)`,
        areaStyle: { color, opacity: 0.12 },
        data: s.history.points.map((p) => [new Date(p.ts).getTime() + shift, (p.max ?? 0) - (p.min ?? 0)]),
      };
      return [band, bandTop, line];
    });

    c.setOption(
      {
        backgroundColor: "transparent",
        animation: false,
        color: SERIES_COLORS,
        title: title
          ? { text: title, subtext: subtitle, left: 0, textStyle: { color: text, fontSize: 14, fontWeight: 600 }, subtextStyle: { color: muted, fontFamily: "JetBrains Mono, monospace", fontSize: 11 } }
          : undefined,
        grid: { left: 52, right: units.length > 1 ? 52 : 16, top: title ? 56 : compact ? 12 : 28, bottom: enableZoom ? 52 : 32 },
        legend: showLegend && series.length > 1 ? { top: title ? 30 : 0, right: 0, textStyle: { color: muted }, data: series.map((s) => s.label) } : { show: false },
        tooltip: {
          trigger: "axis",
          backgroundColor: dark ? "#161d2e" : "#ffffff",
          borderColor: grid,
          textStyle: { color: text, fontSize: 12 },
          formatter: (params: unknown) => {
            const items = (Array.isArray(params) ? params : [params]) as { seriesName: string; value: [number, number]; color: string; seriesIndex: number }[];
            if (!items.length) return "";
            const head = formatTs(items[0].value[0]);
            const lines = items
              .filter((it) => !/\(min–max\)|\(max\)/.test(it.seriesName))
              .map((it) => {
                const s = series[Math.floor(it.seriesIndex / (series[0]?.history.resolution === "raw" ? 1 : 3))];
                const u = unitLabel(s?.history.unit);
                const v = it.value[1];
                return `<span style="display:inline-block;width:8px;height:8px;border-radius:50%;background:${it.color};margin-right:6px"></span>${it.seriesName}: <b>${v === null || v === undefined ? "—" : Number(v).toFixed(1)} ${u}</b>`;
              });
            return `<div>${head}</div>${lines.join("<br/>")}`;
          },
        },
        xAxis: {
          type: "time",
          axisLabel: { color: muted, hideOverlap: true },
          axisLine: { lineStyle: { color: grid } },
          splitLine: { show: true, lineStyle: { color: grid, opacity: 0.6 } },
        },
        yAxis: yAxes.length ? yAxes : [{ type: "value" }],
        dataZoom: enableZoom
          ? [
              { type: "inside", filterMode: "none" },
              { type: "slider", height: 18, bottom: 8, borderColor: grid, textStyle: { color: muted } },
            ]
          : undefined,
        series: echartsSeries,
        graphic: [],
      },
      true,
    );

    if (enableZoom && onZoom) {
      c.off("datazoom");
      c.on("datazoom", () => {
        const opt = c.getOption() as { dataZoom?: { startValue?: number; endValue?: number }[] };
        const dz = opt.dataZoom?.[0];
        if (dz?.startValue !== undefined && dz?.endValue !== undefined) onZoom(new Date(dz.startValue), new Date(dz.endValue));
      });
    }
  }, [series, title, subtitle, showLegend, enableZoom, onZoom, compact]);

  return (
    <div>
      <div ref={el} style={{ width: "100%", height }} role="img" aria-label={title ?? "Wykres"} />
      {series[0] && (
        <div style={{ fontSize: "var(--fs-xs)", color: "var(--text-muted)", marginTop: 4 }}>
          {RESOLUTION_LABEL[series[0].history.resolution]}
          {series[0].history.downsampled ? " · próbkowane" : ""}
          {series[0].history.gaps.length ? ` · offline: ${series[0].history.gaps.length}` : ""}
        </div>
      )}
    </div>
  );
});
