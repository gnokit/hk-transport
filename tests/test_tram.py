import pytest

from hk_transport import tram


def stop(stop_id, name, lat, lon):
    return {
        "stop": stop_id,
        "name_zh": name,
        "name_en": name,
        "latitude": lat,
        "longitude": lon,
    }


def envelope(rows):
    return {
        "data": rows,
        "dataset_id": "test",
        "endpoint": "test",
        "retrieved_at": "2026-10-30T00:00:00+08:00",
        "data_at": None,
        "update_frequency": "biweekly",
        "note": None,
    }


ROUTES = [
    {
        "route": "筲箕灣 - 跑馬地線",
        "route_id": 4002,
        "route_seq": 1,
        "service_mode": "R",
        "special_type": 0,
        "origin_zh": "筲箕灣",
        "dest_zh": "跑馬地",
        "fare": 3.3,
        "journey_time_minutes": 60.0,
        "remark": None,
    }
]
STOPS = [
    stop("T1", "筲箕灣總站", 22.2780, 114.2290),
    stop("T2", "銅鑼灣", 22.2800, 114.1850),
    stop("T3", "跑馬地", 22.2700, 114.1830),
]


def rows_for(route_id=4002, route_seq=1):
    return [
        {**STOPS[0], "route_id": route_id, "route_seq": route_seq, "seq": 1, "route": "筲箕灣 - 跑馬地線"},
        {**STOPS[1], "route_id": route_id, "route_seq": route_seq, "seq": 2, "route": "筲箕灣 - 跑馬地線"},
        {**STOPS[2], "route_id": route_id, "route_seq": route_seq, "seq": 3, "route": "筲箕灣 - 跑馬地線"},
    ]


@pytest.fixture
def wired(monkeypatch):
    monkeypatch.setattr(tram.tram_core, "tram_routes", lambda: envelope(ROUTES))
    monkeypatch.setattr(tram.tram_core, "tram_stops", lambda: envelope(rows_for()))
    monkeypatch.setattr(tram.tram_core, "peak_tram_routes", lambda: envelope([]))
    monkeypatch.setattr(tram.tram_core, "peak_tram_stops", lambda: envelope([]))


def test_a_line_is_found_by_a_word_in_its_name(wired):
    result = tram.tram_route("跑馬地")
    assert result["data"]["variants"][0]["route"] == "筲箕灣 - 跑馬地線"
    assert len(result["data"]["variants"][0]["stops"]) == 3


def test_an_unknown_line_says_so(wired):
    result = tram.tram_route("旺角")
    assert result["data"] is None
    assert "找不到電車線" in result["note"]


def test_the_fare_is_flat(wired):
    result = tram.tram_fare("跑馬地")
    assert result["data"]["variants"][0]["fare"] == 3.3
    assert "固定收費" in result["note"]


def test_stops_near_a_place_are_ordered(wired):
    result = tram.tram_stops_near("銅鑼灣")
    assert result["data"]["stops"][0]["name_zh"] == "銅鑼灣"


def test_the_two_no_data_commands_say_why(wired):
    assert "服務時間" in tram.tram_service_hours()["note"]
    assert "實時" in tram.tram_eta()["note"]
