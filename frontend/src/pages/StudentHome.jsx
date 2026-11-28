import { useEffect, useRef, useState } from "react";
import { api, fmtDate, fmtDateTime } from "../api.js";
import RouteMap, { fmtMinutes, routeToLine, splitAt } from "../components/RouteMap.jsx";
import { ageSeconds, clockIn, fmtDistance, fmtEta, useLive } from "../live.js";
import FeeCard from "../components/FeeCard.jsx";

function useInterval(fn, ms, deps = []) {
  useEffect(() => {
    fn();
    const id = setInterval(fn, ms);
    return () => clearInterval(id);
  }, deps); // eslint-disable-line react-hooks/exhaustive-deps
}

function fmtAge(s) {
  if (s == null) return "";
  if (s < 60) return `${s}s ago`;
  return `${Math.round(s / 60)} min ago`;
}

/** The one-line answer to "where is my bus?" */
function liveHeadline(live, myStopId) {
  if (!live || live.state === "not_started" || live.state === "no_route")
    return { tone: "idle", title: "Bus hasn't started yet", sub: "You'll see it here as soon as the driver starts the trip." };
  const age = ageSeconds(live);
  const mine = live.stops.find((s) => s.id === myStopId);
  if (live.state === "arrived") return { tone: "done", title: "Bus has reached campus", sub: "" };
  let res;
  if (!mine) res = { tone: "live", title: `Campus in ${fmtEta(live.campus_eta_min)}`, sub: "" };
  else if (mine.status === "passed") res = { tone: "warn", title: "Bus has passed your stop", sub: `Reaches campus in ${fmtEta(live.campus_eta_min)}` };
  else if (mine.status === "at_stop") res = { tone: "now", title: "Bus is at your stop now!", sub: "Board now" };
  else res = {
    tone: mine.eta_min <= 5 ? "now" : "live",
    title: `Arriving in ${fmtEta(mine.eta_min)}`,
    sub: `${fmtDistance(mine.distance_m)} away by road · expected around ${clockIn(mine.eta_min)}`,
  };
  if (live.state === "stale" || age > 90) {
    res.tone = "warn";
    res.sub = `GPS signal lost · last seen ${fmtAge(age)}. Estimate may be off.`;
  }
  return res;
}

export default function StudentHome({ me }) {
  const [pollData, setPollData] = useState(null);
  const [bus, setBus] = useState(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [notify, setNotify] = useState(false);
  const [feePaid, setFeePaid] = useState(me.fee_paid);
  const notified = useRef(false);

  const loadPoll = () => api("/polls/current").then(setPollData).catch((e) => setError(e.message));
  const loadBus = () => api("/me/bus").then((b) => {
    if (b.live) b.live.received_at = Date.now();
    setBus(b);
  }).catch(() => {});
  useInterval(loadPoll, 30000);
  useInterval(loadBus, 60000);

  const busId = bus?.assigned ? bus.route.bus_id : null;
  const { byBus, connected } = useLive(busId ? `/ws/bus/${busId}` : null);
  const live = busId ? byBus[busId] || bus.live : null;
  const mine = live?.stops?.find((s) => s.id === me.stop?.id);

  // "Notify me" when the bus is ~5 minutes from my stop
  useEffect(() => {
    if (!notify || notified.current || !mine || mine.status !== "upcoming" || mine.eta_min > 5) return;
    notified.current = true;
    try {
      new Notification(`Bus ${bus.route.bus_number} is ~${Math.max(1, Math.round(mine.eta_min))} min away`, {
        body: `Head to ${me.stop.name} now.`,
      });
    } catch { /* notifications unavailable */ }
  }, [notify, mine?.eta_min]); // eslint-disable-line react-hooks/exhaustive-deps

  const enableNotify = async () => {
    if (!("Notification" in window)) { setError("This browser doesn't support notifications."); return; }
    const perm = await Notification.requestPermission();
    if (perm === "granted") { notified.current = false; setNotify(true); }
    else setError("Notifications were blocked. Allow them in your browser settings.");
  };

  const vote = async (going) => {
    setBusy(true); setError("");
    try {
      await api(`/polls/${pollData.poll.id}/vote`, { method: "POST", body: { going } });
      await loadPoll();
    } catch (e) { setError(e.message); } finally { setBusy(false); }
  };

  const poll = pollData?.poll;
  const myVote = pollData?.my_vote;
  const head = bus?.assigned ? liveHeadline(live, me.stop?.id) : null;
  const line = bus?.assigned ? routeToLine(bus.route, bus.campus) : [];
  const running = live && ["live", "stale", "arrived"].includes(live.state);
  const [done, todo] = running ? splitAt(line, live.progress_m) : [[], line];
  const nextIdx = live?.next_stop_index;

  return (
    <div className="stack">
      <section className="card profile">
        <div>
          <div className="muted small">Welcome</div>
          <h2>{me.name}</h2>
          <div className="muted">{me.username}</div>
        </div>
        <div className="profile-meta">
          <div><span className="muted small">Your stop</span><br /><strong>{me.stop?.name ?? "—"}</strong></div>
          <div><span className="muted small">Transport fee</span><br />
            <span className={`badge ${feePaid ? "ok" : "bad"}`}>{feePaid ? "Paid" : "Pending"}</span>
          </div>
        </div>
      </section>

      {!feePaid && <FeeCard me={me} onPaid={() => { setFeePaid(true); loadPoll(); }} />}

      {bus?.assigned && (
        <section className="card">
          <div className="row between wrap">
            <h3>Where is my bus?</h3>
            <span className={`conn ${connected ? "on" : ""}`}>{connected ? "● live" : "○ connecting…"}</span>
          </div>
          <div className={`live-banner tone-${head.tone}`}>
            <div className="bus-number">{bus.route.bus_number}</div>
            <div>
              <div className="live-title">{head.title}</div>
              {head.sub && <div className="live-sub">{head.sub}</div>}
            </div>
          </div>

          {running && live.off_route && (
            <div className="alert info">The bus is taking a different road than planned (diversion or traffic). ETA is approximate.</div>
          )}

          <ol className="timeline">
            {(live?.stops?.length ? live.stops : bus.route.stops.map((s) => ({ ...s, status: "upcoming" }))).map((s, i) => {
              const isMine = s.id === me.stop?.id;
              const pickup = bus.route.stops.find((x) => x.id === s.id)?.pickup;
              return (
                <li key={s.id} className={`tl-${s.status} ${isMine ? "mine" : ""} ${running && i === nextIdx ? "next" : ""}`}>
                  <span className="tl-dot" />
                  <span className="tl-name">{s.name} {isMine && <span className="badge ok">your stop</span>}</span>
                  <span className="tl-eta muted small">
                    {s.status === "passed" ? "passed ✓" : s.status === "at_stop" ? "bus here now"
                      : running && s.eta_min != null ? `${fmtEta(s.eta_min)} · ${clockIn(s.eta_min)}` : `${pickup ?? ""} boarding`}
                  </span>
                </li>
              );
            })}
            <li className={`tl-${live?.state === "arrived" ? "passed" : "upcoming"}`}>
              <span className="tl-dot" />
              <span className="tl-name">{bus.campus.name}</span>
              <span className="tl-eta muted small">
                {running && live.state !== "arrived" ? `${fmtEta(live.campus_eta_min)} · ${clockIn(live.campus_eta_min)}`
                  : live?.state === "arrived" ? "arrived ✓" : fmtMinutes(bus.route.minutes)}
              </span>
            </li>
          </ol>

          <RouteMap
            fit={line}
            stops={bus.route.stops.map((s) => ({ ...s, highlight: s.id === me.stop?.id, color: "#2563eb" }))}
            routes={[
              { color: "#9ca3af", points: done, opacity: 0.9 },
              { color: "#2563eb", points: todo },
            ]}
            campus={bus.campus}
            buses={running && live.location ? [{
              id: busId, lat: live.location.lat, lng: live.location.lng, label: bus.route.bus_number,
              color: "#2563eb", faded: live.state === "stale",
            }] : []}
          />
          <div className="row between wrap small muted" style={{ marginTop: 8 }}>
            <span>
              {running && live.speed_kmh != null && `${Math.round(live.speed_kmh)} km/h · `}
              {running && live.location && `updated ${fmtAge(ageSeconds(live))}`}
            </span>
            {!notify ? <button className="btn small" onClick={enableNotify}>🔔 Alert me 5 min before</button>
              : <span>🔔 You'll get an alert 5 min before the bus arrives</span>}
          </div>
        </section>
      )}

      <section className="card">
        <h3>Will you take the bus?</h3>
        {!poll && <p className="muted">No trip is scheduled yet.</p>}
        {poll && (
          <>
            <p>
              Trip on <strong>{fmtDate(poll.trip_date)}</strong> from <strong>{me.stop?.name}</strong>
              <span className={`badge status-${poll.status}`}>{poll.status}</span>
            </p>
            <p className="muted small">Voting window: {fmtDateTime(poll.opens_at)} – {fmtDateTime(poll.closes_at)}</p>
            {poll.status === "open" ? (
              <div className="vote-row">
                <button className={`btn vote yes ${myVote?.going === 1 ? "selected" : ""}`} disabled={busy} onClick={() => vote(true)}>
                  ✅ Yes, I'm coming
                </button>
                <button className={`btn vote no ${myVote?.going === 0 ? "selected" : ""}`} disabled={busy} onClick={() => vote(false)}>
                  ❌ Not tomorrow
                </button>
              </div>
            ) : poll.status === "scheduled" ? (
              <div className="alert info">Voting has not opened yet. Come back at {fmtDateTime(poll.opens_at)}.</div>
            ) : (
              <div className="alert info">Voting is closed.</div>
            )}
            {myVote && (
              <p className="small">
                Your answer: <strong>{myVote.going ? "Yes" : "No"}</strong>
                <span className="muted"> · {fmtDateTime(myVote.voted_at)}</span>
                {poll.status === "open" && <span className="muted"> · you can change it until voting closes</span>}
              </p>
            )}
          </>
        )}
        {error && <div className="alert error">{error}</div>}
      </section>

      {feePaid && <FeeCard me={me} />}

      {bus && !bus.assigned && (
        <section className="card">
          <h3>Your bus</h3>
          <p className="muted">{bus.reason}</p>
        </section>
      )}
    </div>
  );
}
