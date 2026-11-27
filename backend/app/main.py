from __future__ import annotations

import json
import random
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path

import jwt
from fastapi import Depends, FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import config
from .ai_agent import explain_plan
from .auth import create_token, current_user, hash_password, require_role, verify_password
from .college_db import get_directory
from .db import get_db, session
from .hub import hub
from . import tracking
from .planner import BusSpec, StopDemand, plan_routes
from .roads import road_route
from .seed import seed

@asynccontextmanager
async def lifespan(_app):
    seed()
    yield


app = FastAPI(title="Smart College Bus Planner", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware, allow_origins=config.CORS_ORIGINS, allow_methods=["*"], allow_headers=["*"]
)


def now_iso() -> str:
    return datetime.now().replace(microsecond=0).isoformat()


# ---------------------------------------------------------------- helpers

def poll_status(db, poll) -> str:
    if db.execute("SELECT 1 FROM plans WHERE poll_id = ?", (poll["id"],)).fetchone():
        return "planned"
    now = now_iso()
    if now < poll["opens_at"]:
        return "scheduled"
    if now < poll["closes_at"]:
        return "open"
    return "closed"


def get_poll(db, poll_id: int):
    poll = db.execute("SELECT * FROM polls WHERE id = ?", (poll_id,)).fetchone()
    if poll is None:
        raise HTTPException(404, "Poll not found")
    return poll


def latest_poll(db):
    return db.execute("SELECT * FROM polls ORDER BY id DESC LIMIT 1").fetchone()


def stops_by_id(db) -> dict[str, dict]:
    return {r["id"]: dict(r) for r in db.execute("SELECT * FROM stops")}


def stop_counts(db, poll_id: int) -> list[dict]:
    rows = db.execute(
        """SELECT s.id, s.name, s.lat, s.lng,
                  COALESCE(SUM(v.going = 1), 0) AS yes,
                  COALESCE(SUM(v.going = 0), 0) AS no
           FROM stops s LEFT JOIN votes v ON v.stop_id = s.id AND v.poll_id = ?
           GROUP BY s.id ORDER BY s.id""",
        (poll_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def plan_view(db, poll_id: int) -> dict | None:
    plan = db.execute("SELECT * FROM plans WHERE poll_id = ?", (poll_id,)).fetchone()
    if plan is None:
        return None
    stops = stops_by_id(db)
    buses = {r["id"]: dict(r) for r in db.execute("SELECT * FROM buses")}
    routes = []
    for r in db.execute("SELECT * FROM routes WHERE plan_id = ? ORDER BY id", (plan["id"],)):
        bus = buses[r["bus_id"]]
        routes.append({
            "bus_id": bus["id"], "bus_number": bus["number"], "capacity": bus["capacity"],
            "load": r["load"], "km": r["km"], "minutes": r["minutes"],
            "stops": [{**stops[s["stop_id"]], "pickup": s["pickup"]} for s in json.loads(r["stops_json"])],
            "geometry": json.loads(r["geometry_json"]) if r["geometry_json"] else None,
        })
    total_km = plan["total_km"]
    avg_km = total_km / len(routes) if routes else 0
    unserved = json.loads(plan["unserved_json"])
    return {
        "poll_id": poll_id, "created_at": plan["created_at"], "solver": plan["solver"],
        "distance_source": plan["distance_source"] or "straight-line",
        "riders": plan["riders"], "buses_used": plan["buses_used"], "fleet_size": plan["fleet_size"],
        "total_km": total_km,
        "est_diesel_litres": round(total_km / config.BUS_KM_PER_LITRE, 1),
        # Estimate: idle buses would each have driven an average-length route.
        "est_saving_litres": round((plan["fleet_size"] - plan["buses_used"]) * avg_km / config.BUS_KM_PER_LITRE, 1),
        "unserved": {stops[k]["name"]: v for k, v in unserved.items()},
        "routes": routes,
        "campus": {"name": config.CAMPUS_NAME, "lat": config.CAMPUS_LAT, "lng": config.CAMPUS_LNG},
        "ai_summary": plan["ai_summary"],
    }


def bus_location(db, bus_id: int):
    r = db.execute("SELECT lat, lng, updated_at FROM bus_locations WHERE bus_id = ?", (bus_id,)).fetchone()
    return dict(r) if r else None


# ---------------------------------------------------------------- auth

class RegisterIn(BaseModel):
    student_id: str = Field(min_length=3, max_length=20)
    name: str = Field(min_length=2, max_length=80)
    password: str = Field(min_length=6, max_length=100)


class LoginIn(BaseModel):
    username: str
    password: str


@app.post("/api/auth/register")
def register(body: RegisterIn, db=Depends(get_db)):
    sid = body.student_id.strip().upper()
    record = get_directory().lookup(sid)
    if record is None:
        raise HTTPException(400, "Student ID not found in college records")
    if record.name.strip().lower() != body.name.strip().lower():
        raise HTTPException(400, "Name does not match college records for this Student ID")
    if not record.fee_paid:
        raise HTTPException(403, "Transport fee is pending. Please clear it at the accounts office to register.")
    if db.execute("SELECT 1 FROM users WHERE username = ?", (sid,)).fetchone():
        raise HTTPException(409, "This Student ID is already registered. Please log in.")
    db.execute(
        "INSERT INTO users (username,name,password_hash,role) VALUES (?,?,?, 'student')",
        (sid, record.name, hash_password(body.password)),
    )
    return {"token": create_token(sid, "student"), "role": "student"}


@app.post("/api/auth/login")
def login(body: LoginIn, db=Depends(get_db)):
    username = body.username.strip()
    user = db.execute(
        "SELECT * FROM users WHERE username = ? OR username = ?", (username, username.upper())
    ).fetchone()
    if user is None or not verify_password(body.password, user["password_hash"]):
        raise HTTPException(401, "Wrong username or password")
    return {"token": create_token(user["username"], user["role"]), "role": user["role"]}


@app.get("/api/me")
def me(user=Depends(current_user), db=Depends(get_db)):
    out = {"username": user["username"], "name": user["name"], "role": user["role"]}
    if user["role"] == "student":
        rec = get_directory().lookup(user["username"])
        stop = stops_by_id(db).get(rec.stop_id) if rec else None
        out.update({"stop": stop, "fee_paid": bool(rec and rec.fee_paid)})
    if user["role"] == "driver":
        bus = db.execute("SELECT * FROM buses WHERE id = ?", (user["bus_id"],)).fetchone()
        out["bus"] = dict(bus) if bus else None
    return out


@app.get("/api/stops")
def list_stops(db=Depends(get_db)):
    return {
        "stops": list(stops_by_id(db).values()),
        "campus": {"name": config.CAMPUS_NAME, "lat": config.CAMPUS_LAT, "lng": config.CAMPUS_LNG},
    }


# ---------------------------------------------------------------- student

class VoteIn(BaseModel):
    going: bool


@app.get("/api/polls/current")
def current_poll(user=Depends(require_role("student")), db=Depends(get_db)):
    poll = latest_poll(db)
    if poll is None:
        return {"poll": None}
    vote = db.execute(
        "SELECT going, voted_at FROM votes WHERE poll_id = ? AND username = ?", (poll["id"], user["username"])
    ).fetchone()
    return {"poll": {**dict(poll), "status": poll_status(db, poll)}, "my_vote": dict(vote) if vote else None}


@app.post("/api/polls/{poll_id}/vote")
def vote(poll_id: int, body: VoteIn, user=Depends(require_role("student")), db=Depends(get_db)):
    poll = get_poll(db, poll_id)
    status = poll_status(db, poll)
    if status != "open":
        raise HTTPException(400, f"Voting is {status}. It is open from {poll['opens_at']} to {poll['closes_at']}.")
    rec = get_directory().lookup(user["username"])
    if rec is None or not rec.fee_paid:  # re-check: fee status can change after registration
        raise HTTPException(403, "Transport fee is pending; you cannot book a seat.")
    db.execute(
        """INSERT INTO votes (poll_id, username, stop_id, going, voted_at) VALUES (?,?,?,?,?)
           ON CONFLICT(poll_id, username) DO UPDATE SET going = excluded.going,
             stop_id = excluded.stop_id, voted_at = excluded.voted_at""",
        (poll_id, user["username"], rec.stop_id, int(body.going), now_iso()),
    )
    return {"ok": True, "going": body.going}


@app.get("/api/me/bus")
def my_bus(user=Depends(require_role("student")), db=Depends(get_db)):
    poll = db.execute(
        "SELECT p.* FROM polls p JOIN plans pl ON pl.poll_id = p.id ORDER BY p.id DESC LIMIT 1"
    ).fetchone()
    if poll is None:
        return {"assigned": False, "reason": "Bus allocation has not been published yet."}
    a = db.execute(
        "SELECT bus_id FROM assignments WHERE poll_id = ? AND username = ?", (poll["id"], user["username"])
    ).fetchone()
    if a is None:
        v = db.execute(
            "SELECT going FROM votes WHERE poll_id = ? AND username = ?", (poll["id"], user["username"])
        ).fetchone()
        reason = ("You did not vote for this trip, so no seat was reserved." if v is None
                  else "You voted No for this trip." if not v["going"]
                  else "Sorry, all seats were full. Please contact the transport office.")
        return {"assigned": False, "trip_date": poll["trip_date"], "reason": reason}
    view = plan_view(db, poll["id"])
    route = next(r for r in view["routes"] if r["bus_id"] == a["bus_id"])
    return {
        "assigned": True, "trip_date": poll["trip_date"], "route": route,
        "campus": view["campus"], "location": bus_location(db, a["bus_id"]),
        "live": tracking.live_status(db, a["bus_id"], now_iso()),
    }


# ---------------------------------------------------------------- driver

class LocationIn(BaseModel):
    lat: float = Field(ge=-90, le=90)
    lng: float = Field(ge=-180, le=180)
    heading: float | None = Field(None, ge=0, le=360)
    accuracy_m: float | None = Field(None, ge=0)
    sim_speedup: float = Field(1.0, ge=1, le=100)  # simulator only: simulated seconds per real second


@app.get("/api/driver/route")
def driver_route(user=Depends(require_role("driver")), db=Depends(get_db)):
    poll = db.execute(
        "SELECT p.* FROM polls p JOIN plans pl ON pl.poll_id = p.id ORDER BY p.id DESC LIMIT 1"
    ).fetchone()
    if poll is None:
        return {"route": None}
    view = plan_view(db, poll["id"])
    route = next((r for r in view["routes"] if r["bus_id"] == user["bus_id"]), None)
    return {"trip_date": poll["trip_date"], "route": route, "campus": view["campus"],
            "live": tracking.live_status(db, user["bus_id"], now_iso()) if route else None}


MAX_ACCURACY_M = 150  # ignore very poor fixes (indoors / cell-tower only)


@app.post("/api/driver/trip/start")
async def driver_trip_start(user=Depends(require_role("driver")), db=Depends(get_db)):
    """Driver starts the trip: forget progress from any earlier run."""
    db.execute("DELETE FROM bus_locations WHERE bus_id = ?", (user["bus_id"],))
    db.commit()
    live = tracking.live_status(db, user["bus_id"], now_iso())
    await hub.publish(user["bus_id"], live)
    return live


@app.post("/api/driver/location")
async def driver_location(body: LocationIn, user=Depends(require_role("driver")), db=Depends(get_db)):
    if body.accuracy_m is not None and body.accuracy_m > MAX_ACCURACY_M:
        return {"ignored": True, "reason": f"GPS accuracy {round(body.accuracy_m)} m is too poor"}
    live = tracking.record_fix(db, user["bus_id"], body.lat, body.lng, now_iso(), body.heading, body.accuracy_m,
                                body.sim_speedup)
    db.commit()
    await hub.publish(user["bus_id"], live)
    return live


# ---------------------------------------------------------------- admin

class PollIn(BaseModel):
    trip_date: str
    opens_at: str
    closes_at: str


class BusIn(BaseModel):
    number: str = Field(min_length=1, max_length=20)
    capacity: int = Field(gt=0, le=120)


class SimulateIn(BaseModel):
    turnout: float = Field(0.7, ge=0, le=1)


admin = require_role("admin")


@app.get("/api/admin/polls")
def admin_polls(_=Depends(admin), db=Depends(get_db)):
    polls = db.execute("SELECT * FROM polls ORDER BY id DESC LIMIT 20").fetchall()
    return [{**dict(p), "status": poll_status(db, p)} for p in polls]


@app.post("/api/admin/polls")
def create_poll(body: PollIn, _=Depends(admin), db=Depends(get_db)):
    try:
        opens, closes = datetime.fromisoformat(body.opens_at), datetime.fromisoformat(body.closes_at)
        datetime.fromisoformat(body.trip_date)
    except ValueError:
        raise HTTPException(400, "Invalid date/time format")
    if closes <= opens:
        raise HTTPException(400, "Voting must close after it opens")
    cur = db.execute(
        "INSERT INTO polls (trip_date, opens_at, closes_at) VALUES (?,?,?)",
        (body.trip_date, opens.isoformat(), closes.isoformat()),
    )
    return {"id": cur.lastrowid}


@app.post("/api/admin/polls/{poll_id}/close")
def close_poll(poll_id: int, _=Depends(admin), db=Depends(get_db)):
    get_poll(db, poll_id)
    db.execute("UPDATE polls SET closes_at = ? WHERE id = ? AND closes_at > ?", (now_iso(), poll_id, now_iso()))
    return {"ok": True}


@app.get("/api/admin/polls/{poll_id}/counts")
def poll_counts(poll_id: int, _=Depends(admin), db=Depends(get_db)):
    poll = get_poll(db, poll_id)
    counts = stop_counts(db, poll_id)
    registered = db.execute("SELECT COUNT(*) FROM users WHERE role='student'").fetchone()[0]
    return {
        "poll": {**dict(poll), "status": poll_status(db, poll)},
        "stops": counts,
        "total_yes": sum(c["yes"] for c in counts),
        "total_no": sum(c["no"] for c in counts),
        "registered_students": registered,
    }


@app.post("/api/admin/polls/{poll_id}/simulate-votes")
def simulate_votes(poll_id: int, body: SimulateIn, _=Depends(admin), db=Depends(get_db)):
    """Demo helper: casts random votes for registered students who haven't voted."""
    get_poll(db, poll_id)
    directory = get_directory()
    rng = random.Random()
    # Real turnout differs by area (distance, local holidays, rain...), so vary it per stop.
    stop_factor = {s: rng.uniform(0.75, 1.2) for s in stops_by_id(db)}
    students = db.execute(
        """SELECT username FROM users u WHERE role='student'
           AND NOT EXISTS (SELECT 1 FROM votes v WHERE v.poll_id=? AND v.username=u.username)""",
        (poll_id,),
    ).fetchall()
    n = 0
    for s in students:
        rec = directory.lookup(s["username"])
        if rec is None or not rec.fee_paid:
            continue
        db.execute(
            "INSERT INTO votes (poll_id, username, stop_id, going, voted_at) VALUES (?,?,?,?,?)",
            (poll_id, s["username"], rec.stop_id, int(rng.random() < min(1.0, body.turnout * stop_factor.get(rec.stop_id, 1.0))), now_iso()),
        )
        n += 1
    return {"votes_added": n}


@app.post("/api/admin/polls/{poll_id}/plan")
def run_planner(poll_id: int, _=Depends(admin), db=Depends(get_db)):
    poll = get_poll(db, poll_id)
    if poll_status(db, poll) in ("open", "scheduled"):
        raise HTTPException(400, "Close voting before planning routes.")

    counts = stop_counts(db, poll_id)
    # Only buses that are active AND have a driver can be sent out.
    buses = [BusSpec(b["id"], b["number"], b["capacity"]) for b in db.execute(
        """SELECT * FROM buses b WHERE active = 1
           AND EXISTS (SELECT 1 FROM users u WHERE u.role = 'driver' AND u.bus_id = b.id) ORDER BY id""")]
    result = plan_routes([StopDemand(c["id"], c["name"], c["lat"], c["lng"], c["yes"]) for c in counts], buses)

    # Replace any previous plan for this poll
    old = db.execute("SELECT id FROM plans WHERE poll_id = ?", (poll_id,)).fetchone()
    if old:
        db.execute("DELETE FROM routes WHERE plan_id = ?", (old["id"],))
        db.execute("DELETE FROM plans WHERE id = ?", (old["id"],))
    db.execute("DELETE FROM assignments WHERE poll_id = ?", (poll_id,))

    cur = db.execute(
        """INSERT INTO plans (poll_id, created_at, solver, total_km, buses_used, fleet_size, riders, unserved_json)
           VALUES (?,?,?,?,?,?,?,?)""",
        (poll_id, now_iso(), result.solver, result.total_km, len(result.routes), len(buses),
         sum(r.load for r in result.routes), json.dumps(result.unserved)),
    )
    plan_id = cur.lastrowid
    stop_coords = {c["id"]: (c["lat"], c["lng"]) for c in counts}
    total_km = 0.0
    for r in result.routes:
        # Actual road path the bus drives: first stop -> ... -> campus
        road = road_route([stop_coords[s.stop_id] for s in r.stops] + [(config.CAMPUS_LAT, config.CAMPUS_LNG)])
        km = road["km"] if road["source"] == "osrm" else r.km
        total_km += km
        db.execute(
            """INSERT INTO routes (plan_id, bus_id, load, km, stops_json, geometry_json, minutes)
               VALUES (?,?,?,?,?,?,?)""",
            (plan_id, r.bus_id, r.load, km,
             json.dumps([{"stop_id": s.stop_id, "pickup": s.pickup} for s in r.stops]),
             json.dumps(road["geometry"]), road["minutes"]),
        )
    db.execute("UPDATE plans SET total_km = ?, distance_source = ? WHERE id = ?",
               (round(total_km, 2), result.distance_source, plan_id))

    # Assign each "yes" voter to a specific bus (first to vote, first seated when a stop is split).
    seats: dict[str, list[list]] = {}
    for r in result.routes:
        for s in r.stops:
            seats.setdefault(s.stop_id, []).append([r.bus_id, s.pickup])
    voters = db.execute(
        "SELECT username, stop_id FROM votes WHERE poll_id = ? AND going = 1 ORDER BY voted_at, username",
        (poll_id,),
    ).fetchall()
    for v in voters:
        for slot in seats.get(v["stop_id"], []):
            if slot[1] > 0:
                slot[1] -= 1
                db.execute("INSERT INTO assignments VALUES (?,?,?)", (poll_id, v["username"], slot[0]))
                break

    view = plan_view(db, poll_id)
    summary = explain_plan({k: v for k, v in view.items() if k != "ai_summary"})
    db.execute("UPDATE plans SET ai_summary = ? WHERE id = ?", (summary, plan_id))
    view["ai_summary"] = summary
    return view


@app.get("/api/admin/polls/{poll_id}/plan")
def get_plan(poll_id: int, _=Depends(admin), db=Depends(get_db)):
    return {"plan": plan_view(db, poll_id)}


@app.get("/api/admin/buses")
def list_buses(_=Depends(admin), db=Depends(get_db)):
    rows = db.execute(
        """SELECT b.*, u.username AS driver FROM buses b
           LEFT JOIN users u ON u.bus_id = b.id AND u.role = 'driver' ORDER BY b.id"""
    ).fetchall()
    return [{**dict(r), "location": bus_location(db, r["id"])} for r in rows]


@app.post("/api/admin/buses")
def add_bus(body: BusIn, _=Depends(admin), db=Depends(get_db)):
    if db.execute("SELECT 1 FROM buses WHERE number = ?", (body.number,)).fetchone():
        raise HTTPException(409, "A bus with that number already exists")
    cur = db.execute("INSERT INTO buses (number, capacity) VALUES (?,?)", (body.number, body.capacity))
    return {"id": cur.lastrowid}


@app.post("/api/admin/buses/{bus_id}/toggle")
def toggle_bus(bus_id: int, _=Depends(admin), db=Depends(get_db)):
    db.execute("UPDATE buses SET active = 1 - active WHERE id = ?", (bus_id,))
    return {"ok": True}


# ---------------------------------------------------------------- live tracking

@app.get("/api/admin/live")
def admin_live(_=Depends(admin), db=Depends(get_db)):
    plan = db.execute("SELECT id FROM plans ORDER BY id DESC LIMIT 1").fetchone()
    if plan is None:
        return []
    bus_ids = [r["bus_id"] for r in db.execute("SELECT bus_id FROM routes WHERE plan_id = ?", (plan["id"],))]
    now = now_iso()
    return [tracking.live_status(db, b, now) for b in bus_ids]


def _ws_user(token: str | None):
    if not token:
        return None
    try:
        payload = jwt.decode(token, config.JWT_SECRET, algorithms=["HS256"])
    except jwt.PyJWTError:
        return None
    with session() as db:
        u = db.execute("SELECT * FROM users WHERE username = ?", (payload["sub"],)).fetchone()
        return dict(u) if u else None


def _can_watch(db, user: dict, bus_id: int) -> bool:
    if user["role"] == "admin":
        return True
    if user["role"] == "driver":
        return user["bus_id"] == bus_id
    return db.execute(
        """SELECT 1 FROM assignments a WHERE a.username = ? AND a.bus_id = ?
           AND a.poll_id = (SELECT poll_id FROM plans ORDER BY id DESC LIMIT 1)""",
        (user["username"], bus_id),
    ).fetchone() is not None


async def _serve_ws(ws: WebSocket, bus_id: int | None, snapshot):
    await ws.accept()
    hub.join(ws, bus_id)
    try:
        for item in snapshot:
            await ws.send_json({"type": "bus", "data": item})
        while True:
            await ws.receive_text()  # client pings; we only push
    except WebSocketDisconnect:
        pass
    finally:
        hub.leave(ws, bus_id)


@app.websocket("/api/ws/bus/{bus_id}")
async def ws_bus(ws: WebSocket, bus_id: int, token: str | None = None):
    user = _ws_user(token)
    with session() as db:
        if user is None or not _can_watch(db, user, bus_id):
            await ws.close(code=4403)
            return
        snapshot = [tracking.live_status(db, bus_id, now_iso())]
    await _serve_ws(ws, bus_id, snapshot)


@app.websocket("/api/ws/fleet")
async def ws_fleet(ws: WebSocket, token: str | None = None):
    user = _ws_user(token)
    if user is None or user["role"] != "admin":
        await ws.close(code=4403)
        return
    with session() as db:
        plan = db.execute("SELECT id FROM plans ORDER BY id DESC LIMIT 1").fetchone()
        ids = [r["bus_id"] for r in db.execute("SELECT bus_id FROM routes WHERE plan_id = ?", (plan["id"],))] if plan else []
        now = now_iso()
        snapshot = [tracking.live_status(db, b, now) for b in ids]
    await _serve_ws(ws, None, snapshot)


# ---------------------------------------------------------------- serve built frontend (production)

_dist = Path(__file__).resolve().parents[2] / "frontend" / "dist"
if _dist.exists():
    app.mount("/assets", StaticFiles(directory=_dist / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        return FileResponse(_dist / "index.html")
