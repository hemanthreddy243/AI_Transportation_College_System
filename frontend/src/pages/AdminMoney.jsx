import { useEffect, useState } from "react";
import { api, fmtDate, fmtDateTime } from "../api.js";
import { rupees } from "../components/FeeCard.jsx";

const monthName = (ym) => new Date(`${ym}-01T00:00`).toLocaleDateString(undefined, { month: "long", year: "numeric" });

function SettingsForm({ onSaved }) {
  const [f, setF] = useState(null);
  const [msg, setMsg] = useState("");
  useEffect(() => { api("/admin/settings").then(setF); }, []);
  if (!f) return null;
  const set = (k) => (e) => setF({ ...f, [k]: e.target.value });
  const save = async (e) => {
    e.preventDefault(); setMsg("");
    try {
      const saved = await api("/admin/settings", {
        method: "PUT",
        body: {
          academic_year: f.academic_year, transport_fee: Number(f.transport_fee), diesel_price: Number(f.diesel_price),
          baseline_buses: f.baseline_buses === "" ? null : Number(f.baseline_buses), platform_fee_pct: Number(f.platform_fee_pct),
        },
      });
      setF(saved); setMsg("Saved. New values apply to trips planned from now on."); onSaved?.();
    } catch (err) { setMsg(err.message); }
  };
  return (
    <form className="form inline-form" onSubmit={save}>
      <label>Diesel ₹/litre<input type="number" step="0.5" min="1" value={f.diesel_price} onChange={set("diesel_price")} /></label>
      <label>Buses run daily before
        <input type="number" min="1" placeholder={`fleet: ${f.active_fleet}`} value={f.baseline_buses} onChange={set("baseline_buses")} />
      </label>
      <label>Platform fee % of savings<input type="number" min="0" max="100" step="0.5" value={f.platform_fee_pct} onChange={set("platform_fee_pct")} /></label>
      <label>Transport fee ₹/year<input type="number" min="1" value={f.transport_fee} onChange={set("transport_fee")} /></label>
      <label>Academic year<input value={f.academic_year} onChange={set("academic_year")} /></label>
      <button className="btn">Save settings</button>
      {msg && <div className="small muted" style={{ width: "100%" }}>{msg}</div>}
    </form>
  );
}

export function SavingsTab() {
  const [d, setD] = useState(null);
  const [error, setError] = useState("");
  const load = () => api("/admin/savings").then(setD).catch((e) => setError(e.message));
  useEffect(() => { load(); }, []);
  if (error) return <div className="alert error">{error}</div>;
  if (!d) return <p className="muted">Loading…</p>;
  const t = d.totals, s = d.settings;
  const maxMonth = Math.max(1, ...d.months.map((m) => m.rupees));

  const clearDemo = async () => { await api("/admin/savings/clear-demo", { method: "POST" }); load(); };

  return (
    <div className="stack">
      <section className="card">
        <div className="row between wrap">
          <h2>Savings</h2>
          <span className="muted small">vs. running {s.effective_baseline_buses} buses every day · diesel {rupees(s.diesel_price)}/L</span>
        </div>
        {t.demo_trips > 0 && (
          <div className="alert info small row between wrap">
            <span>Includes {t.demo_trips} days of <strong>demo history</strong> so this page isn't empty before a pilot.</span>
            <button className="btn small" onClick={clearDemo}>Clear demo history</button>
          </div>
        )}
        <div className="tiles">
          <div className="tile"><div className="tile-v">{rupees(t.rupees_saved)}</div><div className="tile-l">diesel cost saved</div></div>
          <div className="tile"><div className="tile-v">{t.litres_saved.toLocaleString("en-IN")} L</div><div className="tile-l">diesel saved · {t.km_saved.toLocaleString("en-IN")} km not driven</div></div>
          <div className="tile"><div className="tile-v">{t.trips}</div><div className="tile-l">trips planned · avg {t.avg_buses_used} buses</div></div>
          <div className="tile tile-accent"><div className="tile-v">{rupees(t.platform_fee)}</div><div className="tile-l">platform fee ({s.platform_fee_pct}% of savings)</div></div>
        </div>
        <p className="small muted">The college keeps {rupees(t.college_keeps)} of the savings. Savings are estimated from the planned road distances.</p>
      </section>

      <section className="card">
        <h3>By month</h3>
        <div className="table-wrap">
          <table>
            <thead><tr><th>Month</th><th>Trips</th><th>Diesel saved</th><th>Saved</th><th>Platform fee</th><th></th></tr></thead>
            <tbody>
              {d.months.map((m) => (
                <tr key={m.month}>
                  <td>{monthName(m.month)}</td><td>{m.trips}</td><td>{m.litres.toLocaleString("en-IN")} L</td>
                  <td>{rupees(m.rupees)}</td><td><strong>{rupees(m.platform_fee)}</strong></td>
                  <td style={{ width: "30%" }}><div className="bar-track"><div className="bar-fill" style={{ width: `${(100 * m.rupees) / maxMonth}%` }} /></div></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className="card">
        <h3>Trips</h3>
        <div className="table-wrap">
          <table>
            <thead><tr><th>Date</th><th>Riders</th><th>Buses</th><th>Road km</th><th>Diesel saved</th><th>Saved</th></tr></thead>
            <tbody>
              {d.trips.map((r) => (
                <tr key={r.id}>
                  <td>{fmtDate(r.trip_date)} {r.demo ? <span className="badge">demo</span> : null}</td>
                  <td>{r.riders}</td><td>{r.buses_used}/{r.baseline_buses}</td><td>{r.actual_km}</td>
                  <td>{r.litres_saved} L</td><td>{rupees(r.rupees_saved)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className="card">
        <h3>Settings</h3>
        <SettingsForm onSaved={load} />
      </section>
    </div>
  );
}

export function PaymentsTab() {
  const [d, setD] = useState(null);
  const [error, setError] = useState("");
  useEffect(() => {
    const load = () => api("/admin/payments").then(setD).catch((e) => setError(e.message));
    load();
    const id = setInterval(load, 15000);
    return () => clearInterval(id);
  }, []);
  if (error) return <div className="alert error">{error}</div>;
  if (!d) return <p className="muted">Loading…</p>;
  const pct = d.students_total ? Math.round((100 * d.paid_count) / d.students_total) : 0;
  return (
    <div className="stack">
      <section className="card">
        <div className="row between wrap">
          <h2>Transport fee · {d.academic_year}</h2>
          <span className={`badge ${d.gateway === "razorpay" && !d.test_mode ? "ok" : ""}`}>
            {d.gateway === "razorpay" ? (d.test_mode ? "Razorpay · test mode" : "Razorpay · live") : "demo gateway"}
          </span>
        </div>
        <div className="tiles">
          <div className="tile"><div className="tile-v">{d.paid_count}<span className="tile-sub">/{d.students_total}</span></div><div className="tile-l">students paid ({pct}%)</div></div>
          <div className="tile"><div className="tile-v">{rupees(d.online_amount)}</div><div className="tile-l">collected online · {d.online_count} payments</div></div>
          <div className="tile"><div className="tile-v">{d.pending_count}</div><div className="tile-l">students pending</div></div>
          <div className="tile"><div className="tile-v">{rupees(d.pending_amount)}</div><div className="tile-l">still to collect at {rupees(d.fee)}</div></div>
        </div>
        <div className="bar-track" title={`${pct}% paid`}><div className="bar-fill" style={{ width: `${pct}%` }} /></div>
        <p className="small muted">"Paid" includes fees paid at the accounts office (from college records) and online payments.</p>
      </section>
      <section className="card">
        <h3>Recent online payments</h3>
        {d.recent.length === 0 ? <p className="muted">No online payments yet.</p> : (
          <div className="table-wrap">
            <table>
              <thead><tr><th>When</th><th>Student</th><th>Amount</th><th>Method</th><th>Reference</th></tr></thead>
              <tbody>
                {d.recent.map((p) => (
                  <tr key={p.id}>
                    <td className="small">{fmtDateTime(p.created_at)}</td><td>{p.name} <span className="muted small">{p.username}</span></td>
                    <td>{rupees(p.amount)}</td><td>{p.method}</td><td><code>{p.reference}</code></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}
