"""Live trip tracking: turns raw GPS fixes into "where is my bus" answers.

For every GPS fix from a driver's phone we:
  1. snap it onto the bus's planned road path (distance travelled along the route, metres)
  2. smooth the speed (exponential moving average of progress / time)
  3. work out which stops are passed, where the bus is now, and an ETA for every stop ahead
  4. flag problems: off the planned route, GPS signal stale/lost

Progress only moves forward (with a small tolerance), so GPS jitter or a route that passes the
same road twice can't make the bus jump backwards.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import datetime
from functools import lru_cache

from . import config

AT_STOP_M = 120          # within this distance of a stop = "at the stop"
OFF_ROUTE_M = 250        # further than this from the route line = off route
BACKTRACK_TOLERANCE_M = 150
DWELL_S_PER_STOP = 45    # boarding time added to ETAs for each intermediate stop
LIVE_S = 90              # a fix newer than this = live
STALE_S = 15 * 60        # older than this = trip not running / not started
JITTER_M = 20            # progress changes smaller than this are GPS noise, not movement
ETA_SPEED_RANGE = (0.5, 1.5)  # ETA speed is kept within this factor of the planned average
EWMA_ALPHA = 0.35
MAX_BUS_SPEED_MPS = 25   # ~90 km/h: the most a bus can advance between two fixes


def _xy(lat, lng, lat0):
    return (lng * math.cos(math.radians(lat0)) * 111_320.0, lat * 110_540.0)


@dataclass
class Projection:
    along_m: float
    offset_m: float


class RouteTrack:
    """A route's road geometry with stops located along it."""

    def __init__(self, geometry: list[list[float]], stops: list[dict], planned_minutes: float | None):
        self.lat0 = geometry[0][0]
        self.pts = [_xy(lat, lng, self.lat0) for lat, lng in geometry]
        self.cum = [0.0]
        for a, b in zip(self.pts, self.pts[1:]):
            self.cum.append(self.cum[-1] + math.dist(a, b))
        self.total_m = self.cum[-1]
        self.planned_minutes = planned_minutes
        self.stops = []
        start = 0.0
        for s in stops:  # stops are in route order, so search forward from the previous stop
            p = self.project(s["lat"], s["lng"], min_along=start, window_m=None)
            self.stops.append({"id": s["id"], "name": s["name"], "along_m": p.along_m})
            start = p.along_m

    @property
    def planned_speed_mps(self) -> float:
        if self.planned_minutes:
            return self.total_m / (self.planned_minutes * 60)
        return 25 / 3.6

    def project(self, lat, lng, min_along=0.0, window_m: float | None = 3000) -> Projection:
        """Closest point on the route at/after `min_along` (and within `window_m` ahead if given)."""
        p = _xy(lat, lng, self.lat0)
        best = None
        for i in range(len(self.pts) - 1):
            seg_start, seg_end = self.cum[i], self.cum[i + 1]
            if seg_end < min_along - BACKTRACK_TOLERANCE_M:
                continue
            limit = None if window_m is None else min_along + window_m
            if limit is not None and seg_start > limit:
                break  # the bus can't physically be further along than this
            (ax, ay), (bx, by) = self.pts[i], self.pts[i + 1]
            dx, dy = bx - ax, by - ay
            seg_len2 = dx * dx + dy * dy
            t = 0.0 if seg_len2 == 0 else max(0.0, min(1.0, ((p[0] - ax) * dx + (p[1] - ay) * dy) / seg_len2))
            seg_m = seg_end - seg_start
            if seg_m > 0 and seg_start < min_along - BACKTRACK_TOLERANCE_M:
                # this segment starts behind the bus: only its part near/after the last position counts
                t = max(t, (min_along - BACKTRACK_TOLERANCE_M - seg_start) / seg_m)
            if seg_m > 0 and limit is not None and seg_end > limit:
                t = min(t, (limit - seg_start) / seg_m)
            cx, cy = ax + t * dx, ay + t * dy
            off = math.hypot(p[0] - cx, p[1] - cy)
            along = seg_start + t * (seg_end - seg_start)
            if best is None or off < best.offset_m - 1:
                best = Projection(along, off)
        if best is None:
            return Projection(min_along, float("inf"))
        return best


@lru_cache(maxsize=256)
def _track_cached(route_id: int, geometry_json: str, stops_json: str, minutes: float | None) -> RouteTrack:
    return RouteTrack(json.loads(geometry_json), json.loads(stops_json), minutes)


def current_route(db, bus_id: int):
    """The bus's route in the most recent published plan, as (route_row, poll_row) or (None, None)."""
    row = db.execute(
        """SELECT r.*, p.trip_date, p.id AS poll_id FROM routes r
           JOIN plans pl ON pl.id = r.plan_id JOIN polls p ON p.id = pl.poll_id
           WHERE r.bus_id = ? AND pl.id = (SELECT MAX(id) FROM plans)""",
        (bus_id,),
    ).fetchone()
    return row


def track_for(db, route_row) -> RouteTrack | None:
    if route_row is None:
        return None
    stops_by_id = {r["id"]: dict(r) for r in db.execute("SELECT * FROM stops")}
    stops = [stops_by_id[s["stop_id"]] for s in json.loads(route_row["stops_json"])]
    geometry = json.loads(route_row["geometry_json"]) if route_row["geometry_json"] else None
    if not geometry or len(geometry) < 2:
        geometry = [[s["lat"], s["lng"]] for s in stops] + [[config.CAMPUS_LAT, config.CAMPUS_LNG]]
    return _track_cached(route_row["id"], json.dumps(geometry), json.dumps(stops), route_row["minutes"])


def _parse(ts: str) -> datetime:
    return datetime.fromisoformat(ts)


def record_fix(db, bus_id: int, lat: float, lng: float, now: str,
               heading: float | None = None, accuracy_m: float | None = None, sim_speedup: float = 1.0) -> dict:
    """sim_speedup: only for the simulator, which replays N simulated seconds per real second."""
    """Store a GPS fix with its progress along the route, and return the live status."""
    route = current_route(db, bus_id)
    track = track_for(db, route)
    prev = db.execute("SELECT * FROM bus_locations WHERE bus_id = ?", (bus_id,)).fetchone()

    progress, speed, offset = None, None, None
    if track is not None:
        fresh_prev = (prev is not None and prev["progress_m"] is not None and prev["route_id"] == route["id"]
                      and (_parse(now) - _parse(prev["updated_at"])).total_seconds() < STALE_S)
        min_along = prev["progress_m"] if fresh_prev else 0.0
        # Only look as far ahead as the bus could really have driven since its last fix.
        # Without this, a bus on a diversion can "snap" onto a later part of a winding route.
        window = None
        if fresh_prev:
            dt_prev = max(1.0, (_parse(now) - _parse(prev["updated_at"])).total_seconds())
            window = 300 + dt_prev * MAX_BUS_SPEED_MPS * sim_speedup
        proj = track.project(lat, lng, min_along=min_along, window_m=window)
        offset = proj.offset_m
        if offset > OFF_ROUTE_M and fresh_prev:
            progress = prev["progress_m"]  # off route: keep last known progress
        else:
            progress = max(proj.along_m, min_along - BACKTRACK_TOLERANCE_M) if fresh_prev else proj.along_m
        speed = prev["speed_mps"] if fresh_prev else None
        if fresh_prev:
            dt = (_parse(now) - _parse(prev["updated_at"])).total_seconds()
            if dt >= 1:
                moved = progress - prev["progress_m"]
                inst = 0.0 if moved < JITTER_M else moved / dt / sim_speedup
                speed = inst if speed is None else EWMA_ALPHA * inst + (1 - EWMA_ALPHA) * speed

    db.execute(
        """INSERT INTO bus_locations (bus_id, lat, lng, updated_at, route_id, progress_m, speed_mps, heading, offset_m, accuracy_m)
           VALUES (?,?,?,?,?,?,?,?,?,?)
           ON CONFLICT(bus_id) DO UPDATE SET lat=excluded.lat, lng=excluded.lng, updated_at=excluded.updated_at,
             route_id=excluded.route_id, progress_m=excluded.progress_m, speed_mps=excluded.speed_mps,
             heading=excluded.heading, offset_m=excluded.offset_m, accuracy_m=excluded.accuracy_m""",
        (bus_id, lat, lng, now, route["id"] if route else None, progress, speed, heading, offset, accuracy_m),
    )
    db.execute("INSERT INTO bus_positions (bus_id, lat, lng, ts, progress_m) VALUES (?,?,?,?,?)",
               (bus_id, lat, lng, now, progress))
    return live_status(db, bus_id, now)


def live_status(db, bus_id: int, now: str) -> dict:
    """Everything a student/admin needs to know about where a bus is right now."""
    loc = db.execute("SELECT * FROM bus_locations WHERE bus_id = ?", (bus_id,)).fetchone()
    route = current_route(db, bus_id)
    track = track_for(db, route)
    out = {"bus_id": bus_id, "state": "not_started", "location": None, "stops": [], "total_m": None}
    if track is not None:
        out["total_m"] = round(track.total_m)
        out["stops"] = [{"id": s["id"], "name": s["name"], "along_m": round(s["along_m"]), "status": "upcoming",
                         "eta_min": None} for s in track.stops]
    if loc is None:
        return out

    age_s = (_parse(now) - _parse(loc["updated_at"])).total_seconds()
    out["location"] = {"lat": loc["lat"], "lng": loc["lng"], "updated_at": loc["updated_at"],
                       "heading": loc["heading"], "age_s": round(age_s)}
    if age_s > STALE_S or track is None or loc["route_id"] != (route["id"] if route else None):
        out["state"] = "not_started" if track is not None else "no_route"
        return out

    progress = loc["progress_m"] or 0.0
    speed = loc["speed_mps"]
    # Stopped at a signal or boarding shouldn't make the ETA explode, nor a fast stretch make it
    # unrealistically short: keep the speed used for ETAs near the planned average.
    planned = track.planned_speed_mps
    lo, hi = ETA_SPEED_RANGE
    use_speed = planned if speed is None else min(max(speed, lo * planned), hi * planned)
    out.update({
        "state": "live" if age_s <= LIVE_S else "stale",
        "progress_m": round(progress),
        "speed_kmh": round(speed * 3.6, 1) if speed is not None else None,
        "off_route": (loc["offset_m"] or 0) > OFF_ROUTE_M,
        "offset_m": round(loc["offset_m"]) if loc["offset_m"] is not None else None,
    })

    upcoming_seen = 0
    next_idx = None
    for s in out["stops"]:
        delta = s["along_m"] - progress
        if delta < -AT_STOP_M:
            s["status"] = "passed"
        elif delta <= AT_STOP_M:
            s["status"] = "at_stop"
            s["eta_min"] = 0
            next_idx = next_idx if next_idx is not None else out["stops"].index(s)
        else:
            s["eta_min"] = round((delta / use_speed + upcoming_seen * DWELL_S_PER_STOP) / 60, 1)
            s["distance_m"] = round(delta)
            upcoming_seen += 1
            next_idx = next_idx if next_idx is not None else out["stops"].index(s)
    remaining_campus = max(0.0, track.total_m - progress)
    out["next_stop_index"] = next_idx
    out["campus_distance_m"] = round(remaining_campus)
    out["campus_eta_min"] = round((remaining_campus / use_speed + upcoming_seen * DWELL_S_PER_STOP) / 60, 1)
    if remaining_campus <= AT_STOP_M:
        out["state"] = "arrived"
    return out
