import { useEffect, useRef, useState } from "react";
import { auth } from "./api.js";

function wsUrl(path) {
  const proto = window.location.protocol === "https:" ? "wss" : "ws";
  return `${proto}://${window.location.host}/api${path}?token=${encodeURIComponent(auth.token || "")}`;
}

/**
 * Subscribes to live bus updates over a WebSocket, reconnecting automatically.
 * path: "/ws/bus/3" or "/ws/fleet". Returns { byBus: {busId: liveStatus}, connected }.
 */
export function useLive(path) {
  const [byBus, setByBus] = useState({});
  const [connected, setConnected] = useState(false);
  const [, setTick] = useState(0);
  const retry = useRef(0);

  useEffect(() => {
    if (!path) return undefined;
    let ws, timer, ping, closed = false;
    const open = () => {
      ws = new WebSocket(wsUrl(path));
      ws.onopen = () => { setConnected(true); retry.current = 0; };
      ws.onmessage = (e) => {
        const msg = JSON.parse(e.data);
        if (msg.type === "bus") setByBus((prev) => ({ ...prev, [msg.data.bus_id]: { ...msg.data, received_at: Date.now() } }));
      };
      ws.onclose = (e) => {
        setConnected(false);
        if (closed || e.code === 4403) return;
        retry.current = Math.min(retry.current + 1, 5);
        timer = setTimeout(open, 1000 * 2 ** retry.current); // backoff: 2s, 4s ... 32s
      };
      ping = setInterval(() => ws.readyState === 1 && ws.send("ping"), 25000);
    };
    open();
    // re-render every 5 s so "updated 12s ago" stays current even without new messages
    const ticker = setInterval(() => setTick((t) => t + 1), 5000);
    return () => { closed = true; clearTimeout(timer); clearInterval(ping); clearInterval(ticker); ws?.close(); };
  }, [path]);

  return { byBus, connected };
}

/** Seconds since the bus's last GPS fix, counting time since we received it. */
export function ageSeconds(live) {
  if (!live?.location) return null;
  const extra = live.received_at ? (Date.now() - live.received_at) / 1000 : 0;
  return Math.round(live.location.age_s + extra);
}

export function fmtDistance(m) {
  if (m == null) return "";
  return m < 1000 ? `${Math.round(m / 10) * 10} m` : `${(m / 1000).toFixed(1)} km`;
}

export function fmtEta(min) {
  if (min == null) return "";
  if (min < 1) return "< 1 min";
  const m = Math.round(min);
  return m < 60 ? `${m} min` : `${Math.floor(m / 60)} h ${m % 60} min`;
}

export function clockIn(min) {
  if (min == null) return "";
  return new Date(Date.now() + min * 60000).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
}
