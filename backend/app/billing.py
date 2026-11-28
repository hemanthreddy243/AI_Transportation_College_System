"""Transport-fee payments (demo checkout) and the savings ledger.

Payments: students pay their transport fee to the college. Until a real payment gateway
(e.g. Razorpay/Cashfree, settling into the college's account) is connected, checkout is a
DEMO: no money moves and no card/UPI details are collected. A successful payment marks
the fee as paid in the college records through the CollegeDirectory adapter.

Savings: every published plan is recorded with what it saved versus the college's old
way of running buses (a fixed number of buses every day). The total saved is the basis for
the platform fee charged to the college (a % of savings).
"""
from __future__ import annotations

import random
import secrets
from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from . import config
from .auth import require_role
from .college_db import get_directory
from .db import get_db

router = APIRouter()
admin = require_role("admin")
student = require_role("student")

DEFAULT_SETTINGS = {
    "academic_year": "2026-27",
    "transport_fee": "24000",          # ₹ per student per academic year
    "diesel_price": "92",              # ₹ per litre
    "baseline_buses": "",              # buses the college ran daily before; blank = whole active fleet
    "platform_fee_pct": "15",          # % of savings charged by the platform
}
PAY_METHODS = {"upi": "UPI", "card": "Card", "netbanking": "Net banking"}


def now_iso() -> str:
    return datetime.now().replace(microsecond=0).isoformat()


# ---------------------------------------------------------------- settings

def get_settings(db) -> dict:
    stored = {r["key"]: r["value"] for r in db.execute("SELECT key, value FROM settings")}
    return {**DEFAULT_SETTINGS, **stored}


def active_fleet(db) -> int:
    return db.execute(
        """SELECT COUNT(*) FROM buses b WHERE active = 1
           AND EXISTS (SELECT 1 FROM users u WHERE u.role='driver' AND u.bus_id=b.id)"""
    ).fetchone()[0]


def baseline_buses(db, s: dict | None = None) -> int:
    s = s or get_settings(db)
    return int(s["baseline_buses"]) if s["baseline_buses"] else active_fleet(db)


class SettingsIn(BaseModel):
    academic_year: str = Field(min_length=4, max_length=20)
    transport_fee: int = Field(gt=0, le=500_000)
    diesel_price: float = Field(gt=0, le=1000)
    baseline_buses: int | None = Field(None, gt=0, le=1000)
    platform_fee_pct: float = Field(ge=0, le=100)


@router.get("/api/admin/settings")
def read_settings(_=Depends(admin), db=Depends(get_db)):
    s = get_settings(db)
    return {**s, "effective_baseline_buses": baseline_buses(db, s), "active_fleet": active_fleet(db)}


@router.put("/api/admin/settings")
def write_settings(body: SettingsIn, _=Depends(admin), db=Depends(get_db)):
    values = body.model_dump()
    values["baseline_buses"] = "" if values["baseline_buses"] is None else values["baseline_buses"]
    db.executemany(
        "INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        [(k, str(v)) for k, v in values.items()],
    )
    return read_settings(_, db)


# ---------------------------------------------------------------- savings ledger

def compute_savings(actual_km: float, buses_used: int, baseline: int, diesel_price: float) -> dict:
    """Saving vs. running `baseline` buses on routes of today's average length."""
    avg_km = actual_km / buses_used if buses_used else 0.0
    baseline_km = baseline * avg_km
    saved_km = max(0.0, baseline_km - actual_km)
    litres = saved_km / config.BUS_KM_PER_LITRE
    return {"baseline_km": round(baseline_km, 2), "saved_km": round(saved_km, 2),
            "litres_saved": round(litres, 1), "rupees_saved": round(litres * diesel_price)}


def record_plan_savings(db, plan_id: int):
    """Called whenever a plan is published (re-planning a trip replaces its record)."""
    plan = db.execute(
        "SELECT pl.*, p.trip_date FROM plans pl JOIN polls p ON p.id = pl.poll_id WHERE pl.id = ?", (plan_id,)
    ).fetchone()
    s = get_settings(db)
    base = baseline_buses(db, s)
    price = float(s["diesel_price"])
    sv = compute_savings(plan["total_km"], plan["buses_used"], base, price)
    db.execute("DELETE FROM trip_savings WHERE poll_id = ?", (plan["poll_id"],))
    db.execute(
        """INSERT INTO trip_savings (poll_id, trip_date, riders, buses_used, baseline_buses, actual_km, baseline_km,
             diesel_price, litres_saved, rupees_saved, created_at, demo) VALUES (?,?,?,?,?,?,?,?,?,?,?,0)""",
        (plan["poll_id"], plan["trip_date"], plan["riders"], plan["buses_used"], base, plan["total_km"],
         sv["baseline_km"], price, sv["litres_saved"], sv["rupees_saved"], now_iso()),
    )
    return sv


def seed_demo_savings(db, days: int = 22, rng: random.Random | None = None):
    """Demo history so the savings page isn't empty before a pilot. Marked demo=1, can be cleared."""
    rng = rng or random.Random(7)
    fleet = active_fleet(db) or 10
    price = float(DEFAULT_SETTINGS["diesel_price"])
    d = date.today()
    added = 0
    while added < days:
        d -= timedelta(days=1)
        if d.weekday() == 6:  # no buses on Sunday
            continue
        used = max(1, round(fleet * rng.uniform(0.42, 0.62)))
        avg_km = rng.uniform(25, 31)
        actual = round(used * avg_km, 2)
        sv = compute_savings(actual, used, fleet, price)
        db.execute(
            """INSERT INTO trip_savings (poll_id, trip_date, riders, buses_used, baseline_buses, actual_km, baseline_km,
                 diesel_price, litres_saved, rupees_saved, created_at, demo) VALUES (NULL,?,?,?,?,?,?,?,?,?,?,1)""",
            (d.isoformat(), round(used * rng.uniform(42, 50)), used, fleet, actual, sv["baseline_km"], price,
             sv["litres_saved"], sv["rupees_saved"], now_iso()),
        )
        added += 1


@router.get("/api/admin/savings")
def savings_report(_=Depends(admin), db=Depends(get_db)):
    s = get_settings(db)
    rows = [dict(r) for r in db.execute("SELECT * FROM trip_savings ORDER BY trip_date DESC, id DESC")]
    total_rupees = sum(r["rupees_saved"] for r in rows)
    pct = float(s["platform_fee_pct"])
    by_month: dict[str, dict] = {}
    for r in rows:
        m = by_month.setdefault(r["trip_date"][:7], {"month": r["trip_date"][:7], "trips": 0, "litres": 0.0, "rupees": 0})
        m["trips"] += 1
        m["litres"] = round(m["litres"] + r["litres_saved"], 1)
        m["rupees"] += r["rupees_saved"]
    for m in by_month.values():
        m["platform_fee"] = round(m["rupees"] * pct / 100)
    return {
        "settings": {**s, "effective_baseline_buses": baseline_buses(db, s)},
        "totals": {
            "trips": len(rows),
            "litres_saved": round(sum(r["litres_saved"] for r in rows), 1),
            "km_saved": round(sum(r["baseline_km"] - r["actual_km"] for r in rows), 1),
            "rupees_saved": total_rupees,
            "platform_fee": round(total_rupees * pct / 100),
            "college_keeps": round(total_rupees * (100 - pct) / 100),
            "avg_buses_used": round(sum(r["buses_used"] for r in rows) / len(rows), 1) if rows else 0,
            "demo_trips": sum(r["demo"] for r in rows),
        },
        "months": sorted(by_month.values(), key=lambda m: m["month"], reverse=True),
        "trips": rows[:60],
    }


@router.post("/api/admin/savings/clear-demo")
def clear_demo_savings(_=Depends(admin), db=Depends(get_db)):
    n = db.execute("DELETE FROM trip_savings WHERE demo = 1").rowcount
    return {"removed": n}


# ---------------------------------------------------------------- student fee payment (demo checkout)

class PayIn(BaseModel):
    method: str = Field(pattern="^(upi|card|netbanking)$")


def _receipt(db, username: str, year: str):
    r = db.execute(
        """SELECT * FROM payments WHERE username = ? AND academic_year = ? AND status = 'success'
           ORDER BY id DESC LIMIT 1""", (username, year),
    ).fetchone()
    return dict(r) if r else None


@router.get("/api/me/fee")
def my_fee(user=Depends(student), db=Depends(get_db)):
    s = get_settings(db)
    rec = get_directory().lookup(user["username"])
    return {
        "academic_year": s["academic_year"],
        "amount": int(s["transport_fee"]),
        "paid": bool(rec and rec.fee_paid),
        "receipt": _receipt(db, user["username"], s["academic_year"]),
        "demo": True,
    }


@router.post("/api/me/fee/pay")
def pay_fee(body: PayIn, user=Depends(student), db=Depends(get_db)):
    s = get_settings(db)
    directory = get_directory()
    rec = directory.lookup(user["username"])
    if rec is None:
        raise HTTPException(404, "Student not found in college records")
    if rec.fee_paid:
        raise HTTPException(409, "Your transport fee for this year is already paid.")
    # DEMO gateway: always succeeds. A real gateway would create an order here, and the fee
    # would be marked paid only after the gateway's signed webhook confirms the payment.
    ref = "DEMO-" + secrets.token_hex(4).upper()
    cur = db.execute(
        """INSERT INTO payments (username, academic_year, amount, method, status, reference, created_at)
           VALUES (?,?,?,?, 'success', ?, ?)""",
        (user["username"], s["academic_year"], int(s["transport_fee"]), body.method, ref, now_iso()),
    )
    directory.mark_fee_paid(user["username"])
    return {"ok": True, "receipt": dict(db.execute("SELECT * FROM payments WHERE id = ?", (cur.lastrowid,)).fetchone())}


@router.get("/api/admin/payments")
def payments_report(_=Depends(admin), db=Depends(get_db)):
    s = get_settings(db)
    fee = int(s["transport_fee"])
    students = get_directory().all_students()
    paid = sum(1 for x in students if x.fee_paid)
    online = db.execute(
        "SELECT COUNT(*), COALESCE(SUM(amount),0) FROM payments WHERE status='success' AND academic_year=?",
        (s["academic_year"],),
    ).fetchone()
    names = {x.student_id: x.name for x in students}
    recent = [{**dict(r), "name": names.get(r["username"], "")} for r in db.execute(
        "SELECT * FROM payments ORDER BY id DESC LIMIT 50")]
    return {
        "academic_year": s["academic_year"],
        "fee": fee,
        "students_total": len(students),
        "paid_count": paid,
        "pending_count": len(students) - paid,
        "pending_amount": (len(students) - paid) * fee,
        "online_count": online[0],
        "online_amount": online[1],
        "recent": recent,
        "demo": True,
    }
