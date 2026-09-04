import { useEffect, useRef } from "react";
import L from "leaflet";
import "leaflet/dist/leaflet.css";
import { Button, Field } from "@/components/ui";
import { t } from "@/i18n/pl";
import { DEFAULT_CENTER } from "./mapUtils";
import s from "./devices.module.css";

type Coords = { lat: number | null; lon: number | null };

/** Settings: click or drag the marker to place the device exactly (docs/09 §Ustawienia). */
export function LocationPicker({ value, onChange }: { value: Coords; onChange: (v: Coords) => void }) {
  const ref = useRef<HTMLDivElement>(null);
  const mapRef = useRef<L.Map | null>(null);
  const markerRef = useRef<L.Marker | null>(null);
  const onChangeRef = useRef(onChange);
  onChangeRef.current = onChange;

  useEffect(() => {
    if (!ref.current || mapRef.current) return;
    const has = value.lat !== null && value.lon !== null;
    const map = L.map(ref.current).setView(has ? [value.lat!, value.lon!] : DEFAULT_CENTER, has ? 15 : 7);
    L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", { attribution: "© OpenStreetMap", maxZoom: 19 }).addTo(map);
    const icon = L.divIcon({ className: s.pin, html: "●", iconSize: [22, 22], iconAnchor: [11, 11] });
    const place = (lat: number, lon: number) => {
      if (!markerRef.current) {
        markerRef.current = L.marker([lat, lon], { draggable: true, icon }).addTo(map);
        markerRef.current.on("dragend", () => {
          const p = markerRef.current!.getLatLng();
          onChangeRef.current({ lat: round(p.lat), lon: round(p.lng) });
        });
      } else markerRef.current.setLatLng([lat, lon]);
    };
    if (has) place(value.lat!, value.lon!);
    map.on("click", (e: L.LeafletMouseEvent) => {
      place(e.latlng.lat, e.latlng.lng);
      onChangeRef.current({ lat: round(e.latlng.lat), lon: round(e.latlng.lng) });
    });
    mapRef.current = map;
    return () => {
      map.remove();
      mapRef.current = null;
      markerRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // keep the marker in sync when the numeric inputs change
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    if (value.lat === null || value.lon === null) {
      markerRef.current?.remove();
      markerRef.current = null;
      return;
    }
    if (!markerRef.current) {
      const icon = L.divIcon({ className: s.pin, html: "●", iconSize: [22, 22], iconAnchor: [11, 11] });
      markerRef.current = L.marker([value.lat, value.lon], { draggable: true, icon }).addTo(map);
      markerRef.current.on("dragend", () => {
        const p = markerRef.current!.getLatLng();
        onChangeRef.current({ lat: round(p.lat), lon: round(p.lng) });
      });
    } else markerRef.current.setLatLng([value.lat, value.lon]);
  }, [value.lat, value.lon]);

  return (
    <div className={s.picker}>
      <p className={s.sub}>{t.devices.locationHelp}</p>
      <div ref={ref} className={s.map} style={{ height: 320 }} />
      <div className={s.pickerRow}>
        <Field label={t.devices.lat} type="number" step="0.000001" value={value.lat ?? ""} onChange={(e) => onChange({ ...value, lat: e.target.value === "" ? null : Number(e.target.value) })} />
        <Field label={t.devices.lon} type="number" step="0.000001" value={value.lon ?? ""} onChange={(e) => onChange({ ...value, lon: e.target.value === "" ? null : Number(e.target.value) })} />
        <Button type="button" variant="ghost" onClick={() => onChange({ lat: null, lon: null })} disabled={value.lat === null && value.lon === null}>
          {t.devices.clearLocation}
        </Button>
      </div>
    </div>
  );
}

function round(v: number): number {
  return Math.round(v * 1e6) / 1e6;
}
