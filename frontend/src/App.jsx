import { useEffect, useState } from "react";
import { Navigate, Route, Routes, useNavigate } from "react-router-dom";
import { api, auth } from "./api.js";
import Login from "./pages/Login.jsx";
import Register from "./pages/Register.jsx";
import StudentHome from "./pages/StudentHome.jsx";
import AdminHome from "./pages/AdminHome.jsx";
import DriverHome from "./pages/DriverHome.jsx";

// Shows an "Install app" button when the browser offers to install the PWA (Android Chrome/Edge, desktop).
function useInstallPrompt() {
  const [evt, setEvt] = useState(null);
  useEffect(() => {
    const onPrompt = (e) => { e.preventDefault(); setEvt(e); };
    const onInstalled = () => setEvt(null);
    window.addEventListener("beforeinstallprompt", onPrompt);
    window.addEventListener("appinstalled", onInstalled);
    return () => { window.removeEventListener("beforeinstallprompt", onPrompt); window.removeEventListener("appinstalled", onInstalled); };
  }, []);
  const install = async () => { evt.prompt(); await evt.userChoice; setEvt(null); };
  return evt ? install : null;
}

export default function App() {
  const [me, setMe] = useState(null);
  const [loading, setLoading] = useState(Boolean(auth.token));
  const navigate = useNavigate();
  const install = useInstallPrompt();

  const loadMe = async () => {
    if (!auth.token) { setMe(null); setLoading(false); return; }
    try { setMe(await api("/me")); } catch { setMe(null); } finally { setLoading(false); }
  };

  useEffect(() => { loadMe(); }, []);

  const onLoggedIn = async () => { setLoading(true); await loadMe(); navigate("/"); };
  const logout = () => { auth.clear(); setMe(null); navigate("/login"); };

  if (loading) return <div className="center muted">Loading…</div>;

  const home = me?.role === "admin" ? <AdminHome me={me} />
    : me?.role === "driver" ? <DriverHome me={me} />
    : me ? <StudentHome me={me} /> : <Navigate to="/login" />;

  return (
    <>
      <header className="topbar">
        <div className="brand"><span className="logo">🚌</span> Smart Bus</div>
        <div className="topbar-right">
          {install && <button className="btn small" onClick={install}>📲 Install app</button>}
        {me && (
          <>
            <span className="muted hide-sm">{me.name} · {me.role}</span>
            <button className="btn ghost" onClick={logout}>Log out</button>
          </>
        )}
        </div>
      </header>
      <main className="container">
        <Routes>
          <Route path="/login" element={me ? <Navigate to="/" /> : <Login onLoggedIn={onLoggedIn} />} />
          <Route path="/register" element={me ? <Navigate to="/" /> : <Register onLoggedIn={onLoggedIn} />} />
          <Route path="/*" element={home} />
        </Routes>
      </main>
    </>
  );
}
