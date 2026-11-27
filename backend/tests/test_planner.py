import pytest

from app.planner import BusSpec, StopDemand, plan_routes

CAMPUS = (17.45, 78.68)
STOPS = [
    StopDemand("A", "A", 17.3688, 78.5247, 20),
    StopDemand("B", "B", 17.3457, 78.5522, 15),
    StopDemand("C", "C", 17.4058, 78.5591, 25),
    StopDemand("D", "D", 17.4375, 78.4482, 10),
    StopDemand("E", "E", 17.4710, 78.5730, 8),
]


@pytest.mark.parametrize("use_ortools", [True, False])
def test_capacity_never_exceeded_and_everyone_served(use_ortools):
    buses = [BusSpec(i, f"B{i}", 52) for i in range(1, 6)]
    res = plan_routes(STOPS, buses, CAMPUS, use_ortools=use_ortools)
    caps = {b.id: b.capacity for b in buses}
    for r in res.routes:
        assert r.load == sum(s.pickup for s in r.stops)
        assert r.load <= caps[r.bus_id]
    picked = {}
    for r in res.routes:
        for s in r.stops:
            picked[s.stop_id] = picked.get(s.stop_id, 0) + s.pickup
    assert picked == {s.stop_id: s.demand for s in STOPS}
    assert not res.unserved


def test_combines_stops_into_few_buses():
    # 78 riders, 52-seat buses -> 2 buses is the minimum; solver should not use all 5
    buses = [BusSpec(i, f"B{i}", 52) for i in range(1, 6)]
    res = plan_routes(STOPS, buses, CAMPUS)
    assert res.solver == "ortools"
    assert len(res.routes) == 2


def test_large_stop_is_split_across_buses():
    stops = [StopDemand("BIG", "Big", 17.40, 78.55, 90)]
    buses = [BusSpec(1, "B1", 52), BusSpec(2, "B2", 52)]
    res = plan_routes(stops, buses, CAMPUS)
    assert sorted(r.load for r in res.routes) == [38, 52] or sum(r.load for r in res.routes) == 90
    assert all(r.load <= 52 for r in res.routes)


def test_reports_unserved_when_fleet_too_small():
    buses = [BusSpec(1, "B1", 40)]
    res = plan_routes(STOPS, buses, CAMPUS)
    assert sum(r.load for r in res.routes) <= 40
    assert sum(res.unserved.values()) == sum(s.demand for s in STOPS) - sum(r.load for r in res.routes)


def test_no_demand_means_no_buses():
    res = plan_routes([StopDemand("A", "A", 17.4, 78.5, 0)], [BusSpec(1, "B1", 52)], CAMPUS)
    assert res.routes == []
