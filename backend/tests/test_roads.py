import httpx

from app import config, roads


def test_falls_back_to_straight_line_when_server_unreachable(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "ROUTING_PROVIDER", "osrm")
    monkeypatch.setattr(roads, "_cache", {})
    monkeypatch.setattr(roads, "_CACHE_PATH", tmp_path / "cache.json")

    def boom(*a, **k):
        raise httpx.ConnectError("offline")

    monkeypatch.setattr(roads.httpx, "get", boom)
    pts = [(17.44, 78.50), (17.45, 78.68)]
    matrix, source = roads.distance_matrix(pts)
    assert source == "straight-line" and matrix[0][1] > 0
    route = roads.road_route(pts)
    assert route["source"] == "straight-line" and route["geometry"] == [list(p) for p in pts]


def test_parses_osrm_responses_and_caches(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "ROUTING_PROVIDER", "osrm")
    monkeypatch.setattr(roads, "_cache", {})
    monkeypatch.setattr(roads, "_CACHE_PATH", tmp_path / "cache.json")
    calls = []

    class Resp:
        def __init__(self, data): self._d = data
        def raise_for_status(self): pass
        def json(self): return self._d

    def fake_get(url, params=None, timeout=None):
        calls.append(url)
        if "/table/" in url:
            return Resp({"code": "Ok", "distances": [[0, 5000], [5200, 0]]})
        return Resp({"code": "Ok", "routes": [{"distance": 5000, "duration": 600,
                     "geometry": {"coordinates": [[78.5, 17.44], [78.6, 17.445], [78.68, 17.45]]}}]})

    monkeypatch.setattr(roads.httpx, "get", fake_get)
    pts = [(17.44, 78.50), (17.45, 78.68)]
    matrix, source = roads.distance_matrix(pts)
    assert source == "osrm" and matrix == [[0, 5.0], [5.2, 0]]  # road distances are directional
    route = roads.road_route(pts)
    assert route["km"] == 5.0 and len(route["geometry"]) == 3 and route["geometry"][0] == [17.44, 78.5]
    roads.distance_matrix(pts); roads.road_route(pts)
    assert len(calls) == 2  # second time served from cache
