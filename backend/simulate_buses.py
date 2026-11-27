"""Realistic GPS simulator: drives every planned bus along its real road route.

It behaves like the driver app on a phone - logs in as each bus's driver, presses "start trip",
and posts GPS fixes - so it tests the real pipeline end to end (tracking, ETAs, WebSockets).

Realism:
  * speed varies with traffic (free-flow 30-45 km/h, jams 3-12 km/h, random signals)
  * the bus stops at every pickup stop to board students (dwell time)
  * GPS jitter (a few metres of noise) and occasional signal dropouts
  * buses start a little apart, like real departures
  * optional detour on one bus to test the off-route alert
  * --speedup runs the trip faster than real time so you can watch a whole trip in minutes
    (speeds and ETAs are reported in simulated time, e.g. "12 min" = 12 simulated minutes)

Usage (server running, routes planned):
    python simulate_buses.py                       # all buses, 10x speed
    python simulate_buses.py --speedup 1           # real time (a real trip takes ~1 hour)
    python simulate_buses.py --buses 2,5 --detour 5 --dropout 0.05 --noise 15
"""
from __future__ import annotations

import argparse
import math
import random
import sys
import threading
import time

import httpx

API = "http://localhost:8000/api"
DEG_LAT_M = 110_540.0


def metres(a, b):
    lat0 = math.radians((a[0] + b[0]) / 2)
    return math.hypot((b[0] - a[0]) * DEG_LAT_M, (b[1] - a[1]) * 111_320.0 * math.cos(lat0))


def bearing(a, b):
    y = math.sin(math.radians(b[1] - a[1])) * math.cos(math.radians(b[0]))
    x = (math.cos(math.radians(a[0])) * math.sin(math.radians(b[0]))
         - math.sin(math.radians(a[0])) * math.cos(math.radians(b[0])) * math.cos(math.radians(b[1] - a[1])))
    return (math.degrees(math.atan2(y, x)) + 360) % 360


class Path:
    def __init__(self, pts):
        self.pts = pts
        self.cum = [0.0]
        for a, b in zip(pts, pts[1:]):
            self.cum.append(self.cum[-1] + metres(a, b))
        self.total = self.cum[-1]

    def at(self, d):
        """(lat, lng, heading) at distance d along the path."""
        d = max(0.0, min(d, self.total))
        lo, hi = 0, len(self.cum) - 1
        while lo < hi - 1:
            mid = (lo + hi) // 2
            if self.cum[mid] <= d:
                lo = mid
            else:
                hi = mid
        a, b = self.pts[lo], self.pts[hi]
        seg = self.cum[hi] - self.cum[lo]
        t = 0 if seg == 0 else (d - self.cum[lo]) / seg
        return a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, bearing(a, b)

    def nearest_along(self, p):
        best, best_d = 0.0, float("inf")
        for i, q in enumerate(self.pts):
            dd = metres(p, q)
            if dd < best_d:
                best, best_d = self.cum[i], dd
        return best


def login(c, user, pw):
    r = c.post("/auth/login", json={"username": user, "password": pw})
    r.raise_for_status()
    return {"Authorization": "Bearer " + r.json()["token"]}


def drive(bus, args, stop_flag, rng):
    number, headers, path, stop_marks = bus["number"], bus["headers"], bus["path"], bus["stops"]
    c = httpx.Client(base_url=API, timeout=15)
    time.sleep(bus["delay"])
    c.post("/driver/trip/start", headers=headers)
    print(f"[{number}] trip started: {path.total / 1000:.1f} km, {len(stop_marks)} stops", flush=True)

    d, sim_t = 0.0, 0.0
    speed = rng.uniform(25, 35) / 3.6  # m/s
    jam_until, next_stop = -1.0, 0
    dwell_until = -1.0
    detour = None
    if args.detour == bus["bus_id"]:
        start = path.total * 0.35
        detour = (start, start + 1500)  # 1.5 km stretch shifted ~400 m off the road
    tick = args.tick
    while d < path.total and not stop_flag.is_set():
        step = tick * args.speedup  # simulated seconds this tick
        sim_t += step
        if sim_t < dwell_until:
            pass  # boarding
        else:
            # traffic: occasionally enter a jam, otherwise drift around a free-flow speed
            if sim_t > jam_until and rng.random() < 0.02 * step / 10:
                jam_until = sim_t + rng.uniform(60, 240)
            target = rng.uniform(3, 12) / 3.6 if sim_t < jam_until else rng.uniform(30, 45) / 3.6
            speed += (target - speed) * min(1.0, step / 20)
            d += speed * step
            # reached a pickup stop -> dwell
            if next_stop < len(stop_marks) and d >= stop_marks[next_stop]:
                d = stop_marks[next_stop]
                dwell_until = sim_t + rng.uniform(0.5, 1.5) * args.dwell
                next_stop += 1
        lat, lng, heading = path.at(d)
        if detour and detour[0] <= d <= detour[1]:
            # diversion: drive ~500 m to the left of the planned road -> should trigger "off route"
            side = math.radians(heading - 90)
            lat += 500 * math.cos(side) / DEG_LAT_M
            lng += 500 * math.sin(side) / (111_320 * math.cos(math.radians(lat)))
        # GPS noise
        lat += rng.gauss(0, args.noise) / DEG_LAT_M
        lng += rng.gauss(0, args.noise) / (111_320 * math.cos(math.radians(lat)))
        if rng.random() >= args.dropout:  # dropout = phone lost signal this tick
            try:
                r = c.post("/driver/location", headers=headers, json={
                    "lat": lat, "lng": lng, "heading": round(heading), "accuracy_m": abs(rng.gauss(args.noise, 3)),
                    "sim_speedup": args.speedup})
                live = r.json()
                if bus["verbose"] and live.get("campus_eta_min") is not None:
                    print(f"[{number}] {d / 1000:5.1f}/{path.total / 1000:.1f} km  "
                          f"{(live.get('speed_kmh') or 0):4.0f} km/h  campus in {live['campus_eta_min']} min"
                          f"{'  OFF ROUTE' if live.get('off_route') else ''}", flush=True)
            except httpx.HTTPError as e:
                print(f"[{number}] post failed: {e}", flush=True)
        time.sleep(tick)
    if not stop_flag.is_set():  # final fix at campus so the trip is marked "arrived"
        lat, lng, heading = path.at(path.total)
        c.post("/driver/location", headers=headers, json={"lat": lat, "lng": lng, "heading": round(heading),
                                                           "sim_speedup": args.speedup})
    print(f"[{number}] arrived at campus", flush=True)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--speedup", type=float, default=10, help="simulated seconds per real second (default 10)")
    ap.add_argument("--tick", type=float, default=1.0, help="real seconds between GPS fixes (default 1)")
    ap.add_argument("--noise", type=float, default=8, help="GPS jitter in metres (default 8)")
    ap.add_argument("--dropout", type=float, default=0.03, help="chance a fix is lost (default 0.03)")
    ap.add_argument("--dwell", type=float, default=60, help="boarding seconds per stop (default 60)")
    ap.add_argument("--stagger", type=float, default=3, help="real seconds between bus departures")
    ap.add_argument("--buses", help="comma-separated bus ids (default: all planned buses)")
    ap.add_argument("--detour", type=int, help="bus id that takes a detour (tests off-route alert)")
    ap.add_argument("--quiet", action="store_true")
    ap.add_argument("--seed", type=int)
    args = ap.parse_args()

    rng = random.Random(args.seed)
    c = httpx.Client(base_url=API, timeout=30)
    admin = login(c, "admin", "admin123")
    poll = c.get("/admin/polls", headers=admin).json()
    plan = next((c.get(f"/admin/polls/{p['id']}/plan", headers=admin).json()["plan"] for p in poll
                 if p["status"] == "planned"), None)
    if not plan:
        sys.exit("No plan yet - plan routes in the admin page first.")
    wanted = {int(x) for x in args.buses.split(",")} if args.buses else None
    campus = (plan["campus"]["lat"], plan["campus"]["lng"])
    buses = []
    for i, r in enumerate(r for r in plan["routes"] if wanted is None or r["bus_id"] in wanted):
        pts = r.get("geometry") or [[s["lat"], s["lng"]] for s in r["stops"]] + [list(campus)]
        path = Path([tuple(p) for p in pts])
        marks = sorted(path.nearest_along((s["lat"], s["lng"])) for s in r["stops"])
        buses.append({"bus_id": r["bus_id"], "number": r["bus_number"], "path": path, "stops": marks,
                      "headers": login(c, f"driver{r['bus_id']}", "driver123"),
                      "delay": i * args.stagger, "verbose": not args.quiet and i < 3})
    print(f"Simulating {len(buses)} buses at {args.speedup:g}x speed. Ctrl+C to stop.", flush=True)

    stop_flag = threading.Event()
    threads = [threading.Thread(target=drive, args=(b, args, stop_flag, random.Random(rng.random())), daemon=True)
               for b in buses]
    for t in threads:
        t.start()
    try:
        while any(t.is_alive() for t in threads):
            time.sleep(0.5)
    except KeyboardInterrupt:
        stop_flag.set()
    print("Simulation finished.")


if __name__ == "__main__":
    main()
