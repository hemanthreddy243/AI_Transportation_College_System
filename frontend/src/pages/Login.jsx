import { useState } from "react";
import { Link } from "react-router-dom";
import { api, auth } from "../api.js";

export default function Login({ onLoggedIn }) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async (e) => {
    e.preventDefault();
    setError(""); setBusy(true);
    try {
      const { token } = await api("/auth/login", { method: "POST", body: { username, password } });
      auth.set(token);
      await onLoggedIn();
    } catch (err) { setError(err.message); } finally { setBusy(false); }
  };

  return (
    <div className="auth-card card">
      <h1>Log in</h1>
      <p className="muted">Students use their college Student ID.</p>
      <form onSubmit={submit} className="form">
        <label>Student ID / Username
          <input value={username} onChange={(e) => setUsername(e.target.value)} autoFocus required />
        </label>
        <label>Password
          <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} required />
        </label>
        {error && <div className="alert error">{error}</div>}
        <button className="btn primary" disabled={busy}>{busy ? "Logging in…" : "Log in"}</button>
      </form>
      <p className="muted small">New student? <Link to="/register">Register with your Student ID</Link></p>
      <p className="small muted"><a href="/privacy.html">Privacy policy</a></p>
      <details className="small muted">
        <summary>Demo accounts</summary>
        admin / admin123 · driver1 … driver10 / driver123 · pre-registered students / student123
      </details>
    </div>
  );
}
