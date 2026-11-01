import pytest

import hk_transport.journey as j


def stop(stop_id, name, latitude, longitude):
    return {
        "stop": stop_id,
        "name_zh": name,
        "name_en": name,
        "latitude": latitude,
        "longitude": longitude,
    }


def td_row(
    company,
    route,
    route_id,
    seq,
    stop_id,
    name,
    latitude,
    longitude,
    journey_time_minutes=None,
):
    return {
        "company": company,
        "route": route,
        "route_id": route_id,
        "route_seq": 1,
        "route_type": 1,
        "service_mode": "R",
        "special_type": 0,
        "seq": seq,
        "stop": stop_id,
        "name_zh": name,
        "name_en": name,
        "latitude": latitude,
        "longitude": longitude,
        "pick_drop": 3,
        "fare": 5.0,
        "journey_time_minutes": journey_time_minutes,
    }


GMB_STOPS = [
    stop("G1", "小巴一站", 22.0300, 114.0300),
    stop("G2", "小巴二站", 22.0900, 114.0900),
]
BUS_ROWS = [
    td_row("KMB", "R1", 100, 1, "B1", "巴士一站", 22.0000, 114.0000),
    td_row("KMB", "R1", 100, 2, "B2", "巴士二站", 22.0100, 114.0100),
    td_row("KMB", "R1", 100, 3, "B3", "巴士三站", 22.0300, 114.0300),
]
GMB_ROWS = [
    {
        "route_id": 900,
        "route": "G1",
        "route_seq": 1,
        "service_mode": "R",
        "special_type": 0,
        "seq": 1,
        "stop": "G1",
    },
    {
        "route_id": 900,
        "route": "G1",
        "route_seq": 1,
        "service_mode": "R",
        "special_type": 0,
        "seq": 2,
        "stop": "G2",
    },
]
MTR_ROWS = [
    {"line_code": "TWL", "direction": "DT", "id": "1", "sequence": 1, "name_zh": "一站"},
    {"line_code": "TWL", "direction": "DT", "id": "2", "sequence": 2, "name_zh": "二站"},
]
TRUNK_ROWS = [
    td_row("KMB", "T1", 501, 1, "T1", "總站", 22.0000, 114.0000),
    td_row("KMB", "T1", 501, 2, "T2", "中站", 22.0100, 114.0100),
    td_row("KMB", "T1", 501, 3, "T3", "終站", 22.0200, 114.0200),
    td_row("KMB", "T2", 502, 1, "T2", "中站", 22.0100, 114.0100),
    td_row("KMB", "T2", 502, 2, "T3", "終站", 22.0200, 114.0200),
]
EXITS = {
    "retrieved_at": "2026-10-30T00:00:00+08:00",
    "exits": [
        {
            "station_zh": "一站",
            "station_ids": ["1"],
            "latitude": 22.0200,
            "longitude": 114.0200,
            "exit": "A",
        },
        {
            "station_zh": "二站",
            "station_ids": ["2"],
            "latitude": 22.0300,
            "longitude": 114.0300,
            "exit": "A",
        },
    ]
}


def envelope(rows):
    return {
        "data": rows,
        "dataset_id": "test",
        "endpoint": "test",
        "retrieved_at": "2026-10-30T00:00:00+08:00",
        "data_at": None,
        "update_frequency": "daily",
        "note": None,
    }


@pytest.fixture
def wired(monkeypatch):
    monkeypatch.setattr(j.bus_core, "td_bus_route_stops", lambda: envelope(BUS_ROWS))
    monkeypatch.setattr(j.minibus_core, "gmb_stops", lambda: envelope(GMB_STOPS))
    monkeypatch.setattr(j.minibus_core, "gmb_route_stops", lambda: envelope(GMB_ROWS))
    monkeypatch.setattr(j.mtr_core, "lines_and_stations", lambda: envelope(MTR_ROWS))
    monkeypatch.setattr(j.tram_core, "tram_stops", lambda: envelope([]))
    monkeypatch.setattr(j.ferry_core, "ferry_stops", lambda: envelope([]))
    monkeypatch.setattr(j.exits, "_load", lambda: EXITS)
    monkeypatch.setattr(
        j.pedroute,
        "walk_route",
        lambda *args: {
            "data": {"found": True, "metres": 123.0, "minutes": 2.0},
            "note": None,
        },
    )
    j.clear_cache()
    yield
    j.clear_cache()


def test_one_search_covers_a_bus_and_a_minibus(wired):
    result = j.journey("巴士一站", "小巴二站")
    option = result["data"]["options"][0]
    rides = [leg for leg in option["legs"] if leg["type"] == "ride"]
    assert [leg["mode"] for leg in rides] == ["bus", "minibus"]
    assert option["transfers"] == 1
    assert rides[1]["route"] == "G1"


def _walk_leg(metres=500):
    return {
        "type": "walk",
        "metres": metres,
        "from": {"name_zh": "甲", "latitude": 22.0, "longitude": 114.0},
        "to": {"name_zh": "乙", "latitude": 22.001, "longitude": 114.001},
    }


def test_walk_legs_are_re_priced_by_the_pedestrian_network(wired):
    legs = [_walk_leg()]
    j._price_walks(legs, j._WalkBudget(calls=5), [])
    assert legs[0]["metres"] == 123
    assert legs[0]["minutes"] == 2.0
    assert legs[0]["straight_line_metres"] == 500


def test_a_walk_with_no_route_is_marked_estimated(wired, monkeypatch):
    monkeypatch.setattr(
        j.pedroute,
        "walk_route",
        lambda *args: {"data": {"found": False, "metres": None, "minutes": None}, "note": "x"},
    )
    legs = [_walk_leg()]
    j._price_walks(legs, j._WalkBudget(calls=5), [])
    assert legs[0]["estimated"] is True
    assert legs[0]["metres"] == 500


def test_a_direct_ride_is_zero_transfers(wired):
    option = j.journey("巴士一站", "巴士二站")["data"]["options"][0]
    assert option["transfers"] == 0
    assert option["stops"] == 1


def test_the_note_names_bus_and_minibus_separately(wired):
    note = j.journey("巴士一站", "巴士二站")["note"]
    assert f"巴士 {j.COST['board_minutes']['bus']:g}" in note
    assert f"小巴 {j.COST['board_minutes']['minibus']:g}" in note


def test_a_duplicate_does_not_ban_every_alight_on_the_route(wired, monkeypatch):
    """The second option may reuse the trunk route and alight one stop earlier.

    The old duplicate handling banned the whole (mode, key) trip, so the
    alternative that shares the first ride disappeared with it.
    """
    monkeypatch.setattr(j.bus_core, "td_bus_route_stops", lambda: envelope(TRUNK_ROWS))
    j.clear_cache()
    result = j.journey("總站", "終站", options=2)
    route_sets = [
        [leg["route"] for leg in option["legs"] if leg["type"] == "ride"]
        for option in result["data"]["options"]
    ]
    assert ["T1"] in route_sets
    assert ["T1", "T2"] in route_sets


def test_search_cost_is_internal(wired):
    option = j.journey("巴士一站", "巴士二站")["data"]["options"][0]
    assert "search_cost" not in option
    assert "score" in option


def test_an_unreachable_place_says_so(wired, monkeypatch):
    monkeypatch.setattr(j._places, "place", lambda text, points: (None, f"找不到地方：{text}"))
    result = j.journey("巴士一站", "火星")
    assert result["data"] is None
    assert "找不到地方" in result["note"]


def test_the_note_states_the_weighting_and_the_scope(wired):
    note = j.journey("巴士一站", "巴士二站")["note"]
    assert "轉車" in note
    assert "電車" in note
    assert "地政總署" in note


def test_the_answer_carries_its_datasets_and_endpoints(wired):
    result = j.journey("巴士一站", "巴士二站")
    assert result["dataset_id"]
    assert result["endpoint"]
    assert result["sources"]


def test_a_raw_stop_id_resolves_inside_the_graph(wired):
    result = j.journey("B1", "B3")
    assert result["data"] is not None
    assert result["data"]["origin"]["resolved_as"] == "stop"
    assert result["data"]["origin"]["name_zh"] == "巴士一站"


def test_a_crowded_corridor_still_links_the_station(monkeypatch):
    """Twenty bus poles must not crowd out the station 120 m away."""
    points = {}
    for i in range(25):
        points[f"bus:{i}"] = {
            "point": f"bus:{i}",
            "mode": "bus",
            "stop": str(i),
            "name_zh": f"bus{i}",
            "name_en": None,
            "latitude": 22.0,
            "longitude": 114.0 + i * 0.00001,
        }
    points["mtr:1"] = {
        "point": "mtr:1",
        "mode": "mtr",
        "stop": "1",
        "name_zh": "站",
        "name_en": None,
        "latitude": 22.0011,
        "longitude": 114.0,
    }
    adjacency = [[] for _ in range(len(points))]
    index = {key: n for n, key in enumerate(points)}
    j._walk_links(points, adjacency, index, j._units())
    linked = [t for t, w, kind, meta in adjacency[index["mtr:1"]] if kind == "walk"]
    assert linked, "the station is 120 m away and must not be crowded out"
    assert len(linked) <= j._LINK_NEIGHBOURS


def test_every_ride_covers_at_least_one_stop(wired):
    option = j.journey("巴士一站", "巴士三站")["data"]["options"][0]
    rides = [leg for leg in option["legs"] if leg["type"] == "ride"]
    assert rides
    assert all(leg["stops"] >= 1 for leg in rides)


def test_the_cost_policy_covers_every_mode_in_the_graph(wired):
    modes = {mode for (mode, _key) in j._graph()["labels"]}
    assert modes
    assert modes <= set(j.COST["board_minutes"])
    assert modes <= set(j.COST["speed_kmh"])
    assert modes <= set(j.COST["dwell_minutes"])


def test_the_policy_ranks_a_ferry_wait_above_a_train_wait():
    boarding = j.COST["board_minutes"]
    assert boarding["ferry"] > boarding["bus"] > boarding["mtr"]
    assert j.COST["speed_kmh"]["mtr"] > j.COST["speed_kmh"]["bus"]
    assert j.COST["walk_minutes_per_km"] > 0


def test_penalty_keys_match_board_meta(wired, monkeypatch):
    """Route diversification must pass (mode, key), the same shape as board meta."""
    seen_penalties = []
    real_dijkstra = j._dijkstra

    def recording(*args, **kwargs):
        penalty = args[5] if len(args) > 5 else kwargs.get("penalty")
        seen_penalties.append(set(penalty or set()))
        return real_dijkstra(*args, **kwargs)

    monkeypatch.setattr(j, "_dijkstra", recording)
    j.journey("巴士一站", "巴士三站", options=2)
    assert len(seen_penalties) >= 2
    assert seen_penalties[1]
    assert all(
        isinstance(item, tuple)
        and len(item) == 2
        and item[0] in j.COST["board_minutes"]
        for item in seen_penalties[1]
    )


def test_unknown_mode_board_falls_back_to_bus():
    units = j._units()
    assert j._ride_cost(units, "spaceship", 1000) == j._ride_cost(units, "bus", 1000)


def test_a_failed_walk_retry_keeps_the_first_options(wired, monkeypatch):
    calls = {"n": 0}

    def fake_search(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            return [
                {
                    "transfers": 0,
                    "overnight_hint": False,
                    "stops": 1,
                    "walk_metres": 10,
                    "search_cost": 1000,
                    "legs": [
                        {
                            "type": "walk",
                            "metres": 10,
                            "from": {"name_zh": "A", "latitude": 22.0, "longitude": 114.0},
                            "to": {"name_zh": "B", "latitude": 22.001, "longitude": 114.001},
                            "from_point": "bus:1",
                            "to_point": "bus:2",
                        },
                        {
                            "type": "ride",
                            "mode": "bus",
                            "trip": ("bus", ("KMB", 1, 1, "R", 0)),
                            "route": "1",
                            "overnight": False,
                            "operator": "KMB",
                            "board": "巴士一站",
                            "alight": "巴士二站",
                            "stops": 1,
                            "board_point": "bus:1",
                            "alight_point": "bus:2",
                        },
                    ],
                }
            ]
        return []

    def fake_price(legs, budget, sources):
        # Force a retry by reporting a bad mid-journey walk once.
        return {
            "pairs": {frozenset(("bus:1", "bus:2"))},
            "origins": set(),
            "dests": set(),
        }

    monkeypatch.setattr(j, "_search", fake_search)
    monkeypatch.setattr(j, "_price_walks", fake_price)
    result = j.journey("巴士一站", "巴士二站")
    assert result["data"] is not None
    assert result["data"]["options"]
    assert calls["n"] == 2


def test_walk_cache_hit_does_not_call_pedroute_twice(wired, monkeypatch):
    calls = {"n": 0}
    result = {
        "dataset_id": "test-walk",
        "endpoint": "https://example.test/walk",
        "retrieved_at": "2026-10-30T00:00:00+08:00",
        "data_at": None,
        "update_frequency": "realtime",
        "data": {"found": True, "metres": 200.0, "minutes": 3.0},
        "note": None,
    }

    def counting_walk(*args):
        calls["n"] += 1
        return result

    monkeypatch.setattr(j.pedroute, "walk_route", counting_walk)
    j.clear_cache()
    legs = [_walk_leg(400)]
    # give from/to points so the leg is a normal mid walk
    legs[0]["from_point"] = "bus:a"
    legs[0]["to_point"] = "bus:b"
    sources = []
    j._price_walks(legs, j._WalkBudget(calls=5), sources)
    assert calls["n"] == 1
    assert len(sources) == 1
    legs2 = [_walk_leg(400)]
    legs2[0]["from_point"] = "bus:a"
    legs2[0]["to_point"] = "bus:b"
    sources2 = []
    j._price_walks(legs2, j._WalkBudget(calls=5), sources2)
    assert calls["n"] == 1
    assert legs2[0]["metres"] == 200
    # A cache hit must still cite the source it came from.
    assert len(sources2) == 1
    assert sources2[0]["retrieved_at"] == "2026-10-30T00:00:00+08:00"


def test_a_failed_walk_is_not_cached(wired, monkeypatch):
    calls = {"n": 0}

    def failing_walk(*args):
        calls["n"] += 1
        raise RuntimeError("network")

    monkeypatch.setattr(j.pedroute, "walk_route", failing_walk)
    j.clear_cache()
    for _ in range(2):
        legs = [_walk_leg(400)]
        legs[0]["from_point"] = "bus:a"
        legs[0]["to_point"] = "bus:b"
        j._price_walks(legs, j._WalkBudget(calls=5), [])
        assert legs[0]["estimated"] is True
    assert calls["n"] == 2


def test_ride_cost_uses_distance_and_speed():
    units = j._units()
    short = j._ride_cost(units, "mtr", 1000)
    long = j._ride_cost(units, "mtr", 2000)
    assert long > short
    # same metres: faster mode costs less travel (dwell still applies)
    assert j._ride_cost(units, "mtr", 5000) < j._ride_cost(units, "bus", 5000)


def test_mtr_line_speeds_differ():
    units = j._units()
    assert j._ride_cost(units, "mtr", 20000, line="AEL") < j._ride_cost(
        units, "mtr", 20000, line="ISL"
    )
    assert j._ride_cost(units, "mtr", 20000, line="EAL") < j._ride_cost(
        units, "mtr", 20000
    )


def test_a_bus_hop_uses_the_published_whole_route_time():
    units = j._units()
    # 60 minutes for 10 km: a 1 km hop is 6 minutes, with no extra dwell.
    assert j._route_hop_cost(units, 60.0, 1000, 10000) == 6000
    assert j._route_hop_cost(units, None, 1000, 10000) is None
    assert j._route_hop_cost(units, 60.0, 1000, 0) is None


def test_a_fast_published_bus_route_beats_a_slow_one(wired, monkeypatch):
    rows = [
        td_row("KMB", "F", 601, 1, "A", "甲站", 22.0, 114.0, 10.0),
        td_row("KMB", "F", 601, 2, "B", "乙站", 22.01, 114.01, 10.0),
        td_row("KMB", "S", 602, 1, "A", "甲站", 22.0, 114.0, 60.0),
        td_row("KMB", "S", 602, 2, "B", "乙站", 22.01, 114.01, 60.0),
    ]
    monkeypatch.setattr(j.bus_core, "td_bus_route_stops", lambda: envelope(rows))
    j.clear_cache()
    rides = [
        leg
        for leg in j.journey("甲站", "乙站")["data"]["options"][0]["legs"]
        if leg["type"] == "ride"
    ]
    assert rides[0]["route"] == "F"


def test_consecutive_rides_on_the_same_route_merge():
    """A direction change at a shared stop is not a transfer."""
    legs = [
        {
            "type": "ride",
            "mode": "mtr",
            "route": "東鐵線",
            "operator": "MTR",
            "board": "落馬洲",
            "alight": "旺角東",
            "board_point": "mtr:1",
            "alight_point": "mtr:2",
            "stops": 10,
        },
        {
            "type": "ride",
            "mode": "mtr",
            "route": "東鐵線",
            "operator": "MTR",
            "board": "旺角東",
            "alight": "紅磡",
            "board_point": "mtr:2",
            "alight_point": "mtr:3",
            "stops": 1,
        },
    ]
    merged = j._merge_same_route(legs)
    assert len(merged) == 1
    assert merged[0]["stops"] == 11
    assert merged[0]["alight"] == "紅磡"


def test_the_peak_tram_is_kept_out_of_the_journey_graph(monkeypatch):
    """The exclusion is deliberate, so a future change has to argue with a test."""
    def boom():
        raise AssertionError("journey must not load the Peak Tram")

    monkeypatch.setattr(j.tram_core, "peak_tram_stops", boom)
    modes = {mode for (mode, _key) in j._graph()["labels"]}
    assert "peaktram" not in modes
    assert "tram" in modes


@pytest.mark.parametrize(
    ("route", "overnight"),
    [
        ("N241", True),
        ("N8P", True),
        ("NA43", True),
        ("NB73", True),
        ("A43P", False),
        ("NR330", False),
    ],
)
def test_night_route_codes(route, overnight):
    """NA and NB are night routes too; NR routes are residents' services."""
    assert bool(j._OVERNIGHT.match(route)) is overnight


def test_a_night_route_is_tagged(wired, monkeypatch):
    monkeypatch.setattr(
        j.bus_core,
        "td_bus_route_stops",
        lambda: envelope(
            [
                td_row("KMB", "N241", 200, 1, "B1", "巴士一站", 22.0, 114.0),
                td_row("KMB", "N241", 200, 2, "B2", "巴士二站", 22.01, 114.01),
                td_row("KMB", "N241", 200, 3, "B3", "巴士三站", 22.03, 114.03),
            ]
        ),
    )
    j.clear_cache()
    result = j.journey("巴士一站", "巴士二站")
    option = result["data"]["options"][0]
    assert option["overnight_hint"] is True
    assert "通宵" in result["note"]


def test_a_day_route_ranks_before_a_night_route(wired, monkeypatch):
    """The night route is cheaper on paper; the day route still comes first."""
    rows = [
        td_row("KMB", "N241", 200, 1, "B1", "巴士一站", 22.0, 114.0),
        td_row("KMB", "N241", 200, 2, "B2", "巴士二站", 22.01, 114.01),
        td_row("KMB", "R1", 100, 1, "B1", "巴士一站", 22.0, 114.0),
        td_row("KMB", "R1", 100, 2, "B2", "巴士二站", 22.01, 114.01),
    ]
    monkeypatch.setattr(j.bus_core, "td_bus_route_stops", lambda: envelope(rows))
    j.clear_cache()
    result = j.journey("巴士一站", "巴士二站", options=2)
    assert result["data"]["options"][0]["legs"][0]["route"] == "R1"
    assert any(option["overnight_hint"] for option in result["data"]["options"])


def test_cross_boundary_coaches_are_not_in_the_graph(wired, monkeypatch):
    """XB only meets other XB at the border, so it could route via 皇崗."""
    monkeypatch.setattr(
        j.bus_core,
        "td_bus_route_stops",
        lambda: envelope(
            [
                td_row("XB", "旺角 - 皇崗", 300, 1, "B1", "巴士一站", 22.0, 114.0),
                td_row("XB", "旺角 - 皇崗", 300, 2, "B2", "巴士二站", 22.01, 114.01),
            ]
        ),
    )
    j.clear_cache()
    modes = j._graph()["labels"]
    assert not any(label["operator"] == "XB" for label in modes.values())
