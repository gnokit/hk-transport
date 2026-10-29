import pytest

from hk_transport import light_rail_next, mtr_bus, mtr_next_train
from hk_transport.mtr_core import lines_and_stations

pytestmark = pytest.mark.live


def test_live_lines_header():
    result = lines_and_stations()
    assert result["dataset_id"] == "mtr-data-routes-fares-barrier-free-facilities"
    assert result["endpoint"].endswith("mtr_lines_and_stations.csv")
    assert result["retrieved_at"].endswith("+08:00")
    codes = {row["code"] for row in result["data"]}
    assert "ADM" in codes
    assert "CHW" in codes


def test_live_next_train_admiralty():
    result = mtr_next_train("港島線", "金鐘")
    assert result["dataset_id"]
    assert "getSchedule.php" in str(result["endpoint"])
    assert result["data_at"]
    assert result["data"]["station"]["code"] == "ADM"
    assert result["data"]["directions"]


def test_live_light_rail_yuen_long():
    result = light_rail_next("元朗")
    assert result["data"]["station"]["id"] == "600"
    assert "lrt/getSchedule" in str(result["endpoint"])
    assert result["data_at"]


def test_live_mtr_bus_k52():
    result = mtr_bus("K52")
    assert result["data"]["route"]["route_id"] == "K52"
    assert result["data"]["stops"]
    assert result["data"]["fare"]
    assert result["dataset_id"]
    assert "mtr/bus/getSchedule" in str(result["endpoint"])
    stamp = result["retrieved_at"]
    stamps = stamp if isinstance(stamp, list) else [stamp]
    assert stamps and all(item.endswith("+08:00") for item in stamps)
