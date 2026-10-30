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


def td_row(company, route, route_id, seq, stop_id, name, latitude, longitude):
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
        "journey_time_minutes": 30.0,
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
EXITS = {
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
    j._price_walks(legs, [5])
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
    j._price_walks(legs, [5])
    assert legs[0]["estimated"] is True
    assert legs[0]["metres"] == 500


def test_a_direct_ride_is_zero_transfers(wired):
    option = j.journey("巴士一站", "巴士二站")["data"]["options"][0]
    assert option["transfers"] == 0
    assert option["stops"] == 1


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
