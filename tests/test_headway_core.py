from datetime import datetime

import pytest

from hk_transport import headway_core
from hk_transport._result import HKT

FREQUENCIES = """\
trip_id,start_time,end_time,headway_secs
T1,08:00:00,09:00:00,600
T1,09:00:00,10:00:00,1200
T2,08:00:00,10:00:00,900
T4,23:00:00,25:00:00,1800
"""
TRIPS = """\
route_id,service_id,trip_id
100,1,T1
200,2,T2
300,1,T3
400,3,T4
"""
CALENDAR = """\
service_id,monday,tuesday,wednesday,thursday,friday,saturday,sunday,start_date,end_date
1,1,1,1,1,1,0,0,20200101,20991231
2,0,0,0,0,0,1,0,20200101,20991231
3,0,0,0,0,1,0,0,20200101,20991231
"""
CALENDAR_DATES = """\
service_id,date,exception_type
1,20261102,2
"""
TEXTS = {
    "frequencies": FREQUENCIES,
    "trips": TRIPS,
    "calendar": CALENDAR,
    "calendar_dates": CALENDAR_DATES,
}


@pytest.fixture
def wired(monkeypatch):
    def fake_fetch(url, *, dataset_id):
        name = url.rsplit("/", 1)[-1].removesuffix(".txt")
        return TEXTS[name], "2026-10-31T00:00:00+08:00"

    monkeypatch.setattr(headway_core, "fetch_text", fake_fetch)
    headway_core.clear_cache()
    yield
    headway_core.clear_cache()


def _at(year, month, day, hour, minute):
    return datetime(year, month, day, hour, minute, tzinfo=HKT)


def test_headway_and_service_status_at_a_time(wired):
    result = headway_core.service_at(_at(2026, 11, 3, 8, 30))
    row = result["data"]["100"]
    assert row["headway_minutes"] == 10.0
    assert row["in_service"] is True
    assert row["first"] == "08:00"
    assert row["last"] == "10:00"
    assert result["data"]["200"]["in_service"] is False
    assert result["data"]["300"]["in_service"] is None
    assert len(result["endpoint"]) == 4
    assert result["update_frequency"] == "biweekly"


def test_a_later_time_uses_the_next_headway_band(wired):
    row = headway_core.service_at(_at(2026, 11, 3, 9, 30))["data"]["100"]
    assert row["headway_minutes"] == 20.0


def test_outside_the_service_window_is_not_in_service(wired):
    row = headway_core.service_at(_at(2026, 11, 3, 11, 0))["data"]["100"]
    assert row["in_service"] is False
    assert row["headway_minutes"] is None


def test_calendar_dates_can_remove_a_service(wired):
    row = headway_core.service_at(_at(2026, 11, 2, 8, 30))["data"]["100"]
    assert row["in_service"] is False


def test_an_overnight_trip_uses_the_previous_service_day(wired):
    row = headway_core.service_at(_at(2026, 11, 7, 0, 30))["data"]["400"]
    assert row["headway_minutes"] == 30.0
    assert row["in_service"] is True
