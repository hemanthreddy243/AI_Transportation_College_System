from app.tracking import RouteTrack

# A straight east-west road ~11 km long with two stops, ending at "campus"
GEOM = [[17.40, 78.50], [17.40, 78.55], [17.40, 78.60]]
STOPS = [{"id": "A", "name": "A", "lat": 17.40, "lng": 78.50}, {"id": "B", "name": "B", "lat": 17.4003, "lng": 78.55}]


def test_stops_are_located_along_the_route():
    t = RouteTrack(GEOM, STOPS, planned_minutes=20)
    assert t.stops[0]["along_m"] == 0
    assert abs(t.stops[1]["along_m"] - t.total_m / 2) < 50
    assert 10_000 < t.total_m < 11_500


def test_projection_snaps_noisy_fix_and_measures_offset():
    t = RouteTrack(GEOM, STOPS, planned_minutes=20)
    p = t.project(17.4001, 78.525)  # ~11 m north of the road, a quarter of the way
    assert abs(p.along_m - t.total_m / 4) < 50
    assert p.offset_m < 20
    far = t.project(17.41, 78.525)  # ~1.1 km away
    assert far.offset_m > 1000


def test_projection_never_goes_far_backwards():
    t = RouteTrack(GEOM, STOPS, planned_minutes=20)
    p = t.project(17.40, 78.51, min_along=t.total_m / 2)
    assert p.along_m >= t.total_m / 2 - 200


def test_window_stops_snapping_to_a_later_part_of_a_winding_route():
    # U-shaped route: east 5 km, north 1 km, back west. A fix 300 m north of the first leg is
    # close to the *return* leg too - but the bus can't be there yet.
    geom = [[17.40, 78.50], [17.40, 78.55], [17.409, 78.55], [17.409, 78.50]]
    t = RouteTrack(geom, [{"id": "A", "name": "A", "lat": 17.40, "lng": 78.50}], planned_minutes=20)
    fix = (17.4065, 78.51)  # ~720 m north of leg 1, ~280 m south of the return leg
    unlimited = t.project(*fix, min_along=1000, window_m=None)
    limited = t.project(*fix, min_along=1000, window_m=800)
    assert unlimited.along_m > 6000          # snaps onto the return leg
    assert limited.along_m <= 1800 and limited.offset_m > 250  # stays near the bus -> off route
