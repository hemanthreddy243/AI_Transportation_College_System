"""Route planner: decides which stops each bus covers, in what order.

It solves a Capacitated Vehicle Routing Problem (CVRP) with Google OR-Tools:
  * every stop's demand = number of students who voted "yes" for that stop
  * each bus has a seat capacity that must never be exceeded
  * every bus that leaves the depot carries a fixed cost, so the solver prefers
    combining nearby stops into fewer, fuller buses (the fuel saving)
  * routes are "open" pickups: a bus starts at its first stop and ends at campus
  * a stop with more students than a bus can carry is split across buses

Distances are real driving distances from OSRM (see roads.py), falling back to
straight-line estimates when the routing server is unreachable.
If OR-Tools is not available, a simple greedy heuristic is used instead.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from . import config
from .roads import distance_matrix


@dataclass
class StopDemand:
    stop_id: str
    name: str
    lat: float
    lng: float
    demand: int


@dataclass
class BusSpec:
    id: int
    number: str
    capacity: int


@dataclass
class RouteStop:
    stop_id: str
    pickup: int


@dataclass
class Route:
    bus_id: int
    stops: list[RouteStop]
    load: int
    km: float


@dataclass
class PlanResult:
    routes: list[Route]
    unserved: dict[str, int] = field(default_factory=dict)  # stop_id -> students left without a seat
    solver: str = "ortools"
    distance_source: str = "straight-line"

    @property
    def total_km(self) -> float:
        return round(sum(r.km for r in self.routes), 2)


KmFn = Callable[[tuple[float, float], tuple[float, float]], float]


def make_km_fn(stops: list[StopDemand], campus: tuple[float, float]) -> tuple[KmFn, str]:
    """One distance-matrix call for all stops + campus; returns a lookup (a, b) -> driving km."""
    points = list(dict.fromkeys([(s.lat, s.lng) for s in stops] + [campus]))
    matrix, source = distance_matrix(points)
    index = {p: i for i, p in enumerate(points)}
    return (lambda a, b: matrix[index[a]][index[b]]), source


def _route_km(points: list[tuple[float, float]], campus: tuple[float, float], km: KmFn) -> float:
    path = points + [campus]
    return round(sum(km(path[i], path[i + 1]) for i in range(len(path) - 1)), 2)


def _split_into_chunks(stops: list[StopDemand], max_cap: int):
    """A stop with more students than the largest bus becomes several pickup 'chunks'."""
    chunks = []  # (stop, count)
    for s in stops:
        remaining = s.demand
        while remaining > 0:
            take = min(remaining, max_cap)
            chunks.append((s, take))
            remaining -= take
    return chunks


def _merge(route_chunks, campus, bus_id, km: KmFn) -> Route:
    merged: list[RouteStop] = []
    coords: list[tuple[float, float]] = []
    for stop, count in route_chunks:
        if merged and merged[-1].stop_id == stop.stop_id:
            merged[-1].pickup += count
        else:
            merged.append(RouteStop(stop.stop_id, count))
            coords.append((stop.lat, stop.lng))
    return Route(bus_id=bus_id, stops=merged, load=sum(c for _, c in route_chunks), km=_route_km(coords, campus, km))


def plan_routes(
    stops: list[StopDemand],
    buses: list[BusSpec],
    campus: tuple[float, float] = (config.CAMPUS_LAT, config.CAMPUS_LNG),
    use_ortools: bool = True,
    km: KmFn | None = None,
) -> PlanResult:
    stops = [s for s in stops if s.demand > 0]
    buses = [b for b in buses if b.capacity > 0]
    if not stops:
        return PlanResult(routes=[], solver="none")
    if not buses:
        return PlanResult(routes=[], unserved={s.stop_id: s.demand for s in stops}, solver="none")

    source = "custom"
    if km is None:
        km, source = make_km_fn(stops, campus)
    result = None
    if use_ortools:
        try:
            result = _plan_ortools(stops, buses, campus, km)
        except ImportError:
            pass
    result = result or _plan_greedy(stops, buses, campus, km)
    result.distance_source = source
    return result


def _plan_ortools(stops, buses, campus, km: KmFn) -> PlanResult:
    from ortools.constraint_solver import pywrapcp, routing_enums_pb2

    max_cap = max(b.capacity for b in buses)
    chunks = _split_into_chunks(stops, max_cap)

    # Node 0 = virtual start (free to leave from), node 1 = campus (every bus ends here), 2.. = pickups
    START, CAMPUS = 0, 1
    coords = [None, campus] + [(s.lat, s.lng) for s, _ in chunks]
    demands = [0, 0] + [c for _, c in chunks]
    n = len(coords)
    FORBIDDEN = 10**9

    dist = [[0] * n for _ in range(n)]
    for i in range(n):
        for j in range(n):
            if i == j:
                continue
            if i == START:
                dist[i][j] = 0  # a bus "appears" at its first stop
            elif j == START or i == CAMPUS:
                dist[i][j] = FORBIDDEN  # never return to start, never leave campus
            else:
                dist[i][j] = int(km(coords[i], coords[j]) * 1000)  # road metres

    num_vehicles = len(buses)
    manager = pywrapcp.RoutingIndexManager(n, num_vehicles, [START] * num_vehicles, [CAMPUS] * num_vehicles)
    routing = pywrapcp.RoutingModel(manager)

    def dist_cb(from_index, to_index):
        return dist[manager.IndexToNode(from_index)][manager.IndexToNode(to_index)]

    transit = routing.RegisterTransitCallback(dist_cb)
    routing.SetArcCostEvaluatorOfAllVehicles(transit)
    routing.AddDimension(transit, 0, int(config.MAX_ROUTE_KM * 1000), True, "Distance")

    def demand_cb(from_index):
        return demands[manager.IndexToNode(from_index)]

    demand_idx = routing.RegisterUnaryTransitCallback(demand_cb)
    routing.AddDimensionWithVehicleCapacity(demand_idx, 0, [b.capacity for b in buses], True, "Capacity")

    # Each extra bus on the road costs fuel + a driver -> encourages combining stops.
    for v in range(num_vehicles):
        routing.SetFixedCostOfVehicle(int(config.BUS_FIXED_COST_KM * 1000), v)

    # Allow dropping a pickup only when it is impossible to serve (not enough seats / too far).
    for node in range(2, n):
        routing.AddDisjunction([manager.NodeToIndex(node)], 10_000_000 * demands[node])

    params = pywrapcp.DefaultRoutingSearchParameters()
    params.first_solution_strategy = routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC
    params.local_search_metaheuristic = routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH
    params.time_limit.seconds = config.SOLVER_TIME_LIMIT_S

    solution = routing.SolveWithParameters(params)
    if solution is None:
        return None

    routes: list[Route] = []
    served = [False] * n
    for v in range(num_vehicles):
        idx = routing.Start(v)
        seq = []
        while not routing.IsEnd(idx):
            node = manager.IndexToNode(idx)
            if node >= 2:
                seq.append(chunks[node - 2])
                served[node] = True
            idx = solution.Value(routing.NextVar(idx))
        if seq:
            routes.append(_merge(seq, campus, buses[v].id, km))

    unserved: dict[str, int] = {}
    for node in range(2, n):
        if not served[node]:
            s, c = chunks[node - 2]
            unserved[s.stop_id] = unserved.get(s.stop_id, 0) + c
    return PlanResult(routes=routes, unserved=unserved, solver="ortools")


def _plan_greedy(stops, buses, campus, km: KmFn) -> PlanResult:
    """Fallback: start each bus at the farthest unserved stop, then keep adding the nearest stop that fits."""
    max_cap = max(b.capacity for b in buses)
    pending = list(_split_into_chunks(stops, max_cap))
    routes: list[Route] = []
    for bus in sorted(buses, key=lambda b: -b.capacity):
        if not pending:
            break
        pending.sort(key=lambda sc: km((sc[0].lat, sc[0].lng), campus), reverse=True)
        seq, load = [], 0
        current = None
        while True:
            fits = [sc for sc in pending if load + sc[1] <= bus.capacity]
            if current is not None:
                fits = [
                    sc for sc in fits
                    if _route_km([(s.lat, s.lng) for s, _ in seq] + [(sc[0].lat, sc[0].lng)], campus, km) <= config.MAX_ROUTE_KM
                ]
            if not fits:
                break
            nxt = fits[0] if current is None else min(
                fits, key=lambda sc: km(current, (sc[0].lat, sc[0].lng))
            )
            pending.remove(nxt)
            seq.append(nxt)
            load += nxt[1]
            current = (nxt[0].lat, nxt[0].lng)
        if seq:
            routes.append(_merge(seq, campus, bus.id, km))

    unserved: dict[str, int] = {}
    for s, c in pending:
        unserved[s.stop_id] = unserved.get(s.stop_id, 0) + c
    return PlanResult(routes=routes, unserved=unserved, solver="greedy")
