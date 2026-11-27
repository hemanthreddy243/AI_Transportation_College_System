import importlib
import os
import sys

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("APP_DB_PATH", str(tmp_path / "app.db"))
    monkeypatch.setenv("COLLEGE_DB_PATH", str(tmp_path / "college.db"))
    monkeypatch.setenv("AI_ENABLED", "0")
    for m in [m for m in sys.modules if m.startswith("app")]:
        del sys.modules[m]
    main = importlib.import_module("app.main")
    with TestClient(main.app) as c:
        yield c


def login(c, u, p):
    r = c.post("/api/auth/login", json={"username": u, "password": p})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def test_full_flow(client):
    from app.college_db import get_directory

    students = get_directory().all_students()
    app_db_users = set()
    admin = login(client, "admin", "admin123")

    # --- registration is checked against college records
    unregistered = None
    import sqlite3
    conn = sqlite3.connect(os.environ["APP_DB_PATH"])
    app_db_users = {r[0] for r in conn.execute("SELECT username FROM users")}
    conn.close()
    unpaid = next(s for s in students if not s.fee_paid)
    unregistered = next(s for s in students if s.fee_paid and s.student_id not in app_db_users)

    r = client.post("/api/auth/register", json={"student_id": "NOPE123", "name": "X Y", "password": "secret1"})
    assert r.status_code == 400
    r = client.post("/api/auth/register", json={"student_id": unpaid.student_id, "name": unpaid.name, "password": "secret1"})
    assert r.status_code == 403
    r = client.post("/api/auth/register", json={"student_id": unregistered.student_id, "name": "Wrong Name", "password": "secret1"})
    assert r.status_code == 400
    r = client.post("/api/auth/register", json={"student_id": unregistered.student_id.lower(), "name": unregistered.name, "password": "secret1"})
    assert r.status_code == 200, r.text
    me = {"Authorization": f"Bearer {r.json()['token']}"}

    # --- student votes yes in the open poll
    poll = client.get("/api/polls/current", headers=me).json()["poll"]
    assert poll["status"] == "open"
    assert client.post(f"/api/polls/{poll['id']}/vote", json={"going": True}, headers=me).status_code == 200

    # --- admin: simulate the rest, close, plan
    client.post(f"/api/admin/polls/{poll['id']}/simulate-votes", json={"turnout": 0.6}, headers=admin)
    assert client.post(f"/api/admin/polls/{poll['id']}/plan", headers=admin).status_code == 400  # still open
    client.post(f"/api/admin/polls/{poll['id']}/close", headers=admin)
    counts = client.get(f"/api/admin/polls/{poll['id']}/counts", headers=admin).json()
    plan = client.post(f"/api/admin/polls/{poll['id']}/plan", headers=admin).json()

    assert plan["riders"] == counts["total_yes"]  # fleet is big enough for everyone
    assert plan["buses_used"] < plan["fleet_size"]
    for r in plan["routes"]:
        assert r["load"] <= r["capacity"]
    assert plan["ai_summary"]

    # --- voting closed now
    assert client.post(f"/api/polls/{poll['id']}/vote", json={"going": False}, headers=me).status_code == 400

    # --- student sees their bus; driver of that bus posts GPS; student sees it
    mine = client.get("/api/me/bus", headers=me).json()
    assert mine["assigned"]
    my_stop = client.get("/api/me", headers=me).json()["stop"]["id"]
    assert my_stop in [s["id"] for s in mine["route"]["stops"]]

    drv = login(client, f"driver{mine['route']['bus_id']}", "driver123")
    assert client.get("/api/driver/route", headers=drv).json()["route"]["bus_id"] == mine["route"]["bus_id"]
    client.post("/api/driver/location", json={"lat": 17.40, "lng": 78.55}, headers=drv)
    assert client.get("/api/me/bus", headers=me).json()["location"]["lat"] == 17.40

    # --- live tracking: student's socket receives the driver's fixes, with stop ETAs
    route = mine["route"]
    first, campus = route["stops"][0], mine["campus"]
    token = me["Authorization"].split()[1]
    with client.websocket_connect(f"/api/ws/bus/{route['bus_id']}?token={token}") as ws:
        assert ws.receive_json()["type"] == "bus"  # initial snapshot
        client.post("/api/driver/trip/start", headers=drv)
        assert ws.receive_json()["data"]["state"] == "not_started"
        r = client.post("/api/driver/location", json={"lat": first["lat"], "lng": first["lng"]}, headers=drv)
        live = ws.receive_json()["data"]
        assert live == r.json()
        assert live["state"] == "live" and live["stops"][0]["status"] == "at_stop"
        assert live["campus_eta_min"] > 0 and live["off_route"] is False
        # 40 minutes later the bus reaches campus (a jump this far within seconds would be rejected)
        import app.main as main_mod
        from datetime import datetime, timedelta
        later = (datetime.now() + timedelta(minutes=40)).replace(microsecond=0).isoformat()
        real_now = main_mod.now_iso
        main_mod.now_iso = lambda: later
        try:
            client.post("/api/driver/location", json={"lat": campus["lat"], "lng": campus["lng"]}, headers=drv)
        finally:
            main_mod.now_iso = real_now
        done = ws.receive_json()["data"]
        assert done["state"] == "arrived" and all(s["status"] == "passed" for s in done["stops"])

    # poor GPS fixes are ignored
    assert client.post("/api/driver/location", json={"lat": 1, "lng": 1, "accuracy_m": 900}, headers=drv).json()["ignored"]

    # a student can't watch someone else's bus
    other = next(r for r in plan["routes"] if r["bus_id"] != route["bus_id"])
    import pytest
    from starlette.websockets import WebSocketDisconnect
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect(f"/api/ws/bus/{other['bus_id']}?token={token}") as ws:
            ws.receive_json()

    # --- role checks
    assert client.get("/api/admin/buses", headers=me).status_code == 403
