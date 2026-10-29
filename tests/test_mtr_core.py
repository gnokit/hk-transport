from pathlib import Path

import pytest

from hk_transport import mtr_core
from hk_transport._result import MtrError

LINES_CSV = """\
Line Code,Direction,Station Code,Station ID,Chinese Name,English Name,Sequence
EAL,DT,LOW,76,羅湖,Lo Wu,1.00
EAL,DT,SHS,75,上水,Sheung Shui,2
EAL,LMC-DT,LMC,78,落馬洲,Lok Ma Chau,1
EAL,LMC-DT,SHS,75,上水,Sheung Shui,2
,,,,,
"""

FARES_CSV = """\
SRC_STATION_NAME,SRC_STATION_ID,DEST_STATION_NAME,DEST_STATION_ID,OCT_ADT_FARE,SINGLE_ADT_FARE
Central,1,Hung Hom,64,10.4,12
"""

NEXT_PAYLOAD = {
    "status": 1,
    "message": "successful",
    "isdelay": "N",
    "curr_time": "2026-10-29 09:32:08",
    "sys_time": "2026-10-29 09:32:08",
    "data": {
        "ISL-ADM": {
            "UP": [
                {"seq": "1", "dest": "CHW", "plat": "3", "time": "2026-10-29 09:32:08", "ttnt": "0", "valid": "Y"}
            ],
            "DOWN": [],
        }
    },
}

BUS_PAYLOAD = {
    "routeName": "K52",
    "status": 1,
    "routeStatusTime": "2026-10-29 09:40:00",
    "busStop": [
        {
            "busStopId": "K52-D010",
            "isSuspended": "0",
            "bus": [
                {
                    "arrivalTimeText": "",
                    "departureTimeText": "6 分鐘",
                    "isScheduled": "1",
                    "isDelayed": "0",
                    "busLocation": {"latitude": 0, "longitude": 0},
                    "lineRef": "K52_LKT_YWV",
                    "busId": "510",
                }
            ],
        }
    ],
}


def test_lines_keep_branch_directions_and_skip_blank_rows(monkeypatch):
    def fake_fetch(url, *, dataset_id):
        assert url == mtr_core.LINES_URL
        assert dataset_id == mtr_core.STATIC_DATASET
        return LINES_CSV, "2026-10-01T00:00:00+08:00"

    monkeypatch.setattr(mtr_core, "fetch_text", fake_fetch)
    result = mtr_core.lines_and_stations()
    directions = {row["direction"] for row in result["data"]}
    assert directions == {"DT", "LMC-DT"}
    assert result["data_at"] is None
    assert result["update_frequency"] == "monthly"
    assert result["dataset_id"] == mtr_core.STATIC_DATASET
    low = next(row for row in result["data"] if row["code"] == "LOW")
    assert low["sequence"] == 1
    assert low["id"] == "76"


def test_table_is_parsed_once_per_process(monkeypatch):
    calls = []

    def fake_fetch(url, *, dataset_id):
        calls.append(url)
        return LINES_CSV, "2026-10-01T00:00:00+08:00"

    monkeypatch.setattr(mtr_core, "fetch_text", fake_fetch)
    mtr_core.lines_and_stations()
    mtr_core.lines_and_stations()
    assert calls == [mtr_core.LINES_URL]


def test_domestic_fares_keep_only_columns_in_the_file(monkeypatch):
    monkeypatch.setattr(
        mtr_core,
        "fetch_text",
        lambda url, *, dataset_id: (FARES_CSV, "2026-10-01T00:00:00+08:00"),
    )
    result = mtr_core.domestic_fares()
    row = result["data"][0]
    assert row["from_id"] == "1"
    assert row["from_name"] == "Central"
    assert row["fares"] == {"OCT_ADT_FARE": "10.4", "SINGLE_ADT_FARE": "12"}


def test_dash_cell_is_read_as_no_value(monkeypatch):
    text = FARES_CSV.replace("10.4,12", "10.4,-")
    monkeypatch.setattr(
        mtr_core,
        "fetch_text",
        lambda url, *, dataset_id: (text, "2026-10-01T00:00:00+08:00"),
    )
    row = mtr_core.domestic_fares()["data"][0]
    assert row["fares"]["SINGLE_ADT_FARE"] is None
    assert row["fares"]["OCT_ADT_FARE"] == "10.4"


def test_live_next_train_is_not_written_to_the_cache(monkeypatch, tmp_path):
    def fake_get(url, timeout):
        class Response:
            def raise_for_status(self):
                return None

            def json(self):
                return NEXT_PAYLOAD

        assert "line=ISL" in url and "sta=ADM" in url
        return Response()

    monkeypatch.setattr(mtr_core.requests, "get", fake_get)
    result = mtr_core.next_train("ISL", "ADM")
    assert result["update_frequency"] == "10s"
    assert result["data_at"] == "2026-10-29T09:32:08+08:00"
    assert result["data"]["directions"][0]["trains"][0]["dest"] == "CHW"
    assert list(tmp_path.glob("*")) == []


def test_bus_schedule_posts_and_keeps_scheduled_flag(monkeypatch):
    seen = {}

    def fake_post(url, json, timeout):
        seen["url"] = url
        seen["json"] = json

        class Response:
            def raise_for_status(self):
                return None

            def json(self):
                return BUS_PAYLOAD

        return Response()

    monkeypatch.setattr(mtr_core.requests, "post", fake_post)
    result = mtr_core.bus_schedule("K52")
    assert seen["url"] == mtr_core.BUS_URL
    assert seen["json"] == {"language": "zh", "routeName": "K52"}
    bus = result["data"]["stops"][0]["buses"][0]
    assert bus["is_scheduled"] is True
    assert bus["departure_time_text"] == "6 分鐘"
    assert bus["arrival_time_text"] is None
    assert bus["location"] == {"latitude": 0, "longitude": 0}


def test_bad_json_raises(monkeypatch):
    def fake_get(url, timeout):
        class Response:
            def raise_for_status(self):
                return None

            def json(self):
                raise ValueError("not json")

        return Response()

    monkeypatch.setattr(mtr_core.requests, "get", fake_get)
    with pytest.raises(MtrError) as caught:
        mtr_core.next_train("ISL", "ADM")
    assert caught.value.dataset_id == mtr_core.NEXT_DATASET


def test_source_does_not_request_the_intercity_file():
    text = Path(mtr_core.__file__).read_text(encoding="utf-8")
    assert "intercity" not in text.casefold()
