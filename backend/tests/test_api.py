"""API tests, split by feature: registration, voting, planning, driver/assignment,
live tracking and access control. Each test gets a fresh app with fresh demo data."""
import importlib
import os
import sqlite3
import sys
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect


# --------------------------------------------------------------------------- fixtures


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


def login(c, username, password):
    r = c.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def register(c, student_id, name, password="secret1"):
    return c.post(
        "/api/auth/register",
        json={"student_id": student_id, "name": name, "password": password},
    )


def college_students():
    from app.college_db import get_directory

    return get_directory().all_students()


def registered_usernames():
    conn = sqlite3.connect(os.environ["APP_DB_PATH"])
    try:
        return {row[0] for row in conn.execute("SELECT username FROM users")}
    finally:
        conn.close()


@pytest.fixture()
def admin(client):
    return login(client, "admin", "admin123")


@pytest.fixture()
def new_student(client):
    """A fee-paid student from the college records who has not registered yet."""
    taken = registered_usernames()
    return next(s for s in college_students() if s.fee_paid and s.student_id not in taken)


@pytest.fixture()
def student(client, new_student):
    """Auth headers for a freshly registered student."""
    r = register(client, new_student.student_id, new_student.name)
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


@pytest.fixture()
def open_poll(client, student):
    poll = client.get("/api/polls/current", headers=student).json()["poll"]
    assert poll["status"] == "open"
    return poll


def vote_and_simulate(client, admin, student, poll):
    r = client.post(f"/api/polls/{poll['id']}/vote", json={"going": True}, headers=student)
    assert r.status_code == 200, r.text
    client.post(f"/api/admin/polls/{poll['id']}/simulate-votes", json={"turnout": 0.6}, headers=admin)


@pytest.fixture()
def planned(client, admin, student, open_poll):
    """Student votes yes, the rest are simulated, voting closes and routes are planned."""
    vote_and_simulate(client, admin, student, open_poll)
    client.post(f"/api/admin/polls/{open_poll['id']}/close", headers=admin)
    counts = client.get(f"/api/admin/polls/{open_poll['id']}/counts", headers=admin).json()
    plan = client.post(f"/api/admin/polls/{open_poll['id']}/plan", headers=admin).json()
    return {"poll": open_poll, "counts": counts, "plan": plan}


@pytest.fixture()
def my_bus(client, student, planned):
    mine = client.get("/api/me/bus", headers=student).json()
    assert mine["assigned"]
    return mine


@pytest.fixture()
def driver(client, my_bus):
    """Auth headers for the driver of the student's bus."""
    return login(client, f"driver{my_bus['route']['bus_id']}", "driver123")


def token_of(headers):
    return headers["Authorization"].split()[1]


# ----------------------------------------------------------------------- registration


def test_register_rejects_unknown_student_id(client):
    assert register(client, "NOPE123", "X Y").status_code == 400


def test_register_rejects_unpaid_transport_fee(client):
    unpaid = next(s for s in college_students() if not s.fee_paid)
    assert register(client, unpaid.student_id, unpaid.name).status_code == 403


def test_register_rejects_name_that_does_not_match_records(client, new_student):
    assert register(client, new_student.student_id, "Wrong Name").status_code == 400


def test_register_accepts_valid_student_with_case_insensitive_id(client, new_student):
    r = register(client, new_student.student_id.lower(), new_student.name)
    assert r.status_code == 200, r.text
    assert r.json()["token"]


# ----------------------------------------------------------------------------- voting


def test_student_can_vote_in_open_poll(client, student, open_poll):
    r = client.post(f"/api/polls/{open_poll['id']}/vote", json={"going": True}, headers=student)
    assert r.status_code == 200, r.text


def test_cannot_plan_while_voting_is_still_open(client, admin, student, open_poll):
    vote_and_simulate(client, admin, student, open_poll)
    assert client.post(f"/api/admin/polls/{open_poll['id']}/plan", headers=admin).status_code == 400


def test_cannot_vote_after_voting_closes(client, student, planned):
    poll = planned["poll"]
    r = client.post(f"/api/polls/{poll['id']}/vote", json={"going": False}, headers=student)
    assert r.status_code == 400


# --------------------------------------------------------------------------- planning


def test_plan_seats_every_rider(planned):
    assert planned["plan"]["riders"] == planned["counts"]["total_yes"]


def test_plan_uses_fewer_buses_than_the_fleet(planned):
    plan = planned["plan"]
    assert plan["buses_used"] < plan["fleet_size"]


def test_no_bus_exceeds_its_seat_limit(planned):
    for route in planned["plan"]["routes"]:
        assert route["load"] <= route["capacity"]


def test_plan_includes_a_summary(planned):
    assert planned["plan"]["ai_summary"]


# ------------------------------------------------------------------ assignment and driver


def test_students_bus_stops_at_their_stop(client, student, my_bus):
    my_stop = client.get("/api/me", headers=student).json()["stop"]["id"]
    assert my_stop in [s["id"] for s in my_bus["route"]["stops"]]


def test_driver_sees_their_own_route(client, my_bus, driver):
    route = client.get("/api/driver/route", headers=driver).json()["route"]
    assert route["bus_id"] == my_bus["route"]["bus_id"]


def test_student_sees_driver_location(client, student, driver):
    client.post("/api/driver/location", json={"lat": 17.40, "lng": 78.55}, headers=driver)
    assert client.get("/api/me/bus", headers=student).json()["location"]["lat"] == 17.40


def test_poor_gps_fixes_are_ignored(client, driver):
    r = client.post("/api/driver/location", json={"lat": 1, "lng": 1, "accuracy_m": 900}, headers=driver)
    assert r.json()["ignored"]


# ---------------------------------------------------------------------- live tracking


def test_live_tracking_pushes_fixes_and_etas_to_the_student(client, student, my_bus, driver):
    route = my_bus["route"]
    first, campus = route["stops"][0], my_bus["campus"]
    client.post("/api/driver/location", json={"lat": 17.40, "lng": 78.55}, headers=driver)

    with client.websocket_connect(f"/api/ws/bus/{route['bus_id']}?token={token_of(student)}") as ws:
        assert ws.receive_json()["type"] == "bus"  # initial snapshot

        client.post("/api/driver/trip/start", headers=driver)
        assert ws.receive_json()["data"]["state"] == "not_started"

        r = client.post("/api/driver/location", json={"lat": first["lat"], "lng": first["lng"]}, headers=driver)
        live = ws.receive_json()["data"]
        assert live == r.json()
        assert live["state"] == "live" and live["stops"][0]["status"] == "at_stop"
        assert live["campus_eta_min"] > 0 and live["off_route"] is False

        # 40 minutes later the bus reaches campus (a jump this far within seconds would be rejected)
        import app.main as main_mod

        later = (datetime.now() + timedelta(minutes=40)).replace(microsecond=0).isoformat()
        real_now = main_mod.now_iso
        main_mod.now_iso = lambda: later
        try:
            client.post("/api/driver/location", json={"lat": campus["lat"], "lng": campus["lng"]}, headers=driver)
        finally:
            main_mod.now_iso = real_now
        done = ws.receive_json()["data"]
        assert done["state"] == "arrived"
        assert all(s["status"] == "passed" for s in done["stops"])


# --------------------------------------------------------------------- access control


def test_student_cannot_watch_another_bus(client, student, planned, my_bus):
    other = next(r for r in planned["plan"]["routes"] if r["bus_id"] != my_bus["route"]["bus_id"])
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect(f"/api/ws/bus/{other['bus_id']}?token={token_of(student)}") as ws:
            ws.receive_json()


def test_student_cannot_use_admin_endpoints(client, student):
    assert client.get("/api/admin/buses", headers=student).status_code == 403
