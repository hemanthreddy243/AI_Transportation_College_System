"""The college's local time. Servers (e.g. Render) run on UTC, but voting windows and trip
dates are entered and shown in the college's time zone, so all comparisons use local time."""
from datetime import date, datetime
from zoneinfo import ZoneInfo

from . import config

_TZ = ZoneInfo(config.APP_TIMEZONE)


def now() -> datetime:
    """Current local time in the college's time zone (naive, to match stored values)."""
    return datetime.now(_TZ).replace(tzinfo=None)


def now_iso() -> str:
    return now().replace(microsecond=0).isoformat()


def today() -> date:
    return now().date()
