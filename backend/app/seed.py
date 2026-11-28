"""Demo data: a mock college student DB, stops, buses, drivers and an open poll.

Run directly to reset everything:
    python -m app.seed --reset                 # demo: 14 stops, 420 students, 10 buses
    python -m app.seed --reset --scale large   # stress test: 32 stops, 1500 students, 30 buses
"""
from __future__ import annotations

import random
import sys
from datetime import datetime, timedelta

from . import config
from .auth import hash_password
from .college_db import MockSqliteDirectory
from .db import init_schema, session

STOPS = [
    ("S01", "Dilsukhnagar", 17.3688, 78.5247, 9),
    ("S02", "LB Nagar", 17.3457, 78.5522, 8),
    ("S03", "Uppal", 17.4058, 78.5591, 10),
    ("S04", "Habsiguda", 17.4173, 78.5422, 5),
    ("S05", "Tarnaka", 17.4278, 78.5377, 6),
    ("S06", "Secunderabad", 17.4399, 78.4983, 8),
    ("S07", "Ameerpet", 17.4375, 78.4482, 7),
    ("S08", "Kukatpally", 17.4849, 78.4138, 6),
    ("S09", "Mehdipatnam", 17.3916, 78.4400, 4),
    ("S10", "Malakpet", 17.3753, 78.5004, 4),
    ("S11", "Kothapet", 17.3680, 78.5450, 5),
    ("S12", "Nagole", 17.3727, 78.5641, 6),
    ("S13", "ECIL", 17.4710, 78.5730, 7),
    ("S14", "Boduppal", 17.4136, 78.5783, 5),
]  # (id, name, lat, lng, relative popularity)

# Extra stops used by the "large" scale (real Hyderabad localities, approximate coordinates).
EXTRA_STOPS = [
    ("S15", "Miyapur", 17.4968, 78.3614, 6),
    ("S16", "KPHB Colony", 17.4935, 78.3994, 7),
    ("S17", "Begumpet", 17.4447, 78.4664, 4),
    ("S18", "Somajiguda", 17.4250, 78.4590, 3),
    ("S19", "Lakdikapul", 17.4040, 78.4650, 3),
    ("S20", "Koti", 17.3850, 78.4867, 5),
    ("S21", "Santoshnagar", 17.3480, 78.5110, 4),
    ("S22", "Champapet", 17.3440, 78.5320, 4),
    ("S23", "Vanasthalipuram", 17.3270, 78.5660, 6),
    ("S24", "Hayathnagar", 17.3270, 78.6040, 5),
    ("S25", "Alwal", 17.5020, 78.5090, 5),
    ("S26", "Malkajgiri", 17.4470, 78.5270, 6),
    ("S27", "Sainikpuri", 17.4920, 78.5490, 5),
    ("S28", "Moula Ali", 17.4580, 78.5520, 4),
    ("S29", "Ramanthapur", 17.3990, 78.5230, 5),
    ("S30", "Amberpet", 17.3900, 78.5150, 4),
    ("S31", "Kompally", 17.5390, 78.4870, 4),
    ("S32", "Narayanguda", 17.3970, 78.4880, 3),
]

SCALES = {
    "demo": {"stops": 14, "students": 420, "buses": 10},
    "large": {"stops": 32, "students": 1500, "buses": 30},
}

BUSES = [("TS08-1101", 52), ("TS08-1102", 52), ("TS08-1103", 52), ("TS08-1104", 52),
         ("TS08-1105", 52), ("TS08-1106", 52), ("TS08-1107", 40), ("TS08-1108", 40),
         ("TS08-1109", 40), ("TS08-1110", 40)]

FIRST = ["Aarav", "Vivek", "Sai", "Rahul", "Ananya", "Divya", "Harsha", "Keerthi", "Manoj", "Sneha",
         "Pranav", "Lakshmi", "Rohit", "Meghana", "Karthik", "Swathi", "Nikhil", "Pooja", "Arjun", "Bhavana"]
LAST = ["Reddy", "Rao", "Sharma", "Kumar", "Naidu", "Varma", "Goud", "Patel", "Iyer", "Chowdary"]

DEMO_STUDENT_PASSWORD = "student123"


def _buses(n: int):
    if n <= len(BUSES):
        return BUSES[:n]
    return BUSES + [(f"TS08-{1110 + i}", 52 if i % 3 else 40) for i in range(1, n - len(BUSES) + 1)]


def seed(reset: bool = False, scale: str = "demo"):
    rng = random.Random(42)
    cfg = SCALES[scale]
    stops_all = (STOPS + EXTRA_STOPS)[: cfg["stops"]]
    if reset:
        for p in (config.APP_DB_PATH, config.COLLEGE_DB_PATH):
            if p.exists():
                p.unlink()

    # --- mock college DB ---
    college = MockSqliteDirectory()
    college.init_schema()
    if not college.all_students():
        weights = [s[4] for s in stops_all]
        rows = []
        for i in range(cfg["students"]):
            branch = rng.choice(["05", "04", "12", "66", "02"])
            sid = f"22B81A{branch}{i:04d}"
            name = f"{rng.choice(FIRST)} {rng.choice(LAST)}"
            stop = rng.choices(stops_all, weights)[0][0]
            fee_paid = 1 if rng.random() < 0.93 else 0
            rows.append((sid, name, stop, fee_paid))
        with college._conn() as c:
            c.executemany("INSERT INTO students VALUES (?,?,?,?)", rows)

    # --- app DB ---
    init_schema()
    with session() as db:
        if db.execute("SELECT COUNT(*) FROM stops").fetchone()[0]:
            return  # already seeded
        db.executemany("INSERT INTO stops VALUES (?,?,?,?)", [s[:4] for s in stops_all])
        db.execute(
            "INSERT INTO users (username,name,password_hash,role) VALUES (?,?,?, 'admin')",
            (config.ADMIN_USERNAME, "Transport Admin", hash_password(config.ADMIN_PASSWORD)),
        )
        driver_hash = hash_password(config.DRIVER_PASSWORD)
        for i, (number, cap) in enumerate(_buses(cfg["buses"]), start=1):
            cur = db.execute("INSERT INTO buses (number, capacity) VALUES (?,?)", (number, cap))
            db.execute(
                "INSERT INTO users (username,name,password_hash,role,bus_id) VALUES (?,?,?, 'driver', ?)",
                (f"driver{i}", f"Driver {i}", driver_hash, cur.lastrowid),
            )

        # Pre-register ~75% of fee-paid students so the demo has voters.
        # (Real students register themselves through the website.)
        student_hash = hash_password(DEMO_STUDENT_PASSWORD)
        eligible = [s for s in college.all_students() if s.fee_paid]
        for s in eligible[: int(len(eligible) * 0.75)]:
            db.execute(
                "INSERT INTO users (username,name,password_hash,role) VALUES (?,?,?, 'student')",
                (s.student_id, s.name, student_hash),
            )

        # Demo savings history (marked demo; the admin can clear it before a real pilot).
        from .billing import seed_demo_savings
        seed_demo_savings(db)

        # An open poll for tomorrow's morning trip.
        now = datetime.now().replace(second=0, microsecond=0)
        db.execute(
            "INSERT INTO polls (trip_date, opens_at, closes_at) VALUES (?,?,?)",
            ((now + timedelta(days=1)).date().isoformat(),
             (now - timedelta(minutes=5)).isoformat(),
             (now + timedelta(hours=4)).isoformat()),
        )


if __name__ == "__main__":
    scale = sys.argv[sys.argv.index("--scale") + 1] if "--scale" in sys.argv else "demo"
    seed(reset="--reset" in sys.argv, scale=scale)
    n = SCALES[scale]["buses"]
    print(f"Seeded ({scale}). admin/admin123, driver1..driver{n}/driver123, students use password student123")
