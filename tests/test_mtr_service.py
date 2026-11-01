from datetime import datetime

from hk_transport import mtr_service_core
from hk_transport._result import HKT


def _at(hour, minute, day=1):
    return datetime(2026, 11, day, hour, minute, tzinfo=HKT)


def test_snapshot_has_the_expected_station_and_lines():
    result = mtr_service_core.service_at(_at(8, 30))
    station = result["data"]["2"]
    assert station["name_zh"] == "金鐘"
    assert {"ISL", "TWL", "EAL", "SIL"} <= set(station["lines"])
    assert result["dataset_id"] == mtr_service_core.DATASET
    assert result["update_frequency"] == "as and when necessary"
    assert "不是 data.gov.hk" in result["note"]


def test_island_line_is_open_at_0830_and_closed_at_0300():
    at_0830 = mtr_service_core.service_at(_at(8, 30))["data"]["2"]["lines"]["ISL"]
    assert at_0830["in_service"] is True
    at_0300 = mtr_service_core.service_at(_at(3, 0))["data"]["2"]["lines"]["ISL"]
    assert at_0300["in_service"] is False


def test_destination_specific_last_train():
    eal = mtr_service_core.service_at(_at(23, 30))["data"]["2"]["lines"]["EAL"]
    assert eal["in_service"] is True
    assert eal["destinations"]["75"]["in_service"] is True   # 上水
    assert eal["destinations"]["78"]["in_service"] is False  # 落馬洲


def test_airport_express_is_in_the_snapshot():
    ael = mtr_service_core.service_at(_at(23, 30))["data"]["44"]["lines"]["AEL"]
    assert ael["in_service"] is True
    assert ael["destinations"]["47"]["in_service"] is True
    late = mtr_service_core.service_at(_at(1, 0))["data"]["44"]["lines"]["AEL"]
    assert late["in_service"] is False


def test_trip_destinations_map_branch_directions():
    destinations = mtr_service_core.trip_destinations()
    assert destinations[("EAL", "LMC-UT")] == "78"
    assert destinations[("EAL", "UT")] == "76"
    assert destinations[("AEL", "UT")] == "56"
