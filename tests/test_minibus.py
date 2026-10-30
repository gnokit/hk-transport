import pytest

from hk_transport import minibus


def stop(stop_id, name, latitude, longitude, district="NT"):
    return {
        "stop": stop_id,
        "name_zh": name,
        "name_en": name,
        "latitude": latitude,
        "longitude": longitude,
        "district": district,
    }


STOPS = [
    stop("S1", "福康街", 22.0000, 114.0000),
    stop("S2", "中站", 22.0100, 114.0100),
    stop("S3", "攸潭尾", 22.0200, 114.0200),
    stop("S4", "更遠", 22.0300, 114.0300),
    stop("H1", "港島一", 22.2000, 114.2000, district="HKI"),
]


def route(route_id, district, code, seq, origin, dest, service_mode="R", special_type=0):
    return {
        "district": district,
        "route": code,
        "route_en": code,
        "route_id": route_id,
        "route_seq": seq,
        "route_type": 2,
        "service_mode": service_mode,
        "special_type": special_type,
        "origin_zh": origin,
        "origin_en": origin,
        "dest_zh": dest,
        "dest_en": dest,
        "fare": 9.0,
        "journey_time_minutes": 18.0,
    }


ROUTES = [
    route(100, "NT", "37", 1, "福康街", "攸潭尾"),
    route(101, "NT", "38", 1, "攸潭尾", "更遠"),
    route(200, "HKI", "37", 1, "港島一", "港島二"),
]


def stop_row(route_id, district, code, route_seq, seq, stop_id, name_zh, lat, lon, service_mode="R", special_type=0):
    return {
        "district": district,
        "route": code,
        "route_id": route_id,
        "route_seq": route_seq,
        "service_mode": service_mode,
        "special_type": special_type,
        "seq": seq,
        "stop": stop_id,
        "name_zh": name_zh,
        "name_en": name_zh,
        "latitude": lat,
        "longitude": lon,
        "pick_drop": 3,
        "fare": 9.0,
        "journey_time_minutes": 18.0,
    }


STOP_ROWS = [
    stop_row(100, "NT", "37", 1, 1, "S1", "福康街", 22.0000, 114.0000),
    stop_row(100, "NT", "37", 1, 2, "S2", "中站", 22.0100, 114.0100),
    stop_row(100, "NT", "37", 1, 3, "S3", "攸潭尾", 22.0200, 114.0200),
    stop_row(101, "NT", "38", 1, 1, "S3", "攸潭尾", 22.0200, 114.0200),
    stop_row(101, "NT", "38", 1, 2, "S4", "更遠", 22.0300, 114.0300),
]


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


def wire(monkeypatch, stops=None, routes=None, rows=None):
    monkeypatch.setattr(minibus.minibus_core, "gmb_stops", lambda: envelope(stops or STOPS))
    monkeypatch.setattr(minibus.minibus_core, "gmb_routes", lambda: envelope(routes or ROUTES))
    monkeypatch.setattr(
        minibus.minibus_core, "gmb_route_stops", lambda: envelope(rows or STOP_ROWS)
    )


def test_a_direct_minibus_is_one_option(monkeypatch):
    wire(monkeypatch)
    result = minibus.minibus_journey("福康街", "攸潭尾")
    option = result["data"]["options"][0]
    assert option["transfers"] == 0
    assert [leg["route"] for leg in option["legs"]] == ["37"]
    assert option["legs"][0]["district"] == "NT"
    assert "一個點" in result["note"]


def test_a_second_ride_is_a_transfer(monkeypatch):
    wire(monkeypatch)
    result = minibus.minibus_journey("福康街", "更遠")
    option = result["data"]["options"][0]
    assert option["transfers"] == 1
    assert [leg["route"] for leg in option["legs"]] == ["37", "38"]


def test_a_night_or_distant_place_keeps_the_nearest_stop_distance(monkeypatch):
    wire(monkeypatch)
    monkeypatch.setattr(
        minibus,
        "_place",
        lambda text, stops: (
            {"query": text, "name_zh": "遠地方", "latitude": 22.5, "longitude": 114.5},
            None,
        ),
    )
    result = minibus.minibus_journey("福康街", "遠地方", walk=400)
    assert result["data"] is None
    assert "400 米內沒有小巴站" in result["note"]
    assert "最近的是" in result["note"]


def test_a_code_in_two_districts_is_listed_for_both(monkeypatch):
    wire(monkeypatch)
    result = minibus.minibus_route("37")
    assert len(result["data"]["variants"]) == 2
    assert "2 個區域都有" in result["note"]
    assert {row["district"] for row in result["data"]["variants"]} == {"NT", "HKI"}


def test_a_region_narrows_the_route(monkeypatch):
    wire(monkeypatch)
    result = minibus.minibus_route("37", region="NT")
    assert len(result["data"]["variants"]) == 1
    assert result["data"]["variants"][0]["district"] == "NT"
    assert "個區域都有" not in result["note"]


def test_an_unknown_route_says_so(monkeypatch):
    wire(monkeypatch)
    result = minibus.minibus_route("999")
    assert result["data"] is None
    assert "找不到小巴路線" in result["note"]


def test_fare_lists_each_variant_with_its_district(monkeypatch):
    wire(monkeypatch)
    result = minibus.minibus_fare("37")
    assert len(result["data"]["variants"]) == 2
    assert "成人全程價" in result["note"]
    assert "唔係分段收費" in result["note"]


def test_direct_requires_the_same_direction_and_order(monkeypatch):
    wire(monkeypatch)
    forward = minibus.minibus_direct("福康街", "攸潭尾")
    assert forward["data"]["direct"][0]["route"] == "37"
    backward = minibus.minibus_direct("攸潭尾", "福康街")
    assert backward["data"] is None
    assert "沒有一程過" in backward["note"]


def test_eta_needs_a_stop_because_there_is_no_route_level_endpoint(monkeypatch):
    wire(monkeypatch)
    result = minibus.minibus_eta(route="37")
    assert result["data"] is None
    assert "要指定一個站" in result["note"]


def test_eta_filters_by_route_id(monkeypatch):
    wire(monkeypatch)

    def eta(stop_id):
        return {
            **envelope(
                [
                    {"route_id": 100, "route_seq": 1, "stop_seq": 3, "enabled": True, "eta": []},
                    {"route_id": 101, "route_seq": 1, "stop_seq": 1, "enabled": True, "eta": []},
                ]
            ),
            "update_frequency": "every minute",
        }

    monkeypatch.setattr(minibus.minibus_core, "gmb_stop_eta", eta)
    result = minibus.minibus_eta(route="37", stop="攸潭尾")
    assert [row["route_id"] for row in result["data"]["eta"]] == [100]
    assert "37" in result["note"]


def test_the_three_no_data_commands_return_null_with_a_reason(monkeypatch):
    for call, word in (
        (minibus.minibus_service_hours, "服務時間"),
        (minibus.minibus_frequency, "班次"),
        (minibus.minibus_accessibility, "低地台"),
    ):
        result = call("37")
        assert result["data"] is None
        assert word in result["note"]


def test_red_minibus_has_no_data_and_says_why(monkeypatch):
    result = minibus.red_minibus("旺角至荃灣")
    assert result["data"] is None
    assert "固定路線" in result["note"]
    assert "綠色專線小巴" in result["note"]
