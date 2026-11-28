import { useEffect, useState } from "react";
import { api, fmtDate, fmtDateTime, timeAgo } from "../api.js";
import Markdown from "../components/Markdown.jsx";
import { PaymentsTab, SavingsTab } from "./AdminMoney.jsx";
import RouteMap, { ROUTE_COLORS, fmtMinutes, routeToLine } from "../components/RouteMap.jsx";
import { ageSeconds, fmtEta, useLive } from "../live.js";

function liveLine(l) {
  if (!l || l.state === "not_started" || l.state === "no_route") return { text: "not started", cls: "" };
  if (l.state === "arrived") return { text: "arrived at campus", cls: "ok" };
  const next = l.next_stop_index != null ? l.stops[l.next_stop_index] : null;
  const where = next ? (next.status === "at_stop" ? `at ${next.name}` : `→ ${next.name} ${fmtEta(next.eta_min)}`) : "→ campus";
  const stale = l.state === "stale" || ageSeconds(l) > 90;
  return {
    text: `${where} · campus ${fmtEta(l.campus_eta_min)}${l.speed_kmh != null ? ` · ${Math.round(l.speed_kmh)} km/h` : ""}${l.off_route ? " · OFF ROUTE" : ""}${stale ? " · signal lost" : ""}`,
    cls: l.off_route || stale ? "warn" : "live",
  };
}

const pad = (n) => String(n).padStart(2, "0");
const localInput = (d) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;

function NewPollForm({ onCreated }) {
  const tomorrow = new Date(Date.now() + 86400000);
  const today18 = new Date(); today18.setHours(18, 0, 0, 0);
  const today21 = new Date(); today21.setHours(21, 0, 0, 0);
  const [f, setF] = useState({
    trip_date: localInput(tomorrow).slice(0, 10), opens_at: localInput(today18), closes_at: localInput(today21),
  });
  const [error, setError] = useState("");
  const set = (k) => (e) => setF({ ...f, [k]: e.target.value });
  const submit = async (e) => {
    e.preventDefault(); setError("");
    try { await api("/admin/polls", { method: "POST", body: f }); onCreated(); }
    catch (err) { setError(err.message); }
  };
  return (
    <form className="form inline-form" onSubmit={submit}>
      <label>Trip date<input type="date" value={f.trip_date} onChange={set("trip_date")} required /></label>
      <label>Voting opens<input type="datetime-local" value={f.opens_at} onChange={set("opens_at")} required /></label>
      <label>Voting closes<input type="datetime-local" value={f.closes_at} onChange={set("closes_at")} required /></label>
      <button className="btn primary">Schedule voting</button>
      {error && <div className="alert error">{error}</div>}
    </form>
  );
}

function Buses({ buses, reload }) {
  const [f, setF] = useState({ number: "", capacity: 50 });
  const [error, setError] = useState("");
  const add = async (e) => {
    e.preventDefault(); setError("");
    try { await api("/admin/buses", { method: "POST", body: { ...f, capacity: Number(f.capacity) } }); setF({ number: "", capacity: 50 }); reload(); }
    catch (err) { setError(err.message); }
  };
  const toggle = async (id) => { await api(`/admin/buses/${id}/toggle`, { method: "POST" }); reload(); };
  return (
    <section className="card">
      <h3>Fleet</h3>
      <div className="table-wrap">
        <table>
          <thead><tr><th>Bus</th><th>Seats</th><th>Driver</th><th>Last location</th><th>Status</th></tr></thead>
          <tbody>
            {buses.map((b) => (
              <tr key={b.id} className={b.active ? "" : "dim"}>
                <td>{b.number}</td><td>{b.capacity}</td><td>{b.driver ?? "—"}</td>
                <td className="muted small">{b.location ? timeAgo(b.location.updated_at) : "—"}</td>
                <td><button className="btn small" onClick={() => toggle(b.id)}>{b.active ? "Active" : "Off-duty"}</button></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <form className="form inline-form" onSubmit={add}>
        <label>Bus number<input value={f.number} onChange={(e) => setF({ ...f, number: e.target.value })} required /></label>
        <label>Seats<input type="number" min="1" max="120" value={f.capacity} onChange={(e) => setF({ ...f, capacity: e.target.value })} required /></label>
        <button className="btn">Add bus</button>
        {error && <div className="alert error">{error}</div>}
      </form>
    </section>
  );
}

export default function AdminHome() {
  const [polls, setPolls] = useState([]);
  const [pollId, setPollId] = useState(null);
  const [counts, setCounts] = useState(null);
  const [plan, setPlan] = useState(null);
  const [buses, setBuses] = useState([]);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [showNew, setShowNew] = useState(false);
  const [tab, setTab] = useState("trips");
  const { byBus: fleetLive, connected } = useLive("/ws/fleet");

  const loadPolls = async () => {
    const p = await api("/admin/polls");
    setPolls(p);
    setPollId((cur) => cur ?? p[0]?.id ?? null);
  };
  const loadBuses = () => api("/admin/buses").then(setBuses);
  const loadPoll = async (id) => {
    if (!id) return;
    const [c, p] = await Promise.all([api(`/admin/polls/${id}/counts`), api(`/admin/polls/${id}/plan`)]);
    setCounts(c); setPlan(p.plan);
  };

  useEffect(() => { loadPolls().catch((e) => setError(e.message)); loadBuses(); }, []);
  useEffect(() => {
    loadPoll(pollId).catch((e) => setError(e.message));
    const id = setInterval(() => { loadPoll(pollId).catch(() => {}); loadBuses().catch(() => {}); }, 10000);
    return () => clearInterval(id);
  }, [pollId]);

  const act = async (label, fn) => {
    setBusy(label); setError("");
    try { await fn(); await Promise.all([loadPolls(), loadPoll(pollId)]); }
    catch (e) { setError(e.message); } finally { setBusy(""); }
  };

  const poll = counts?.poll;
  const maxYes = Math.max(1, ...(counts?.stops ?? []).map((s) => s.yes));
  const liveBuses = plan
    ? plan.routes.map((r, i) => {
        const l = fleetLive[r.bus_id];
        const running = l && ["live", "stale", "arrived"].includes(l.state) && l.location;
        return running ? { id: r.bus_id, lat: l.location.lat, lng: l.location.lng, label: r.bus_number,
                           color: ROUTE_COLORS[i % ROUTE_COLORS.length], faded: l.state === "stale" } : null;
      }).filter(Boolean)
    : [];
  const fleetStates = plan ? plan.routes.map((r) => fleetLive[r.bus_id]) : [];
  const countState = (f) => fleetStates.filter(f).length;

  const TABS = [["trips", "🗺 Trips"], ["savings", "💰 Savings"], ["payments", "🧾 Payments"], ["fleet", "🚌 Fleet"]];
  return (
    <div className="stack">
      <nav className="tabs">
        {TABS.map(([id, label]) => (
          <button key={id} className={`tab ${tab === id ? "active" : ""}`} onClick={() => setTab(id)}>{label}</button>
        ))}
      </nav>
      {tab === "savings" && <SavingsTab />}
      {tab === "payments" && <PaymentsTab />}
      {tab === "fleet" && <Buses buses={buses} reload={loadBuses} />}
      {tab === "trips" && (<>
      <section className="card">
        <div className="row between wrap">
          <h2>Trip planning</h2>
          <div className="row wrap">
            <select value={pollId ?? ""} onChange={(e) => setPollId(Number(e.target.value))}>
              {polls.map((p) => <option key={p.id} value={p.id}>{fmtDate(p.trip_date)} · {p.status}</option>)}
            </select>
            <button className="btn" onClick={() => setShowNew(!showNew)}>{showNew ? "Cancel" : "+ New voting window"}</button>
          </div>
        </div>
        {showNew && <NewPollForm onCreated={async () => { setShowNew(false); const p = await api("/admin/polls"); setPolls(p); setPollId(p[0].id); }} />}
        {poll && (
          <>
            <p>
              Trip <strong>{fmtDate(poll.trip_date)}</strong>
              <span className={`badge status-${poll.status}`}>{poll.status}</span>
              <span className="muted small"> · voting {fmtDateTime(poll.opens_at)} – {fmtDateTime(poll.closes_at)}</span>
            </p>
            <div className="tiles">
              <div className="tile"><div className="tile-v">{counts.total_yes}</div><div className="tile-l">said Yes</div></div>
              <div className="tile"><div className="tile-v">{counts.total_no}</div><div className="tile-l">said No</div></div>
              <div className="tile"><div className="tile-v">{counts.registered_students - counts.total_yes - counts.total_no}</div><div className="tile-l">not voted</div></div>
              <div className="tile"><div className="tile-v">{buses.filter((b) => b.active).reduce((a, b) => a + b.capacity, 0)}</div><div className="tile-l">seats in active fleet</div></div>
            </div>
            <div className="row wrap">
              <button className="btn" disabled={!!busy} onClick={() => act("sim", () => api(`/admin/polls/${pollId}/simulate-votes`, { method: "POST", body: { turnout: 0.65 } }))}>
                {busy === "sim" ? "…" : "Simulate student votes (demo)"}
              </button>
              {(poll.status === "open" || poll.status === "scheduled") && (
                <button className="btn" disabled={!!busy} onClick={() => act("close", () => api(`/admin/polls/${pollId}/close`, { method: "POST" }))}>
                  Close voting now
                </button>
              )}
              <button className="btn primary" disabled={!!busy || poll.status === "open" || poll.status === "scheduled"}
                onClick={() => act("plan", () => api(`/admin/polls/${pollId}/plan`, { method: "POST" }))}>
                {busy === "plan" ? "Agent is planning routes…" : plan ? "Re-plan routes" : "Plan routes & assign buses"}
              </button>
            </div>
            {(poll.status === "open" || poll.status === "scheduled") && <p className="muted small">Close voting to plan routes.</p>}
          </>
        )}
        {error && <div className="alert error">{error}</div>}
      </section>

      {counts && (
        <section className="card">
          <h3>Students per stop</h3>
          <div className="bars">
            {counts.stops.map((s) => (
              <div className="bar-row" key={s.id}>
                <div className="bar-label">{s.name}</div>
                <div className="bar-track"><div className="bar-fill" style={{ width: `${(100 * s.yes) / maxYes}%` }} /></div>
                <div className="bar-value">{s.yes}</div>
              </div>
            ))}
          </div>
        </section>
      )}

      {plan && (
        <>
          <section className="card">
            <div className="row between wrap">
              <h3>Bus plan</h3>
              <span className="muted small">
                solver: {plan.solver} · distances: {plan.distance_source === "osrm" ? "real roads (OSRM)" : "straight-line estimate"} · {fmtDateTime(plan.created_at)}
              </span>
            </div>
            <div className="tiles">
              <div className="tile"><div className="tile-v">{plan.buses_used}<span className="tile-sub">/{plan.fleet_size}</span></div><div className="tile-l">buses needed</div></div>
              <div className="tile"><div className="tile-v">{plan.riders}</div><div className="tile-l">riders seated</div></div>
              <div className="tile"><div className="tile-v">{plan.total_km}</div><div className="tile-l">total km</div></div>
              <div className="tile"><div className="tile-v">~{plan.est_saving_litres} L</div><div className="tile-l">diesel saved (est.)</div></div>
            </div>
            <div className="row wrap small" style={{ margin: "4px 0 8px" }}>
              <span className={`conn ${connected ? "on" : ""}`}>{connected ? "● live tracking" : "○ connecting…"}</span>
              <span className="badge">{countState((l) => l?.state === "live")} on the road</span>
              <span className="badge ok">{countState((l) => l?.state === "arrived")} arrived</span>
              <span className="badge warn">{countState((l) => l?.off_route || l?.state === "stale")} need attention</span>
              <span className="badge">{countState((l) => !l || l.state === "not_started")} not started</span>
            </div>
            {Object.keys(plan.unserved).length > 0 && (
              <div className="alert error">
                Not enough seats: {Object.entries(plan.unserved).map(([k, v]) => `${k} (${v})`).join(", ")}. Add or activate buses and re-plan.
              </div>
            )}
            <RouteMap
              routes={plan.routes.map((r, i) => ({ color: ROUTE_COLORS[i % ROUTE_COLORS.length], points: routeToLine(r, plan.campus), label: `${r.bus_number}: ${r.load}/${r.capacity}` }))}
              stops={plan.routes.flatMap((r, i) => r.stops.map((s) => ({ ...s, id: `${r.bus_id}-${s.id}`, label: `${s.pickup} → ${r.bus_number}`, color: ROUTE_COLORS[i % ROUTE_COLORS.length] })))}
              campus={plan.campus}
              buses={liveBuses}
              height={460}
            />
            <div className="route-grid">
              {plan.routes.map((r, i) => {
                const pct = Math.round((100 * r.load) / r.capacity);
                return (
                  <div className="route-card" key={r.bus_id} style={{ borderLeftColor: ROUTE_COLORS[i % ROUTE_COLORS.length] }}>
                    <div className="row between"><strong>{r.bus_number}</strong><span className={`badge ${pct > 90 ? "warn" : "ok"}`}>{r.load}/{r.capacity} · {pct}%</span></div>
                    <div className="small">{r.stops.map((s) => `${s.name} (${s.pickup})`).join(" → ")} → Campus</div>
                    <div className="muted small">{r.km} km road{r.minutes != null && ` · ${fmtMinutes(r.minutes)}`}</div>
                    {(() => { const ll = liveLine(fleetLive[r.bus_id]); return <div className={`live-mini ${ll.cls}`}>🚌 {ll.text}</div>; })()}
                  </div>
                );
              })}
            </div>
          </section>
          <section className="card ai">
            <h3>🤖 AI briefing</h3>
            <Markdown text={plan.ai_summary || ""} />
          </section>
        </>
      )}

      </>)}
    </div>
  );
}
