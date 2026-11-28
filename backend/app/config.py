"""Central configuration. Everything can be overridden with environment variables."""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def _load_dotenv(path: Path):
    """Read KEY=VALUE lines from backend/.env (git-ignored). Real environment variables win."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_dotenv(BASE_DIR / ".env")

DATA_DIR = Path(os.getenv("DATA_DIR", BASE_DIR / "data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)

# App database (users, polls, votes, plans, tracking)
APP_DB_PATH = Path(os.getenv("APP_DB_PATH", DATA_DIR / "app.db"))
# Mock of the college's existing student database (read-only from the app's point of view)
COLLEGE_DB_PATH = Path(os.getenv("COLLEGE_DB_PATH", DATA_DIR / "college.db"))

def _jwt_secret() -> str:
    if os.getenv("JWT_SECRET"):
        return os.environ["JWT_SECRET"]
    # Dev: persist a random secret so logins survive restarts. Set JWT_SECRET in production.
    path = DATA_DIR / ".jwt_secret"
    if not path.exists():
        import secrets
        path.write_text(secrets.token_hex(32))
    return path.read_text().strip()


JWT_SECRET = _jwt_secret()
JWT_TTL_HOURS = int(os.getenv("JWT_TTL_HOURS", "72"))

ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin123")
DRIVER_PASSWORD = os.getenv("DRIVER_PASSWORD", "driver123")

# Campus = where every morning route ends
CAMPUS_NAME = os.getenv("CAMPUS_NAME", "Campus")
CAMPUS_LAT = float(os.getenv("CAMPUS_LAT", "17.4500"))
CAMPUS_LNG = float(os.getenv("CAMPUS_LNG", "78.6800"))

# Road routing: "osrm" = real road distances/shapes, "straight" = straight-line estimate (offline/tests)
ROUTING_PROVIDER = os.getenv("ROUTING_PROVIDER", "osrm")
OSRM_URL = os.getenv("OSRM_URL", "https://router.project-osrm.org").rstrip("/")
OSRM_TIMEOUT_S = float(os.getenv("OSRM_TIMEOUT_S", "15"))
BUS_SLOWDOWN = float(os.getenv("BUS_SLOWDOWN", "1.3"))  # bus vs car travel time

# Planner tuning
ROAD_FACTOR = float(os.getenv("ROAD_FACTOR", "1.35"))  # straight-line km -> approx road km (fallback only)
BUS_FIXED_COST_KM = float(os.getenv("BUS_FIXED_COST_KM", "40"))  # cost of putting one more bus on the road, in km-equivalent
MAX_ROUTE_KM = float(os.getenv("MAX_ROUTE_KM", "75"))  # longest route a single bus may drive
SOLVER_TIME_LIMIT_S = int(os.getenv("SOLVER_TIME_LIMIT_S", "5"))
BUS_KM_PER_LITRE = float(os.getenv("BUS_KM_PER_LITRE", "4.0"))

# AI explainer
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-opus-5-5")
AI_ENABLED = os.getenv("AI_ENABLED", "1") == "1"

APP_TIMEZONE = os.getenv("APP_TIMEZONE", "Asia/Kolkata")  # college local time (servers run on UTC)
SEED_SCALE = os.getenv("SEED_SCALE", "demo")  # demo data created on first start

# Payments: Razorpay. Leave the keys empty to use the built-in demo checkout.
# Test keys (rzp_test_...) use Razorpay's real checkout without moving real money.
# In production these must be the COLLEGE's own Razorpay account keys, so fees settle to the college.
RAZORPAY_KEY_ID = os.getenv("RAZORPAY_KEY_ID", "")
RAZORPAY_KEY_SECRET = os.getenv("RAZORPAY_KEY_SECRET", "")
RAZORPAY_WEBHOOK_SECRET = os.getenv("RAZORPAY_WEBHOOK_SECRET", "")
RAZORPAY_API = os.getenv("RAZORPAY_API", "https://api.razorpay.com/v1")
COLLEGE_DISPLAY_NAME = os.getenv("COLLEGE_DISPLAY_NAME", "College Transport")

CORS_ORIGINS = os.getenv("CORS_ORIGINS", "http://localhost:5173").split(",")
