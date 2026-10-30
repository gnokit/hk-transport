import json

import pytest

from hk_transport import minibus_core
from hk_transport._result import MtrError

FEATURES = {
    "type": "FeatureCollection",
    "features": [
        {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [114.0000, 22.0000]},
            "properties": {
                "routeId": 100,
                "companyCode": "GMB",
                "district": "NT",
                "routeNameC": "37",
                "routeNameE": "37",
                "routeSeq": 1,
                "routeType": 2,
                "serviceMode": "R",
                "specialType": 0,
                "journeyTime": 18,
                "locStartNameC": "元朗(福康街)",
                "locStartNameE": "Yuen Long (Fook Hong Street)",
                "locEndNameC": "攸潭尾村公所",
                "locEndNameE": "Yau Tam Mei Village Office",
                "stopId": 9001,
                "stopSeq": 1,
                "stopNameC": "福康街",
                "stopNameE": "Fook Hong Street",
                "stopPickDrop": 2,
                "fullFare": 9.0,
                "lastUpdateDate": "2026-10-08T00:00:00",
            },
        },
        {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [114.0010, 22.0010]},
            "properties": {
                "routeId": 100,
                "district": "NT",
                "routeNameC": "37",
                "routeNameE": "37",
                "routeSeq": 1,
                "routeType": 2,
                "serviceMode": "R",
                "specialType": 0,
                "journeyTime": 18,
                "locStartNameC": "元朗(福康街)",
                "locEndNameC": "攸潭尾村公所",
                "stopId": 9002,
                "stopSeq": 2,
                "stopNameC": "攸潭尾村公所",
                "stopNameE": "Yau Tam Mei Village Office",
                "stopPickDrop": 1,
                "fullFare": 9.0,
                "lastUpdateDate": "2026-10-08T00:00:00",
            },
        },
        {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [114.2000, 22.2000]},
            "properties": {
                "routeId": 200,
                "district": "HKI",
                "routeNameC": "37",
                "routeNameE": "37",
                "routeSeq": 1,
                "routeType": 2,
                "serviceMode": "T",
                "specialType": 1,
                "journeyTime": 30,
                "locStartNameC": "置富花園",
                "locEndNameC": "中環",
                "stopId": 9100,
                "stopSeq": 1,
                "stopNameC": "置富花園",
                "stopNameE": "Chi Fu Fa Yuen",
                "stopPickDrop": 2,
                "fullFare": 6.4,
                "lastUpdateDate": "2026-10-08T00:00:00",
            },
        },
    ],
}


@pytest.fixture
def parsed(tmp_path, monkeypatch):
    path = tmp_path / "gmb.json"
    path.write_text(json.dumps(FEATURES), encoding="utf-8-sig")
    monkeypatch.setattr(
        minibus_core, "cached_file", lambda url, dataset_id: (path, "2026-10-30T12:00:00+08:00")
    )
    minibus_core.clear_cache()
    yield
    minibus_core.clear_cache()


def test_routes_are_one_row_per_variant(parsed):
    result = minibus_core.gmb_routes()
    assert len(result["data"]) == 2
    first = result["data"][0]
    assert first["route"] == "37"
    assert first["district"] == "NT"
    assert first["fare"] == 9.0
    assert first["journey_time_minutes"] == 18.0
    assert result["dataset_id"] == "hk-td-tis_23-routes-fares-geojson"
    assert result["update_frequency"] == "biweekly"


def test_stop_rows_keep_sequence_and_swap_coordinates_to_lat_lon(parsed):
    rows = minibus_core.gmb_route_stops()["data"]
    assert len(rows) == 3
    first = rows[0]
    assert first["seq"] == 1
    assert first["stop"] == "9001"
    assert first["latitude"] == pytest.approx(22.0000)
    assert first["longitude"] == pytest.approx(114.0000)


def test_stops_are_deduplicated_by_stop_id(parsed):
    rows = minibus_core.gmb_stops()["data"]
    assert {row["stop"] for row in rows} == {"9001", "9002", "9100"}
    assert "同一個停車位置" in minibus_core.gmb_stops()["note"]


def test_the_file_carries_its_own_update_date(parsed):
    assert minibus_core.gmb_routes()["data_at"] == "2026-10-08T00:00:00+08:00"


def test_the_parse_is_held_in_memory_until_cleared(tmp_path, monkeypatch):
    path = tmp_path / "gmb.json"
    path.write_text(json.dumps(FEATURES), encoding="utf-8-sig")
    calls = []

    def cached(url, dataset_id):
        calls.append(url)
        return path, "2026-10-30T12:00:00+08:00"

    monkeypatch.setattr(minibus_core, "cached_file", cached)
    minibus_core.clear_cache()
    minibus_core.gmb_routes()
    minibus_core.gmb_routes()
    assert len(calls) == 1
    minibus_core.clear_cache()


def test_a_malformed_file_is_an_error(tmp_path, monkeypatch):
    path = tmp_path / "bad.json"
    path.write_text("{not json", encoding="utf-8")
    monkeypatch.setattr(
        minibus_core, "cached_file", lambda url, dataset_id: (path, "2026-10-30T12:00:00+08:00")
    )
    minibus_core.clear_cache()
    with pytest.raises(MtrError) as caught:
        minibus_core.gmb_routes()
    assert caught.value.dataset_id == minibus_core.DATASET_STATIC
    minibus_core.clear_cache()


def eta_payload(rows):
    def call(url, *, dataset_id, cache=True, timeout=30, headers=None):
        return {"data": rows}, "2026-10-30T12:00:00+08:00"

    return call


def test_stop_eta_reads_minutes_and_time(monkeypatch):
    monkeypatch.setattr(
        minibus_core,
        "fetch_json",
        eta_payload(
            [
                {
                    "route_id": 100,
                    "route_seq": 1,
                    "stop_seq": 1,
                    "enabled": True,
                    "eta": [
                        {"eta_seq": 1, "diff": 5, "timestamp": "2026-10-30T12:05:00.000+08:00"},
                    ],
                }
            ]
        ),
    )
    result = minibus_core.gmb_stop_eta("9001")
    row = result["data"][0]
    assert row["route_id"] == 100
    assert row["eta"][0]["minutes"] == 5
    assert row["eta"][0]["at"] == "2026-10-30T12:05:00.000+08:00"
    assert "eta/stop/9001" in result["endpoint"]


def test_route_stop_eta_uses_the_three_part_path(monkeypatch):
    seen = {}

    def call(url, *, dataset_id, cache=True, timeout=30, headers=None):
        seen["url"] = url
        return {"data": {"stop_id": 9002, "enabled": True, "eta": []}}, "2026-10-30T12:00:00+08:00"

    monkeypatch.setattr(minibus_core, "fetch_json", call)
    minibus_core.gmb_route_stop_eta(100, 1, 2)
    assert seen["url"].endswith("/eta/route-stop/100/1/2")


def test_stop_payload_is_not_a_list_so_it_is_an_error(monkeypatch):
    monkeypatch.setattr(minibus_core, "fetch_json", eta_payload({"nope": 1}))
    with pytest.raises(MtrError):
        minibus_core.gmb_stop_eta("9001")


def test_stop_names_keep_the_readable_side():
    """A '/' joined name is one line, not two with a stray break."""
    from hk_transport._values import clean_breaks

    assert clean_breaks("甲站/<br>乙站") == "甲站/乙站"
    assert clean_breaks("甲站<br>乙站") == "甲站 乙站"
    assert clean_breaks("") is None
