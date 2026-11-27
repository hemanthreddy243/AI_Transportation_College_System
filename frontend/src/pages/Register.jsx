import { useState } from "react";
import { Link } from "react-router-dom";
import { api, auth } from "../api.js";

export default function Register({ onLoggedIn }) {
  const [form, setForm] = useState({ student_id: "", name: "", password: "", confirm: "" });
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const set = (k) => (e) => setForm({ ...form, [k]: e.target.value });

  const submit = async (e) => {
    e.preventDefault();
    setError("");
    if (form.password !== form.confirm) { setError("Passwords do not match"); return; }
    setBusy(true);
    try {
      const { token } = await api("/auth/register", {
        method: "POST",
        body: { student_id: form.student_id, name: form.name, password: form.password },
      });
      auth.set(token);
      await onLoggedIn();
    } catch (err) { setError(err.message); } finally { setBusy(false); }
  };

  return (
    <div className="auth-card card">
      <h1>Student registration</h1>
      <p className="muted">
        We verify your Student ID, name and transport fee status against college records.
        Your bus stop comes from your college record.
      </p>
      <form onSubmit={submit} className="form">
        <label>Student ID
          <input value={form.student_id} onChange={set("student_id")} placeholder="e.g. 22B81A05001" required />
        </label>
        <label>Full name (as in college records)
          <input value={form.name} onChange={set("name")} required />
        </label>
        <label>Password
          <input type="password" minLength={6} value={form.password} onChange={set("password")} required />
        </label>
        <label>Confirm password
          <input type="password" minLength={6} value={form.confirm} onChange={set("confirm")} required />
        </label>
        {error && <div className="alert error">{error}</div>}
        <button className="btn primary" disabled={busy}>{busy ? "Verifying…" : "Register"}</button>
      </form>
      <p className="muted small">Already registered? <Link to="/login">Log in</Link></p>
    </div>
  );
}
