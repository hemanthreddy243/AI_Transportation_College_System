import { useEffect } from "react";
import L from "leaflet";
import { CircleMarker, MapContainer, Marker, Polyline, TileLayer, Tooltip, useMap } from "react-leaflet";

export const ROUTE_COLORS = ["#2563eb", "#dc2626", "#16a34a", "#9333ea", "#ea580c", "#0891b2", "#db2777", "#65a30d", "#7c3aed", "#ca8a04"];

const busIcon = (label, color = "#111827", faded = false) =>
  L.divIcon({
    className: "",
    html: `<div class="bus-pin${faded ? " faded" : ""}" style="background:${color}">🚌 ${label ?? ""}</div>`,
    iconSize: null,
    iconAnchor: [20, 14],
  });

const campusIcon = L.divIcon({
  className: "",
  html: `<div class="campus-pin">🎓 Campus</div>`,
  iconSize: null,
  iconAnchor: [36, 14],
});

function FitBounds({ points }) {
  const map = useMap();
  const key = JSON.stringify(points);
  useEffect(() => {
    if (points.length > 1) map.fitBounds(points, { padding: [30, 30] });
    else if (points.length === 1) map.setView(points[0], 14);
  }, [key]); // eslint-disable-line react-hooks/exhaustive-deps
  return null;
}

/**
 * stops:  [{id,name,lat,lng, label?, highlight?}]
 * routes: [{color, points:[[lat,lng],...], label}]
 * buses:  [{id, lat, lng, label, color}]
 */
export default function RouteMap({ stops = [], routes = [], buses = [], campus, height = 380, fit }) {
  // `fit`: fixed points to frame, so live updates don't keep re-zooming the map
  const fitPoints = fit || [
    ...stops.map((s) => [s.lat, s.lng]),
    ...routes.flatMap((r) => r.points),
    ...(campus ? [[campus.lat, campus.lng]] : []),
  ];
  const center = fitPoints[0] || [17.42, 78.55];

  return (
    <div className="map-wrap" style={{ height }}>
      <MapContainer center={center} zoom={12} style={{ height: "100%", width: "100%" }} scrollWheelZoom={false}>
        <TileLayer
          attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
          url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
        />
        <FitBounds points={fitPoints} />
        {routes.map((r, i) => (
          <Polyline key={i} positions={r.points}
            pathOptions={{ color: r.color, weight: r.weight || 5, opacity: r.opacity ?? 0.8, dashArray: r.dash }}>
            {r.label && <Tooltip sticky>{r.label}</Tooltip>}
          </Polyline>
        ))}
        {stops.map((s) => (
          <CircleMarker
            key={s.id}
            center={[s.lat, s.lng]}
            radius={s.highlight ? 10 : 7}
            pathOptions={{ color: s.color || "#374151", fillColor: s.highlight ? "#facc15" : "#fff", fillOpacity: 1, weight: 3 }}
          >
            <Tooltip direction="top" offset={[0, -6]} permanent={Boolean(s.highlight)}>
              {s.name}{s.label ? ` · ${s.label}` : ""}
            </Tooltip>
          </CircleMarker>
        ))}
        {campus && <Marker position={[campus.lat, campus.lng]} icon={campusIcon} />}
        {buses.map((b) => (
          <Marker key={b.id} position={[b.lat, b.lng]} icon={busIcon(b.label, b.color, b.faded)} zIndexOffset={1000} />
        ))}
      </MapContainer>
    </div>
  );
}

// Real road path when available (from OSRM), otherwise straight lines between stops.
export function routeToLine(route, campus) {
  if (route.geometry?.length > 1) return route.geometry;
  return [...route.stops.map((s) => [s.lat, s.lng]), [campus.lat, campus.lng]];
}

const R = 6371000;
function metres(a, b) {
  const toRad = (d) => (d * Math.PI) / 180;
  const dLat = toRad(b[0] - a[0]), dLng = toRad(b[1] - a[1]);
  const h = Math.sin(dLat / 2) ** 2 + Math.cos(toRad(a[0])) * Math.cos(toRad(b[0])) * Math.sin(dLng / 2) ** 2;
  return 2 * R * Math.asin(Math.sqrt(h));
}

// Evenly spaced points along a polyline (every `stepM` metres) - used to simulate a bus driving the road.
export function samplePath(points, stepM = 250) {
  if (points.length < 2) return points;
  const out = [points[0]];
  let carry = 0;
  for (let i = 0; i < points.length - 1; i++) {
    const a = points[i], b = points[i + 1];
    const len = metres(a, b);
    let d = stepM - carry;
    while (d < len) {
      const t = d / len;
      out.push([a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t]);
      d += stepM;
    }
    carry = len - (d - stepM);
  }
  out.push(points[points.length - 1]);
  return out;
}

// Split a polyline at a distance along it: [travelled, remaining]
export function splitAt(points, distM) {
  if (distM == null || points.length < 2) return [[], points];
  let acc = 0;
  for (let i = 0; i < points.length - 1; i++) {
    const a = points[i], b = points[i + 1];
    const len = metres(a, b);
    if (acc + len >= distM) {
      const t = len === 0 ? 0 : (distM - acc) / len;
      const mid = [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t];
      return [[...points.slice(0, i + 1), mid], [mid, ...points.slice(i + 1)]];
    }
    acc += len;
  }
  return [points, [points[points.length - 1]]];
}

export function fmtMinutes(min) {
  if (min == null) return "";
  const m = Math.round(min);
  return m < 60 ? `~${m} min` : `~${Math.floor(m / 60)} h ${m % 60} min`;
}
