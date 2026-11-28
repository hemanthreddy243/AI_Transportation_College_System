"""App database (SQLite). One short-lived connection per request."""
import sqlite3
from contextlib import contextmanager

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS stops (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    lat REAL NOT NULL,
    lng REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS users (
    username TEXT PRIMARY KEY,          -- student_id for students
    name TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('student','admin','driver')),
    bus_id INTEGER                      -- drivers only
);
CREATE TABLE IF NOT EXISTS buses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    number TEXT NOT NULL UNIQUE,
    capacity INTEGER NOT NULL CHECK (capacity > 0),
    active INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS polls (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trip_date TEXT NOT NULL,            -- YYYY-MM-DD the buses run
    opens_at TEXT NOT NULL,             -- local ISO datetime
    closes_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS votes (
    poll_id INTEGER NOT NULL REFERENCES polls(id),
    username TEXT NOT NULL REFERENCES users(username),
    stop_id TEXT NOT NULL,
    going INTEGER NOT NULL,
    voted_at TEXT NOT NULL,
    PRIMARY KEY (poll_id, username)
);
CREATE TABLE IF NOT EXISTS plans (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    poll_id INTEGER NOT NULL UNIQUE REFERENCES polls(id),
    created_at TEXT NOT NULL,
    solver TEXT NOT NULL,
    total_km REAL NOT NULL,
    buses_used INTEGER NOT NULL,
    fleet_size INTEGER NOT NULL,
    riders INTEGER NOT NULL,
    unserved_json TEXT NOT NULL,
    ai_summary TEXT
);
CREATE TABLE IF NOT EXISTS routes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    plan_id INTEGER NOT NULL REFERENCES plans(id) ON DELETE CASCADE,
    bus_id INTEGER NOT NULL REFERENCES buses(id),
    load INTEGER NOT NULL,
    km REAL NOT NULL,
    stops_json TEXT NOT NULL            -- ordered [{stop_id, pickup}]
);
CREATE TABLE IF NOT EXISTS assignments (
    poll_id INTEGER NOT NULL,
    username TEXT NOT NULL,
    bus_id INTEGER NOT NULL,
    PRIMARY KEY (poll_id, username)
);
CREATE TABLE IF NOT EXISTS bus_locations (
    bus_id INTEGER PRIMARY KEY,
    lat REAL NOT NULL,
    lng REAL NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS bus_positions (     -- GPS history, for audits and replaying trips
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    bus_id INTEGER NOT NULL,
    lat REAL NOT NULL,
    lng REAL NOT NULL,
    ts TEXT NOT NULL,
    progress_m REAL
);
CREATE INDEX IF NOT EXISTS idx_bus_positions ON bus_positions (bus_id, ts);
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS payments (           -- transport-fee payments (demo gateway for now)
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL,
    academic_year TEXT NOT NULL,
    amount INTEGER NOT NULL,
    method TEXT NOT NULL,
    status TEXT NOT NULL,
    reference TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS trip_savings (       -- what each published trip saved (basis of platform fee)
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    poll_id INTEGER,
    trip_date TEXT NOT NULL,
    riders INTEGER NOT NULL,
    buses_used INTEGER NOT NULL,
    baseline_buses INTEGER NOT NULL,
    actual_km REAL NOT NULL,
    baseline_km REAL NOT NULL,
    diesel_price REAL NOT NULL,
    litres_saved REAL NOT NULL,
    rupees_saved INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    demo INTEGER NOT NULL DEFAULT 0
);
"""


def connect() -> sqlite3.Connection:
    # FastAPI may close a request's connection on a different worker thread than it opened it.
    # Each connection is still used by one request only, so this is safe.
    conn = sqlite3.connect(config.APP_DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


MIGRATIONS = [  # (table, column, definition) added after the first release
    ("routes", "geometry_json", "TEXT"),       # road path [[lat,lng],...]
    ("routes", "minutes", "REAL"),             # estimated drive time
    ("plans", "distance_source", "TEXT"),      # 'osrm' or 'straight-line'
    ("bus_locations", "route_id", "INTEGER"),  # route the fix was matched against
    ("bus_locations", "progress_m", "REAL"),   # metres travelled along the route
    ("bus_locations", "speed_mps", "REAL"),    # smoothed speed
    ("bus_locations", "heading", "REAL"),
    ("bus_locations", "offset_m", "REAL"),     # distance from the planned route line
    ("bus_locations", "accuracy_m", "REAL"),   # GPS accuracy reported by the phone
    ("payments", "gateway", "TEXT"),           # 'demo' or 'razorpay'
    ("payments", "order_id", "TEXT"),          # Razorpay order id (order_...)
    ("payments", "payment_id", "TEXT"),        # Razorpay payment id (pay_...)
]


def init_schema():
    with connect() as c:
        c.executescript(SCHEMA)
        for table, column, definition in MIGRATIONS:
            cols = {r["name"] for r in c.execute(f"PRAGMA table_info({table})")}
            if column not in cols:
                c.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


@contextmanager
def session():
    conn = connect()
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def get_db():
    """FastAPI dependency."""
    with session() as conn:
        yield conn
