import pytest

from hk_transport import ferry


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
        "route": "中環 - 長洲",
        "route_id": 7001,
        "route_seq": 1,
        "service_mode": "T",
        "special_type": 1,
        "origin_zh": "中環",
        "dest_zh": "長洲",
        "fare": 30.0,
        "journey_time_minutes": 36.0,
        "remark": None,
    }
]
STOPS = [
    {
        "stop": "P1",
        "name_zh": "中環碼頭",
        "name_en": "Central Pier",
        "latitude": 22.2880,
        "longitude": 114.1583,
        "route_id": 7001,
        "route_seq": 1,
        "seq": 1,
        "route": "中環 - 長洲",
    },
    {
        "stop": "P2",
        "name_zh": "長洲碼頭",
        "name_en": "Cheung Chau Pier",
        "latitude": 22.2080,
        "longitude": 114.0280,
        "route_id": 7001,
        "route_seq": 1,
        "seq": 2,
        "route": "中環 - 長洲",
    },
]


@pytest.fixture
def wired(monkeypatch):
    monkeypatch.setattr(ferry.ferry_core, "ferry_routes", lambda: envelope(ROUTES))
    monkeypatch.setattr(ferry.ferry_core, "ferry_stops", lambda: envelope(STOPS))


def test_a_route_lists_its_piers(wired):
    result = ferry.ferry_route("長洲")
    variant = result["data"]["variants"][0]
    assert [p["name_zh"] for p in variant["piers"]] == ["中環碼頭", "長洲碼頭"]


def test_the_answer_never_names_an_operator(wired):
    result = ferry.ferry_route("長洲")
    assert "營辦商" in result["note"]


def test_the_fare_is_the_adult_full_fare(wired):
    result = ferry.ferry_fare("長洲")
    assert result["data"]["variants"][0]["fare"] == 30.0
    assert "唔係分段" in result["note"]


def test_piers_near_a_place(wired):
    result = ferry.ferry_piers_near("中環碼頭")
    assert result["data"]["piers"][0]["name_zh"] == "中環碼頭"


def test_timetable_and_eta_have_no_data(wired):
    assert "班次" in ferry.ferry_timetable()["note"]
    assert "實時" in ferry.ferry_eta()["note"]
