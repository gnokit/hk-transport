import pytest

from hk_transport import bus
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

    monkeypatch.setattr(bus.als, "address_lookup", far_away)
    result = bus.bus_journey("甲站", "遠地方", walk=400)
    assert result["data"] is None
    assert "米內找不到巴士站" in result["note"]


def test_leg_stop_counts_are_segments(monkeypatch):
    wire(monkeypatch, ROUTES)
    option = bus.bus_journey("甲站", "乙站")["data"]["options"][0]
    assert option["stops"] == sum(leg["stops"] for leg in option["legs"])
