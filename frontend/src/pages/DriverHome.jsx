import { useEffect, useRef, useState } from "react";
import { api, fmtDate } from "../api.js";
import RouteMap, { fmtMinutes, routeToLine, samplePath, splitAt } from "../components/RouteMap.jsx";
import { fmtDistance, fmtEta } from "../live.js";

export default function DriverHome({ me }) {
  const [data, setData] = useState(null);
  const [mode, setMode] = useState("off"); // off | gps | sim
  const [pos, setPos] = useState(null);
  const [live, setLive] = useState(null);
  const [gpsInfo, setGpsInfo] = useState("");
  const [error, setError] = useState("");
  const watchId = useRef(null);
  const simTimer = useRef(null);
  const wakeLock = useRef(null);

  useEffect(() => { api("/driver/route").then(setData).catch((e) => setError(e.message)); }, []);

  const send = async (fix) => {
    setPos({ lat: fix.lat, lng: fix.lng });
    try {
      const res = await api("/driver/location", { method: "POST", body: fix });
      if (res.ignored) setGpsInfo(res.reason);
      else { setLive(res); setError(""); }
    } catch (e) { setError(e.message); }
  };

  const keepScreenOn = async () => {
    // Phones pause GPS when the screen turns off; a wake lock keeps it on during the trip.
    try { wakeLock.current = await navigator.wakeLock?.request("screen"); } catch { /* not supported */ }
  };

  const stop = () => {
    if (watchId.current !== null) navigator.geolocation.clearWatch(watchId.current);
    if (simTimer.current) clearInterval(simTimer.current);
    watchId.current = null; simTimer.current = null;
    wakeLock.current?.release?.().catch(() => {});
    wakeLock.current = null;
    setMode("off");
  };
  useEffect(() => stop, []);

  const startTrip = async () => {
    stop();
    setLive(await api("/driver/trip/start", { method: "POST" }));
    keepScreenOn();
  };

  const startGps = async () => {
    if (!navigator.geolocation) { setError("This device has no GPS / location support."); return; }
    if (!window.isSecureContext) { setError("Phones only share GPS over HTTPS. Open this page with https:// (see README)."); return; }
    await startTrip();
    setMode("gps");
    watchId.current = navigator.geolocation.watchPosition(
      (p) => {
        setGpsInfo(`GPS accuracy ±${Math.round(p.coords.accuracy)} m`);
        send({
          lat: p.coords.latitude, lng: p.coords.longitude,
          heading: p.coords.heading ?? undefined, accuracy_m: p.coords.accuracy,
        });
      },
      (e) => { setError(`Location error: ${e.message}. Allow location access for this site.`); stop(); },
      { enableHighAccuracy: true, maximumAge: 3000, timeout: 20000 }
    );
  };

  const startSim = async () => {
    await startTrip();
    // Drive along the real road path, one point every 250 m (~every 1.5 s)
    const path = samplePath(routeToLine(data.route, data.campus), 250);
    let i = 0;
    setMode("sim");
    send({ lat: path[0][0], lng: path[0][1] });
    simTimer.current = setInterval(() => {
      i += 1;
      if (i >= path.length) { stop(); return; }
      send({ lat: path[i][0], lng: path[i][1] });
    }, 1500);
  };

  const route = data?.route;
  const line = route ? routeToLine(route, data.campus) : [];
  const [done, todo] = live?.progress_m != null ? splitAt(line, live.progress_m) : [[], line];
  const next = live?.next_stop_index != null ? live.stops[live.next_stop_index] : null;

  return (
    <div className="stack">
      <section className="card">
        <div className="muted small">Driver</div>
        <h2>{me.name} · Bus {me.bus?.number}</h2>
        {!data && !error && <p className="muted">Loading…</p>}
        {data && !route && <p className="muted">No route assigned to your bus for the next trip.</p>}
        {route && (
          <>
            <p>Trip on <strong>{fmtDate(data.trip_date)}</strong> · {route.load}/{route.capacity} students · {route.km} km {route.minutes != null && `· ${fmtMinutes(route.minutes)} drive`}</p>
            {mode !== "off" && live && (
              <div className="live-banner tone-live">
                <div>
                  <div className="live-title">
                    {live.state === "arrived" ? "Arrived at campus" : next ? `Next: ${next.name}` : "Heading to campus"}
                  </div>
                  <div className="live-sub">
                    {next && next.status === "at_stop" ? `Boarding ${route.stops.find((s) => s.id === next.id)?.pickup ?? ""} students`
                      : next ? `${fmtDistance(next.distance_m)} · ${fmtEta(next.eta_min)}` : ""}
                    {live.state !== "arrived" && ` · campus in ${fmtEta(live.campus_eta_min)}`}
                    {live.off_route && " · ⚠ off planned route"}
                  </div>
                </div>
              </div>
            )}
            <ol className="stop-list">
              {route.stops.map((s, i) => (
                <li key={s.id} className={live?.stops?.[i]?.status === "passed" ? "muted" : ""}>
                  {s.name} <span className="muted">— pick up {s.pickup}</span>
                  {live?.stops?.[i]?.status === "passed" && " ✓"}
                </li>
              ))}
              <li className="muted">{data.campus.name}</li>
            </ol>
            <div className="row wrap">
              {mode === "off" ? (
                <>
                  <button className="btn primary" onClick={startGps}>▶ Start trip (share GPS)</button>
                  <button className="btn" onClick={startSim}>Simulate drive (demo)</button>
                </>
              ) : (
                <button className="btn danger" onClick={stop}>■ Stop sharing ({mode === "gps" ? "GPS" : "simulation"})</button>
              )}
            </div>
            {mode !== "off" && <p className="small muted">Students on this bus see your live location. Keep this page open and the screen on. {gpsInfo}</p>}
          </>
        )}
        {error && <div className="alert error">{error}</div>}
      </section>
      {route && (
        <RouteMap
          fit={line}
          stops={route.stops.map((s) => ({ ...s, label: `${s.pickup} students`, color: "#2563eb" }))}
          routes={[{ color: "#9ca3af", points: done }, { color: "#2563eb", points: todo }]}
          campus={data.campus}
          buses={pos ? [{ id: "me", ...pos, label: me.bus?.number, color: "#2563eb" }] : []}
          height={420}
        />
      )}
    </div>
  );
}
