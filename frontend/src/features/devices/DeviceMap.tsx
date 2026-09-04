import { useEffect, useRef } from "react";
import L from "leaflet";
import "leaflet/dist/leaflet.css";
import { t } from "@/i18n/pl";
import { DEFAULT_CENTER, STATUS_COLOR, escapeHtml } from "./mapUtils";
import s from "./devices.module.css";

export type MapDevice = { id: string; display_name: string; model: string; status: string; lat: number | null; lon: number | null; tenant_id?: string; tenant_name?: string };

/** Read-only map of devices with status-coloured markers (operator panel and customer panel). */
export function DeviceMap({ devices, linkFor, height = 360 }: { devices: MapDevice[]; linkFor: (d: MapDevice) => string; height?: number }) {
  const ref = useRef<HTMLDivElement>(null);
  const mapRef = useRef<L.Map | null>(null);
  const located = devices.filter((d) => d.lat !== null && d.lon !== null);
  const key = located.map((d) => `${d.id}:${d.lat}:${d.lon}:${d.status}`).join("|");
  useEffect(() => {
    if (!ref.current) return;
    if (!mapRef.current) {
      mapRef.current = L.map(ref.current, { scrollWheelZoom: false }).setView(DEFAULT_CENTER, 7);
      L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", { attribution: "© OpenStreetMap", maxZoom: 18 }).addTo(mapRef.current);
    }
    const map = mapRef.current;
    const layer = L.layerGroup().addTo(map);
    for (const d of located) {
      const color = STATUS_COLOR[d.status] ?? "#6b7280";
      const marker = L.circleMarker([d.lat!, d.lon!], { radius: 9, color, fillColor: color, fillOpacity: 0.85, weight: 2 });
      marker.bindPopup(`<b>${escapeHtml(d.display_name)}</b>${d.tenant_name ? `<br>${escapeHtml(d.tenant_name)}` : ""}<br>${escapeHtml(d.status)} · ${escapeHtml(d.model)}<br><a href="${linkFor(d)}">${escapeHtml(t.operator.open)}</a>`);
      marker.addTo(layer);
    }
    if (located.length > 0) map.fitBounds(L.latLngBounds(located.map((d) => [d.lat!, d.lon!] as [number, number])).pad(0.3), { maxZoom: 13 });
    return () => {
      layer.remove();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);
  useEffect(
    () => () => {
      mapRef.current?.remove();
      mapRef.current = null;
    },
    [],
  );
  return (
    <>
      <div ref={ref} className={s.map} style={{ height }} />
      {located.length === 0 && <p className={s.sub}>{t.operator.mapEmpty}</p>}
    </>
  );
}
