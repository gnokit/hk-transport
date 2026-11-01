import json
from pathlib import Path

import pytest
import requests

from hk_transport._result import MtrError
from hk_transport.exits import (
    DATASET_ID,
    SEARCH_ENDPOINT,
    TRANSFORM_DATASET_ID,
    TRANSFORM_ENDPOINT,
    mtr_exits,
)
from hk_transport import exits


def test_exit_reader_does_not_fetch():
    text = Path(exits.__file__).read_text(encoding="utf-8")
    assert "requests" not in text
    assert "cache_dir" not in text
    assert "HK_TRANSPORT_CACHE" not in text


def test_admiralty_c1_keeps_grid_and_converted_wgs84():
    result = mtr_exits("金鐘")
    assert result["dataset_id"] == [DATASET_ID, TRANSFORM_DATASET_ID]
    assert result["endpoint"] == [SEARCH_ENDPOINT, TRANSFORM_ENDPOINT]
    assert result["data_at"] is None
    assert result["update_frequency"] == "yearly"
    assert "已超過一年" not in result["note"]
    assert "不是港鐵公布的出口名冊" in result["note"]
    row = next(item for item in result["data"] if item["station_zh"] == "金鐘" and item["exit"] == "C1")
    assert row["easting"] == 835020
    assert row["northing"] == 815518
    assert row["latitude"] == pytest.approx(22.278527076, abs=1e-6)
    assert row["longitude"] == pytest.approx(114.164764821, abs=1e-6)
    assert row["name_zh"] == "港鐵金鐘站-C1進出口"
    assert row["name_en"] == "MTR Admiralty Station-C1 Access"
    assert row["station_ids"] == ["2"]
    assert row["station_codes"] == ["ADM"]


def test_snapshot_uses_official_station_names():
    rows = exits._load()["exits"]
    names = {item["station_zh"] for item in rows}
    assert len(rows) == 608
    assert len(names) == 97
    assert "這次沒有進出口" not in mtr_exits("金鐘")["note"]
    assert "尖東" in names
    assert "荃灣西" in names
    assert "茘枝角" in names
    assert "荔枝角" not in names
    lai_chi_kok = next(item for item in rows if item["station_zh"] == "茘枝角")
    assert "荔枝角" in lai_chi_kok["name_zh"]
    assert all(item["name_zh"].endswith("出口") for item in rows)
    assert all("郵箱" not in item["name_zh"] and "WiFi" not in item["name_zh"] for item in rows)


def test_access_without_a_letter_keeps_a_null_exit():
    row = next(item for item in exits._load()["exits"] if item["name_zh"] == "港鐵尖東站進出口")
    assert row["station_zh"] == "尖東"
    assert row["exit"] is None
    assert row["latitude"] is not None
    assert row["easting"] != row["latitude"]


def test_lo_wu_uses_the_published_exit_word():
    row = next(item for item in exits._load()["exits"] if item["station_zh"] == "羅湖" and item["exit"] == "A")
    assert row["name_zh"] == "港鐵羅湖站-A出口"
    assert row["name_en"] == "MTR Lo Wu Station-A Exit"


def test_one_station_can_be_asked_for_by_name_or_code():
    by_name = mtr_exits("金鐘")
    assert {row["station_zh"] for row in by_name["data"]} == {"金鐘"}
    assert "只列出「金鐘」" in by_name["note"]
    by_code = mtr_exits("ADM")
    assert {row["station_zh"] for row in by_code["data"]} == {"金鐘"}


def test_lai_chi_kok_alias_is_accepted():
    result = mtr_exits("荔枝角")
    assert {row["station_zh"] for row in result["data"]} == {"茘枝角"}
    assert "茘枝角" in result["note"]


def test_unknown_station_does_not_invent_exits():
    result = mtr_exits("不存在")
    assert result["data"] is None
    assert "快照沒有這個站的出入口" in result["note"]


def test_shared_stations_list_both_line_ids():
    rows = exits._load()["exits"]

    def ids(name: str) -> list[str]:
        return next(item["station_ids"] for item in rows if item["station_zh"] == name)

    assert ids("香港") == ["39", "44"]
    assert ids("九龍") == ["40", "45"]
    assert ids("青衣") == ["42", "46"]
    assert next(item["station_codes"] for item in rows if item["station_zh"] == "香港") == ["HOK"]


def test_snapshot_older_than_a_year_is_still_returned(monkeypatch):
    snapshot = exits._load()
    stale = {
        **snapshot,
        "retrieved_at": "2020-01-01T00:00:00+08:00",
        "missing_stations": ["顯徑"],
    }
    monkeypatch.setattr(exits, "_load", lambda: stale)
    result = exits.mtr_exits("金鐘")
    assert {row["station_zh"] for row in result["data"]} == {"金鐘"}
    assert result["retrieved_at"] == "2020-01-01T00:00:00+08:00"
    assert "已超過一年" in result["note"]
    assert "顯徑" in result["note"]


def test_missing_snapshot_names_the_dataset(monkeypatch, tmp_path):
    monkeypatch.setattr(exits, "_path", lambda: tmp_path / "missing.json")
    with pytest.raises(MtrError) as caught:
        mtr_exits("金鐘")
    assert caught.value.dataset_id == DATASET_ID
    assert caught.value.endpoint == SEARCH_ENDPOINT


def test_snapshot_file_records_the_same_sources():
    payload = json.loads(exits._path().read_text(encoding="utf-8"))
    assert payload["dataset_id"] == DATASET_ID
    assert payload["endpoint"] == SEARCH_ENDPOINT
    assert payload["transform_dataset_id"] == TRANSFORM_DATASET_ID
    assert payload["retrieved_at"].endswith("+08:00")


@pytest.mark.live
def test_live_admiralty_c1_grid_still_matches_the_snapshot():
    response = requests.get(
        SEARCH_ENDPOINT,
        params={"q": "港鐵金鐘站 出口"},
        headers={"User-Agent": "hk-transport"},
        timeout=20,
    )
    response.raise_for_status()
    item = next(row for row in response.json() if row.get("nameZH") == "港鐵金鐘站-C1進出口")
    assert item["x"] == 835020.0
    assert item["y"] == 815518.0


def test_a_blank_station_is_an_error():
    with pytest.raises(MtrError) as caught:
        mtr_exits("   ")
    assert caught.value.dataset_id == DATASET_ID
    assert "站名" in str(caught.value)
