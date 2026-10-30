import pytest

from hk_transport import bus_core
from hk_transport._result import MtrError

STAMP = "2026-10-30T07:00:00+08:00"


def payload(data, stamp=STAMP):
    return {"generated_timestamp": stamp, "data": data}


def fake(monkeypatch, body):
    seen = []

    def _fetch(url, **kwargs):
        seen.append((url, kwargs))
        return body, STAMP

    monkeypatch.setattr(bus_core, "fetch_json", _fetch)
    return seen


def test_kmb_routes_read_the_whole_table(monkeypatch):
    seen = fake(
        monkeypatch,
        payload(
            [
                {
                    "route": "1A",
                    "bound": "O",
                    "service_type": "1",
                    "orig_tc": "中秀茂坪",
                    "orig_en": "SAU MAU PING",
                    "dest_tc": "尖沙咀碼頭",
                    "dest_en": "STAR FERRY",
                }
            ]
        ),
    )
    result = bus_core.kmb_routes()
    assert result["dataset_id"] == bus_core.KMB_DATASET
    assert result["data_at"] == STAMP
    assert result["update_frequency"] == "daily"
    assert result["data"][0]["route"] == "1A"
    assert result["data"][0]["dest_zh"] == "尖沙咀碼頭"
    assert "九巴同龍運" in result["note"]
    assert seen[0][0].endswith("/kmb/route/")


def test_kmb_bound_accepts_code_or_word(monkeypatch):
    seen = fake(monkeypatch, {"data": {"route": "1A", "bound": "O", "service_type": "1"}})
    bus_core.kmb_route("1A", "O")
    bus_core.kmb_route("1A", "outbound")
    assert seen[0][0].endswith("/route/1A/outbound/1")
    assert seen[1][0].endswith("/route/1A/outbound/1")


def test_kmb_bound_rejects_anything_else(monkeypatch):
    fake(monkeypatch, {"data": {}})
    with pytest.raises(MtrError):
        bus_core.kmb_route("1A", "north")


def test_kmb_route_stops_keep_the_sequence(monkeypatch):
    fake(
        monkeypatch,
        payload(
            [
                {"route": "1A", "bound": "O", "service_type": "1", "seq": "1", "stop": "ABC"},
                {"route": "1A", "bound": "O", "service_type": "1", "seq": "2", "stop": "DEF"},
            ]
        ),
    )
    rows = bus_core.kmb_route_stops("1A")["data"]
    assert [row["stop"] for row in rows] == ["ABC", "DEF"]
    assert [row["seq"] for row in rows] == [1.0, 2.0]


def test_kmb_eta_is_live_and_never_cached(monkeypatch):
    seen = fake(
        monkeypatch,
        payload(
            [
                {
                    "co": "KMB",
                    "route": "1A",
                    "dir": "O",
                    "eta": "2026-10-30T07:05:00+08:00",
                    "eta_seq": 1,
                }
            ]
        ),
    )
    result = bus_core.kmb_route_eta("1A")
    assert result["update_frequency"] == "60s"
    assert result["data"][0]["eta"] == "2026-10-30T07:05:00+08:00"
    assert seen[0][1]["cache"] is False


def test_eta_with_no_time_stays_empty(monkeypatch):
    fake(monkeypatch, payload([{"co": "KMB", "route": "1A", "dir": "O", "eta": None}]))
    row = bus_core.kmb_route_eta("1A")["data"][0]
    assert row["eta"] is None
    assert row["dest_zh"] is None


def test_nlb_stops_keep_the_fare_and_the_holiday_fare(monkeypatch):
    fake(
        monkeypatch,
        {
            "stops": [
                {
                    "stopId": 1,
                    "stopName_c": "梅窩碼頭",
                    "stopName_e": "Mui Wo Ferry Pier",
                    "latitude": "22.26466400",
                    "longitude": "114.00155400",
                    "fare": "12.7",
                    "fareHoliday": "21.4",
                }
            ]
        },
    )
    result = bus_core.nlb_stops("1")
    row = result["data"][0]
    assert row["fare"] == 12.7
    assert row["fare_holiday"] == 21.4
    assert row["latitude"] == 22.264664
    assert result["dataset_id"] == bus_core.NLB_DATASET


def test_nlb_routes_read_overnight_and_special_flags(monkeypatch):
    fake(
        monkeypatch,
        {
            "routes": [
                {
                    "routeId": 2,
                    "routeNo": "1",
                    "routeName_c": "大澳 > 梅窩碼頭",
                    "routeName_e": "Tai O > Mui Wo Ferry Pier",
                    "overnightRoute": 1,
                    "specialRoute": 0,
                }
            ]
        },
    )
    row = bus_core.nlb_routes()["data"][0]
    assert row["route"] == "1"
    assert row["overnight"] is True
    assert row["special"] is False


def test_citybus_route_stops_read_the_direction(monkeypatch):
    fake(
        monkeypatch,
        payload([{"co": "CTB", "route": "1", "dir": "O", "seq": 1, "stop": "001027"}]),
    )
    row = bus_core.ctb_route_stops("1", "outbound")["data"][0]
    assert row["direction"] == "O"
    assert row["stop"] == "001027"


def test_citybus_eta_is_live(monkeypatch):
    seen = fake(monkeypatch, payload([]))
    result = bus_core.ctb_eta("001017", "1")
    assert result["update_frequency"] == "60s"
    assert seen[0][1]["cache"] is False


def test_snapshot_is_read_without_network(monkeypatch):
    def no_network(*args, **kwargs):
        raise AssertionError("the snapshot must not call the network")

    monkeypatch.setattr(bus_core, "fetch_json", no_network)
    result = bus_core.kmb_route_stops_all()
    stored = bus_core._load_snapshot()["variants"]
    assert len(result["data"]) == sum(len(stops) for stops in stored.values())
    assert result["data"][0].keys() == {"route", "direction", "service_type", "seq", "stop"}
    assert "快照" in result["note"]
    assert "超過 30 日" not in result["note"]


def test_stale_snapshot_is_still_returned(monkeypatch):
    snapshot = bus_core._load_snapshot()
    old = {**snapshot, "retrieved_at": "2020-01-01T00:00:00+08:00"}
    monkeypatch.setattr(bus_core, "_load_snapshot", lambda: old)
    result = bus_core.kmb_route_stops_all()
    assert result["data"]
    assert "超過 30 日" in result["note"]


def test_missing_snapshot_names_the_rebuild_script(monkeypatch, tmp_path):
    monkeypatch.setattr(bus_core, "_snapshot_path", lambda: tmp_path / "missing.json")
    with pytest.raises(MtrError) as caught:
        bus_core.kmb_route_stops_all()
    assert "build_bus_route_stops" in str(caught.value)


def test_td_fares_stream_the_geojson_and_keep_one_row_per_variant(monkeypatch, tmp_path):
    import json

    path = tmp_path / "bus.json"
    features = [
        {
            "properties": {
                "companyCode": "KMB",
                "routeNameE": "B1",
                "routeType": 1,
                "serviceMode": "R",
                "fullFare": 15.3,
                "journeyTime": 50,
                "locStartNameC": "天慈",
                "locStartNameE": "TIN TSZ",
                "locEndNameC": "落馬洲站",
                "locEndNameE": "LOK MA CHAU STATION Please inquire with the operator.",
                "lastUpdateDate": "2026-05-22T00:00:00",
                "stopSeq": 1,
                "stopId": "A",
            }
        },
        {
            "properties": {
                "companyCode": "KMB",
                "routeNameE": "B1",
                "routeType": 1,
                "serviceMode": "R",
                "fullFare": 15.3,
                "journeyTime": 50,
                "locEndNameE": "DUPLICATE STOP ROW",
                "stopSeq": 2,
                "stopId": "B",
            }
        },
    ]
    path.write_text(json.dumps({"type": "FeatureCollection", "features": features}), encoding="utf-8")
    monkeypatch.setattr(bus_core, "cached_file", lambda url, **kw: (path, "2026-10-30T00:00:00+08:00"))
    result = bus_core.td_bus_fares()
    assert len(result["data"]) == 1
    row = result["data"][0]
    assert row["fare"] == 15.3
    assert row["journey_time_minutes"] == 50.0
    assert row["dest_en"] == "LOK MA CHAU STATION"
    assert row["remark"] == "Please inquire with the operator."
    assert result["data_at"] == "2026-05-22T00:00:00+08:00"
