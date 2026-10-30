import pytest

from hk_transport import _places, bus
from hk_transport._result import MtrError


def stop(stop_id, name, latitude, longitude):
    return {
        "stop": stop_id,
        "name_zh": name,
        "name_en": name,
        "latitude": latitude,
        "longitude": longitude,
    }


def route_row(route, direction, seq, stop_id, service_type="1"):
    return {
        "route": route,
        "direction": direction,
        "service_type": service_type,
        "seq": seq,
        "stop": stop_id,
    }


STOPS = [
    stop("A1", "甲站", 22.0000, 114.0000),
    stop("A2", "甲站後街", 22.0027, 114.0000),
    stop("B1", "乙站", 22.0100, 114.0100),
    stop("C1", "丙站", 22.0050, 114.0050),
]

# R1 boards one stop further from the origin than R2, but goes direct.
ROUTES = [
    route_row("R2", "O", 1, "A1"),
    route_row("R2", "O", 2, "C1"),
    route_row("R3", "O", 1, "C1"),
    route_row("R3", "O", 2, "B1"),
    route_row("R1", "O", 1, "A2"),
    route_row("R1", "O", 2, "B1"),
]


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


def wire(monkeypatch, routes):
    monkeypatch.setattr(bus.bus_core, "kmb_stops", lambda: envelope(STOPS))
    monkeypatch.setattr(bus.bus_core, "kmb_route_stops_all", lambda: envelope(routes))
    # No place search in the offline tests; a name that is not a stop is far away.
    monkeypatch.setattr(_places.geocode, "place_search", lambda text, limit=5: envelope([]))


def test_every_stop_in_radius_is_tried_not_just_the_nearest(monkeypatch):
    wire(monkeypatch, ROUTES)
    result = bus.bus_journey("甲站", "乙站")
    option = result["data"]["options"][0]
    assert option["transfers"] == 0
    assert [leg["route"] for leg in option["legs"]] == ["R1"]


def test_the_same_route_on_two_variants_is_one_option(monkeypatch):
    routes = ROUTES + [
        route_row("R1", "O", 1, "A2", service_type="2"),
        route_row("R1", "O", 2, "B1", service_type="2"),
    ]
    wire(monkeypatch, routes)
    result = bus.bus_journey("甲站", "乙站")
    same = [o for o in result["data"]["options"] if o["legs"][0]["route"] == "R1"]
    assert len(same) == 1


def test_a_night_route_is_returned_with_a_hint(monkeypatch):
    routes = [
        route_row("N241", "O", 1, "A2"),
        route_row("N241", "O", 2, "B1"),
    ]
    wire(monkeypatch, routes)
    result = bus.bus_journey("甲站", "乙站")
    assert result["data"]["options"][0]["overnight_hint"] is True
    assert "通宵" in result["note"]


def test_no_stop_within_the_radius_says_so(monkeypatch):
    wire(monkeypatch, ROUTES)

    def far_away(text, n=5):
        return envelope(
            [
                {
                    "building_zh": "遠地方",
                    "building_en": "Far Place",
                    "street_zh": None,
                    "street_en": None,
                    "latitude": "22.5000",
                    "longitude": "114.5000",
                    "score": 90,
                }
            ]
        )

    monkeypatch.setattr(_places.als, "address_lookup", far_away)
    result = bus.bus_journey("甲站", "遠地方", walk=400)
    assert result["data"] is None
    assert "400 米內沒有九巴／龍運站" in result["note"]
    assert "最近的是乙站" in result["note"]
    assert "直線 74239 米" in result["note"]


def test_leg_stop_counts_are_segments(monkeypatch):
    wire(monkeypatch, ROUTES)
    option = bus.bus_journey("甲站", "乙站")["data"]["options"][0]
    assert option["stops"] == sum(leg["stops"] for leg in option["legs"])


def test_bus_fare_lists_every_variant(monkeypatch):
    rows = [
        {"company": "KMB", "route": "B1", "route_type": 1, "service_mode": "R", "fare": 15.3, "journey_time_minutes": 50.0},
        {"company": "KMB", "route": "B1", "route_type": 1, "service_mode": "T", "fare": 15.3, "journey_time_minutes": 77.0},
    ]
    monkeypatch.setattr(bus.bus_core, "td_bus_fares", lambda: envelope(rows))
    result = bus.bus_fare("b1")
    assert result["data"]["route"] == "B1"
    assert len(result["data"]["variants"]) == 2
    assert "成人全程價" in result["note"]
    assert "不是分段" in result["note"]


def test_bus_fare_for_an_unknown_route_says_so(monkeypatch):
    monkeypatch.setattr(bus.bus_core, "td_bus_fares", lambda: envelope([]))
    result = bus.bus_fare("999")
    assert result["data"] is None
    assert "999" in result["note"]


def notices_envelope(rows):
    return envelope(rows)


def test_bus_disruption_matches_a_named_route(monkeypatch):
    monkeypatch.setattr(
        bus.notices,
        "special_traffic_news",
        lambda: notices_envelope([]),
    )
    monkeypatch.setattr(
        bus.notices,
        "special_traffic_arrangements",
        lambda: notices_envelope(
            [
                {
                    "id": "1",
                    "title_zh": "元朗大棠路臨時交通及運輸安排",
                    "content_zh": "港鐵巴士路線第K66號的巴士站將臨時遷移。",
                    "start_date": "19.11.2026",
                }
            ]
        ),
    )
    result = bus.bus_disruption("k66")
    assert len(result["data"]["matches"]) == 1
    assert result["data"]["matches"][0]["source"] == "arrangement"
    assert "關鍵字比對" in result["note"]


def test_bus_disruption_does_not_match_inside_a_longer_route(monkeypatch):
    monkeypatch.setattr(bus.notices, "special_traffic_news", lambda: notices_envelope([]))
    monkeypatch.setattr(
        bus.notices,
        "special_traffic_arrangements",
        lambda: notices_envelope(
            [{"id": "1", "title_zh": "265B 改道", "content_zh": "265B 路線臨時改道。", "start_date": "1.1.2026"}]
        ),
    )
    result = bus.bus_disruption("26")
    assert result["data"]["matches"] == []
    assert "沒有提到這條線" in result["note"]


def test_bus_disruption_rejects_something_that_is_not_a_route(monkeypatch):
    result = bus.bus_disruption("元州邨")
    assert result["data"] is None
    assert "唔似巴士路線號碼" in result["note"]


def test_none_options_and_walk_fall_back_to_defaults(monkeypatch):
    wire(monkeypatch, ROUTES)
    result = bus.bus_journey("甲站", "乙站", options=None, walk=None)
    assert result["data"]["options"]
    assert result["data"]["options"][0]["transfers"] == 0


def place(name, latitude, longitude, district="測試區", address=None):
    return {
        "name_zh": name,
        "name_en": name,
        "address_zh": address,
        "address_en": None,
        "district_zh": district,
        "district_en": None,
        "easting": 0.0,
        "northing": 0.0,
        "latitude": latitude,
        "longitude": longitude,
    }


def test_a_place_name_comes_from_the_place_search(monkeypatch):
    wire(monkeypatch, ROUTES)
    monkeypatch.setattr(
        _places.geocode, "place_search", lambda text, limit=5: envelope([place("乙站附近", 22.0101, 114.0101)])
    )
    result = bus.bus_journey("甲站", "乙站附近")
    assert result["data"]["destination"]["resolved_as"] == "place"
    assert result["data"]["destination"]["name_zh"] == "乙站附近"
    assert result["data"]["options"]


def test_a_place_in_another_district_is_reported_not_hidden(monkeypatch):
    wire(monkeypatch, ROUTES)
    rows = [
        place("乙站", 22.0100, 114.0100),
        place("乙站大廈", 22.2800, 114.1300, district="中西區"),
    ]
    monkeypatch.setattr(_places.geocode, "place_search", lambda text, limit=5: envelope(rows))
    point = bus.bus_journey("甲站", "乙站")["data"]["destination"]
    assert point["resolved_as"] == "stop"
    assert "also_matched" not in point


def test_the_best_place_name_wins_over_a_facility_that_mentions_it(monkeypatch):
    monkeypatch.setattr(_places.geocode, "place_search", lambda text, limit=5: envelope([
        place("自動心臟除顫器 - 南生圍", 22.4000, 114.1000),
        place("南生圍", 22.4633, 114.0370),
    ]))
    point, note = _places.place("南生圍", {row["stop"]: row for row in STOPS})
    assert note is None
    assert point["name_zh"] == "南生圍"


def test_address_lookup_is_the_fallback_when_the_place_search_is_empty(monkeypatch):
    monkeypatch.setattr(_places.geocode, "place_search", lambda text, limit=5: envelope([]))
    monkeypatch.setattr(_places.als, "address_lookup", lambda text, n=5: envelope([{
        "building_zh": "遠東發展元朗大廈",
        "building_en": "FAR EAST CONSORTIUM YUEN LONG BUILDING",
        "street_zh": "元朗安樂路",
        "street_en": "YUEN LONG ON LOK ROAD",
        "district_zh": "元朗區",
        "latitude": "22.44517",
        "longitude": "114.03204",
        "score": 100.0,
    }]))
    point, note = _places.place("元朗", {row["stop"]: row for row in STOPS})
    assert note is None
    assert point["resolved_as"] == "address"
    assert point["district_zh"] == "元朗區"


def test_a_stop_name_that_matches_two_places_is_not_narrowed_silently(monkeypatch):
    wide = [
        {"stop": "X1", "name_zh": "同名站", "name_en": "Same", "latitude": 22.0, "longitude": 114.0},
        {"stop": "X2", "name_zh": "同名站", "name_en": "Same", "latitude": 22.1, "longitude": 114.1},
    ]
    point, note = _places.place("同名站", {row["stop"]: row for row in wide})
    assert note is None
    assert point["name_zh"] == "同名站"
    assert len(point["also_matched"]) == 1
