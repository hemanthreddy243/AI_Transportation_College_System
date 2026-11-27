"""Real road distances and route shapes from OSRM (OpenStreetMap routing engine).

* `distance_matrix(points)`  -> driving km between every pair of points (one /table call)
* `road_route(points)`       -> the actual road path through points in order, with km and minutes

Results are cached on disk, so the routing server is only asked about new stop combinations.
If the server can't be reached, everything falls back to straight-line x ROAD_FACTOR, so planning
never breaks.

The default server is the free public OSRM demo (fine for development, light use only).
For production, run your own OSRM with the Telangana/India OpenStreetMap extract and set OSRM_URL.
"""
from __future__ import annotations

import json
import logging
import math
import threading

import httpx

from . import config

log = logging.getLogger(__name__)

_CACHE_PATH = config.DATA_DIR / "road_cache.json"
_lock = threading.Lock()
_cache: dict | None = None

Point = tuple[float, float]  # (lat, lng)


def _load() -> dict:
    global _cache
    if _cache is None:
        try:
            _cache = json.loads(_CACHE_PATH.read_text())
        except (OSError, ValueError):
            _cache = {}
    return _cache


def _save():
    try:
        _CACHE_PATH.write_text(json.dumps(_cache))
    except OSError as e:
        log.warning("Could not write road cache: %s", e)


def _key(kind: str, points: list[Point]) -> str:
    return kind + ":" + ";".join(f"{lat:.5f},{lng:.5f}" for lat, lng in points)


def _coords(points: list[Point]) -> str:
    return ";".join(f"{lng:.6f},{lat:.6f}" for lat, lng in points)  # OSRM wants lng,lat


def straight_km(a: Point, b: Point) -> float:
    r = 6371.0
    p1, p2 = math.radians(a[0]), math.radians(b[0])
    dp, dl = p2 - p1, math.radians(b[1] - a[1])
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(h)) * config.ROAD_FACTOR


def _osrm_enabled() -> bool:
    return config.ROUTING_PROVIDER == "osrm"


def distance_matrix(points: list[Point]) -> tuple[list[list[float]], str]:
    """Returns (km matrix, source) where source is 'osrm' or 'straight-line'."""
    n = len(points)
    fallback = [[0.0 if i == j else straight_km(points[i], points[j]) for j in range(n)] for i in range(n)]
    if not _osrm_enabled() or n < 2:
        return fallback, "straight-line"

    key = _key("table", points)
    with _lock:
        cached = _load().get(key)
    if cached:
        return cached, "osrm"
    try:
        r = httpx.get(
            f"{config.OSRM_URL}/table/v1/driving/{_coords(points)}",
            params={"annotations": "distance"}, timeout=config.OSRM_TIMEOUT_S,
        )
        r.raise_for_status()
        data = r.json()
        if data.get("code") != "Ok":
            raise ValueError(data.get("message", data.get("code")))
        km = [[(d / 1000 if d is not None else fallback[i][j]) for j, d in enumerate(row)]
              for i, row in enumerate(data["distances"])]
    except (httpx.HTTPError, ValueError, KeyError) as e:
        log.warning("OSRM table failed (%s); using straight-line distances", e)
        return fallback, "straight-line"
    with _lock:
        _load()[key] = km
        _save()
    return km, "osrm"


def road_route(points: list[Point]) -> dict:
    """Road path through `points` in order: {'geometry': [[lat,lng],...], 'km': float, 'minutes': float|None}."""
    straight = {
        "geometry": [list(p) for p in points],
        "km": round(sum(straight_km(points[i], points[i + 1]) for i in range(len(points) - 1)), 2),
        "minutes": None,
        "source": "straight-line",
    }
    if not _osrm_enabled() or len(points) < 2:
        return straight

    key = _key("route", points)
    with _lock:
        cached = _load().get(key)
    if cached:
        return cached
    try:
        r = httpx.get(
            f"{config.OSRM_URL}/route/v1/driving/{_coords(points)}",
            params={"overview": "full", "geometries": "geojson"}, timeout=config.OSRM_TIMEOUT_S,
        )
        r.raise_for_status()
        data = r.json()
        if data.get("code") != "Ok":
            raise ValueError(data.get("message", data.get("code")))
        best = data["routes"][0]
        result = {
            "geometry": [[round(lat, 6), round(lng, 6)] for lng, lat in best["geometry"]["coordinates"]],
            "km": round(best["distance"] / 1000, 2),
            # OSRM's car profile; a loaded bus with stops is slower, so scale it.
            "minutes": round(best["duration"] / 60 * config.BUS_SLOWDOWN, 1),
            "source": "osrm",
        }
    except (httpx.HTTPError, ValueError, KeyError, IndexError) as e:
        log.warning("OSRM route failed (%s); drawing straight lines", e)
        return straight
    with _lock:
        _load()[key] = result
        _save()
    return result
