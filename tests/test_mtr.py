from pathlib import Path

from hk_transport import mtr
from hk_transport._result import NO_ALERT, compose
from hk_transport.mtr import ALERT_CHECK_NEWS, UNKNOWN_SERVICE


def envelope(data, **overrides):
    result = {
        "dataset_id": "mtr-data-routes-fares-barrier-free-facilities",
        "endpoint": "https://example.test/table.csv",
        "retrieved_at": "2026-10-01T00:00:00+08:00",
        "data_at": None,
        "update_frequency": "monthly",
        "data": data,
        "note": None,
    }
    result.update(overrides)
    return result


def stop(line, direction, code, station_id, zh, en, sequence):
    return {
        "line_code": line,
        "direction": direction,
        "code": code,
        "id": station_id,
        "name_zh": zh,
        "name_en": en,
        "sequence": sequence,
    }


NETWORK = [
    stop("ISL", "DT", "CHW", "10", "柴灣", "Chai Wan", 1),
    stop("ISL", "DT", "TIH", "12", "天后", "Tin Hau", 2),
    stop("ISL", "DT", "ADM", "2", "金鐘", "Admiralty", 3),
    stop("ISL", "DT", "CEN", "1", "中環", "Central", 4),
    stop("TWL", "UT", "ADM", "2", "金鐘", "Admiralty", 1),
    stop("TWL", "UT", "TST", "3", "尖沙咀", "Tsim Sha Tsui", 2),
    stop("TWL", "UT", "TSW", "25", "荃灣", "Tsuen Wan", 3),
    stop("AEL", "UT", "HOK", "44", "香港", "Hong Kong", 1),
    stop("AEL", "UT", "KOW", "45", "九龍", "Kowloon", 2),
    stop("AEL", "UT", "AIR", "47", "機場", "Airport", 3),
    stop("EAL", "DT", "LOW", "76", "羅湖", "Lo Wu", 1),
    stop("EAL", "DT", "SHS", "75", "上水", "Sheung Shui", 2),
    stop("EAL", "LMC-DT", "LMC", "78", "落馬洲", "Lok Ma Chau", 1),
    stop("EAL", "LMC-DT", "SHS", "75", "上水", "Sheung Shui", 2),
    stop("EAL", "DT", "HUH", "64", "紅磡", "Hung Hom", 3),
]


def _keys(value, found):
    if isinstance(value, dict):
        found.update(value)
        for item in value.values():
            _keys(item, found)
    elif isinstance(value, list):
        for item in value:
            _keys(item, found)


def test_branch_directions_stay_separate(monkeypatch):
    monkeypatch.setattr(mtr.mtr_core, "lines_and_stations", lambda: envelope(NETWORK))
    result = mtr.mtr_lines(line="東鐵線")
    directions = {item["direction"]: item for item in result["data"]["lines"][0]["directions"]}
    assert directions.keys() == {"DT", "LMC-DT"}
    lo_wu = [station["name_zh"] for station in directions["DT"]["stations"]]
    lok_ma_chau = [station["name_zh"] for station in directions["LMC-DT"]["stations"]]
    assert "羅湖" in lo_wu and "落馬洲" not in lo_wu
    assert "落馬洲" in lok_ma_chau and "羅湖" not in lok_ma_chau
    assert directions["DT"]["first"]["name_zh"] == "羅湖"
    assert directions["DT"]["last"]["name_zh"] == "紅磡"


def test_chai_wan_to_tsuen_wan_transfers_at_admiralty(monkeypatch):
    monkeypatch.setattr(mtr.mtr_core, "lines_and_stations", lambda: envelope(NETWORK))
    result = mtr.mtr_journey("柴灣", "荃灣")
    legs = result["data"]["legs"]
    assert result["data"]["transfers"] == 1
    assert legs[0]["line_code"] == "ISL"
    assert legs[0]["alight"]["name_zh"] == "金鐘"
    assert legs[1]["line_code"] == "TWL"
    assert legs[1]["board"]["name_zh"] == "金鐘"
    assert [stop["name_zh"] for stop in legs[0]["stations"]] == ["柴灣", "天后", "金鐘"]
    assert [stop["name_zh"] for stop in legs[1]["stations"]] == ["金鐘", "尖沙咀", "荃灣"]
    names = set()
    _keys(result["data"], names)
    assert "duration" not in names
    assert "minutes" not in names


def test_path_can_cross_hong_kong_and_central(monkeypatch):
    monkeypatch.setattr(mtr.mtr_core, "lines_and_stations", lambda: envelope(NETWORK))
    result = mtr.mtr_journey("中環", "機場")
    walked = result["data"]["interchanges"]
    assert any(item["from"]["id"] == "1" and item["to"]["id"] == "44" for item in walked)
    assert result["data"]["legs"][-1]["alight"]["name_zh"] == "機場"
    assert result["data"]["legs"][-1]["line_code"] == "AEL"


def test_chinese_name_resolves_to_english_fare_row(monkeypatch):
    monkeypatch.setattr(mtr.mtr_core, "lines_and_stations", lambda: envelope(NETWORK))
    monkeypatch.setattr(
        mtr.mtr_core,
        "domestic_fares",
        lambda: envelope(
            [
                {
                    "from_id": "1",
                    "to_id": "64",
                    "from_name": "Central",
                    "to_name": "Hung Hom",
                    "fares": {"OCT_ADT_FARE": "10.4"},
                }
            ]
        ),
    )
    result = mtr.mtr_fare("中環", "紅磡")
    pair = result["data"]["pairs"][0]
    assert pair["from"]["id"] == "1"
    assert pair["fares"]["OCT_ADT_FARE"] == "10.4"
    assert pair["fares"]["OCT_STD_FARE"] is None
    assert "OCT_STD_FARE" in result["note"]


def test_no_alert_uses_the_prescribed_note(monkeypatch):
    monkeypatch.setattr(mtr.mtr_core, "lines_and_stations", lambda: envelope(NETWORK))
    monkeypatch.setattr(
        mtr.mtr_core,
        "next_train",
        lambda line, station: envelope(
            {
                "status": 1,
                "message": "successful",
                "url": None,
                "isdelay": "N",
                "directions": [
                    {
                        "direction": "UP",
                        "trains": [
                            {
                                "seq": "1",
                                "dest": "CHW",
                                "platform": "3",
                                "time": "2026-10-29 09:32:08",
                                "ttnt": "0",
                                "valid": "Y",
                            }
                        ],
                    }
                ],
            },
            dataset_id="mtr-data2-nexttrain-data",
            endpoint="https://example.test/next",
            data_at="2026-10-29T09:32:08+08:00",
            update_frequency="10s",
        ),
    )
    result = mtr.mtr_next_train("港島線", "金鐘")
    assert result["note"] == NO_ALERT
    assert result["data"]["alert"] is None
    assert "全線正常" not in (result["note"] or "")
    assert result["data"]["directions"][0]["trains"][0]["dest"]["name_zh"] == "柴灣"


def test_alert_tells_the_agent_to_check_traffic_news(monkeypatch):
    monkeypatch.setattr(mtr.mtr_core, "lines_and_stations", lambda: envelope(NETWORK))
    monkeypatch.setattr(
        mtr.mtr_core,
        "next_train",
        lambda line, station: envelope(
            {
                "status": 0,
                "message": "觀塘線服務延誤",
                "url": "https://example.test/mtr-news",
                "isdelay": "Y",
                "directions": [],
            },
            dataset_id="mtr-data2-nexttrain-data",
            endpoint="https://example.test/next",
            data_at="2026-10-29T11:00:00+08:00",
            update_frequency="10s",
        ),
    )
    result = mtr.mtr_next_train("港島線", "金鐘")
    assert result["data"]["alert"]["status"] == 0
    assert result["data"]["alert"]["message"] == "觀塘線服務延誤"
    assert result["data"]["alert"]["url"] == "https://example.test/mtr-news"
    assert result["note"] == ALERT_CHECK_NEWS
    assert "special_traffic_news" in result["note"]


def test_barrier_free_drops_rows_that_are_not_present(monkeypatch):
    monkeypatch.setattr(mtr.mtr_core, "lines_and_stations", lambda: envelope(NETWORK))
    monkeypatch.setattr(
        mtr.mtr_core,
        "barrier_free_facilities",
        lambda: envelope(
            [
                {
                    "station_id": "2",
                    "key": "MJ1",
                    "present": True,
                    "exit_zh": "A 出口",
                    "exit_en": "Exit A",
                    "coordinate": None,
                },
                {
                    "station_id": "2",
                    "key": "MJ4",
                    "present": False,
                    "exit_zh": None,
                    "exit_en": None,
                    "coordinate": None,
                },
            ]
        ),
    )
    monkeypatch.setattr(
        mtr.mtr_core,
        "barrier_free_categories",
        lambda: envelope(
            [
                {
                    "key": "MJ1",
                    "category_zh": "行動不便人士設施",
                    "category_en": "Facilities for Mobility Impaired",
                    "name_zh": "闊閘機",
                    "name_en": "Wide Gates",
                }
            ]
        ),
    )
    result = mtr.mtr_barrier_free("金鐘")
    facilities = result["data"]["stations"][0]["facilities"]
    assert [item["key"] for item in facilities] == ["MJ1"]
    assert facilities[0]["name_zh"] == "闊閘機"
    assert facilities[0]["coordinate"] is None


def test_light_rail_specials_are_flagged(monkeypatch):
    monkeypatch.setattr(
        mtr.mtr_core,
        "light_rail_routes",
        lambda: envelope([stop("610", "1", "YLL", "600", "元朗", "Yuen Long", 1)]),
    )
    monkeypatch.setattr(
        mtr.mtr_core,
        "light_rail_next_train",
        lambda station_id, with_special=1: envelope(
            {
                "status": 1,
                "platforms": [
                    {
                        "platform_id": 1,
                        "trains": [{"route_no": "610", "special": True, "time_zh": "5 分鐘"}],
                    }
                ]
            },
            dataset_id="mtr-lrnt_data-light-rail-nexttrain-data",
            endpoint="https://example.test/lrt",
            data_at="2026-10-29T10:00:00+08:00",
            update_frequency="10s",
        ),
    )
    result = mtr.light_rail_next("元朗")
    assert result["data"]["station"]["id"] == "600"
    assert result["data"]["platforms"][0]["trains"][0]["special"] is True


def test_bus_fare_is_one_row_and_schedule_is_called_once(monkeypatch):
    calls = []
    monkeypatch.setattr(
        mtr.mtr_core,
        "bus_routes",
        lambda: envelope(
            [
                {
                    "route_id": "K52",
                    "name_zh": "悅湖山莊至龍鼓灘",
                    "name_en": "Yuet Wu Villa to Lung Kwu Tan",
                    "circular": False,
                }
            ]
        ),
    )
    monkeypatch.setattr(
        mtr.mtr_core,
        "bus_stops",
        lambda: envelope(
            [
                {
                    "route_id": "K52",
                    "direction": "O",
                    "sequence": 2,
                    "id": "b",
                    "name_zh": "龍鼓灘",
                    "name_en": "Lung Kwu Tan",
                    "latitude": 22.39,
                    "longitude": 113.92,
                },
                {
                    "route_id": "K52",
                    "direction": "O",
                    "sequence": 1,
                    "id": "a",
                    "name_zh": "悅湖山莊",
                    "name_en": "Yuet Wu Villa",
                    "latitude": 22.37,
                    "longitude": 113.96,
                },
            ]
        ),
    )
    monkeypatch.setattr(
        mtr.mtr_core,
        "bus_fares",
        lambda: envelope([{"route_id": "K52", "fares": {"FARE_OCTO_ADULT": "10.1"}}]),
    )

    def schedule(route_name, language="zh"):
        calls.append((route_name, language))
        return envelope(
            {"stops": []},
            dataset_id="mtr-mtr_bus-mtr-bus-eta-data",
            endpoint="https://example.test/bus",
            data_at=None,
            update_frequency="10s",
        )

    monkeypatch.setattr(mtr.mtr_core, "bus_schedule", schedule)
    result = mtr.mtr_bus("k52")
    assert calls == [("K52", "zh")]
    assert [stop["name_zh"] for stop in result["data"]["stops"]] == ["悅湖山莊", "龍鼓灘"]
    assert result["data"]["fare"] == {"FARE_OCTO_ADULT": "10.1"}
    assert "FARE_OCTO_CHILD" not in result["data"]["fare"]


def test_same_route_id_with_two_names_is_one_route(monkeypatch):
    calls = []
    monkeypatch.setattr(
        mtr.mtr_core,
        "bus_routes",
        lambda: envelope(
            [
                {
                    "route_id": "K52",
                    "name_zh": "悅湖山莊至龍鼓灘",
                    "name_en": "Yuet Wu Villa to Lung Kwu Tan",
                    "circular": False,
                },
                {
                    "route_id": "K52",
                    "name_zh": "輕鐵屯門站至龍鼓灘",
                    "name_en": "LR Tuen Mun Stop to Lung Kwu Tan",
                    "circular": False,
                },
            ]
        ),
    )
    monkeypatch.setattr(mtr.mtr_core, "bus_stops", lambda: envelope([]))
    monkeypatch.setattr(
        mtr.mtr_core,
        "bus_fares",
        lambda: envelope(
            [
                {"route_id": "K52", "fares": {"FARE_OCTO_ADULT": "5.1"}},
                {"route_id": "K52", "fares": {"FARE_OCTO_ADULT": "5.1"}},
            ]
        ),
    )

    def schedule(route_name, language="zh"):
        calls.append((route_name, language))
        return envelope(
            {"stops": []},
            dataset_id="mtr-mtr_bus-mtr-bus-eta-data",
            endpoint="https://example.test/bus",
            data_at="2026-10-29T10:00:00+08:00",
            update_frequency="10s",
        )

    monkeypatch.setattr(mtr.mtr_core, "bus_schedule", schedule)
    result = mtr.mtr_bus("K52")
    assert calls == [("K52", "zh")]
    assert result["data"]["route"]["names"] == [
        {"name_zh": "悅湖山莊至龍鼓灘", "name_en": "Yuet Wu Villa to Lung Kwu Tan"},
        {"name_zh": "輕鐵屯門站至龍鼓灘", "name_en": "LR Tuen Mun Stop to Lung Kwu Tan"},
    ]
    assert result["data"]["fare"] == {"FARE_OCTO_ADULT": "5.1"}
    assert result["note"] is None


def test_airport_express_does_not_copy_domestic_concessions(monkeypatch):
    monkeypatch.setattr(mtr.mtr_core, "lines_and_stations", lambda: envelope(NETWORK))
    monkeypatch.setattr(
        mtr.mtr_core,
        "airport_express_fares",
        lambda: envelope(
            [
                {
                    "from_id": "44",
                    "to_id": "47",
                    "from_name": "Hong Kong",
                    "to_name": "Airport",
                    "fares": {
                        "OCT_ADT_FARE": "74",
                        "OCT_CHD_FARE": "35",
                        "SINGLE_ADT_FARE": "80",
                        "SINGLE_CHD_FARE": "40",
                    },
                }
            ]
        ),
    )
    result = mtr.mtr_airport_express_fare("香港", "機場")
    fares = result["data"]["pairs"][0]["fares"]
    assert "OCT_CON_ELDERLY_FARE" not in fares
    assert "OCT_STD_FARE" not in fares
    assert "OCT_JOYYOU_SIXTY_FARE" not in fares
    assert "成人同小童" in result["note"]


def test_missing_station_does_not_invent_one(monkeypatch):
    monkeypatch.setattr(mtr.mtr_core, "lines_and_stations", lambda: envelope(NETWORK))
    result = mtr.mtr_journey("不存在", "荃灣")
    assert result["data"] is None
    assert "不存在" in result["note"]


def next_board(station, dest, times):
    trains = [
        {
            "seq": str(index),
            "dest": dest,
            "platform": "1",
            "time": text,
            "ttnt": "1",
            "valid": "Y",
        }
        for index, text in enumerate(times, start=1)
    ]
    return envelope(
        {
            "status": 1,
            "message": "successful",
            "url": None,
            "isdelay": "N",
            "curr_time": "2026-10-29 10:10:00",
            "sys_time": "2026-10-29 10:10:00",
            "directions": [
                {"direction": "UP", "trains": trains},
                {"direction": "DOWN", "trains": []},
            ],
        },
        dataset_id="mtr-data2-nexttrain-data",
        endpoint=f"https://example.test/next?sta={station}",
        data_at="2026-10-29T10:10:00+08:00",
        update_frequency="10s",
    )


def test_ride_estimate_sums_links_that_agree(monkeypatch):
    boards = {
        ("ISL", "CHW"): next_board("CHW", "CEN", ["2026-10-29 10:00:00", "2026-10-29 10:04:00", "2026-10-29 10:08:00"]),
        ("ISL", "TIH"): next_board("TIH", "CEN", ["2026-10-29 10:02:00", "2026-10-29 10:06:00", "2026-10-29 10:10:00"]),
        ("ISL", "ADM"): next_board("ADM", "CEN", ["2026-10-29 10:04:00", "2026-10-29 10:08:00", "2026-10-29 10:12:00"]),
        ("TWL", "ADM"): next_board("ADM", "TSW", ["2026-10-29 10:06:00", "2026-10-29 10:10:00", "2026-10-29 10:14:00"]),
        ("TWL", "TST"): next_board("TST", "TSW", ["2026-10-29 10:08:00", "2026-10-29 10:12:00", "2026-10-29 10:16:00"]),
        ("TWL", "TSW"): next_board("TSW", "TSW", ["2026-10-29 10:10:00", "2026-10-29 10:14:00", "2026-10-29 10:18:00"]),
    }
    monkeypatch.setattr(mtr.mtr_core, "lines_and_stations", lambda: envelope(NETWORK))
    monkeypatch.setattr(mtr.mtr_core, "next_train", lambda line, station: boards[(line, station)])
    result = mtr.mtr_ride_estimate("柴灣", "荃灣")
    assert result["data"]["minutes"] == 8
    assert [link["minutes"] for link in result["data"]["links"]] == [2, 2, 2, 2]
    assert "不包括轉車步行和等車" in result["note"]
    assert "對不齊" not in result["note"]


def test_ride_estimate_leaves_total_empty_when_a_link_disagrees(monkeypatch):
    boards = {
        ("ISL", "CHW"): next_board("CHW", "CEN", ["2026-10-29 10:00:00", "2026-10-29 10:04:00", "2026-10-29 10:08:00"]),
        ("ISL", "TIH"): next_board("TIH", "CEN", ["2026-10-29 10:02:00", "2026-10-29 10:06:00", "2026-10-29 10:10:00"]),
        ("ISL", "ADM"): next_board(
            "ADM",
            "CEN",
            ["2026-10-29 10:02:00", "2026-10-29 10:04:00", "2026-10-29 10:06:00", "2026-10-29 10:08:00"],
        ),
    }
    monkeypatch.setattr(mtr.mtr_core, "lines_and_stations", lambda: envelope(NETWORK))
    monkeypatch.setattr(mtr.mtr_core, "next_train", lambda line, station: boards[(line, station)])
    result = mtr.mtr_ride_estimate("柴灣", "金鐘")
    assert result["data"]["minutes"] is None
    assert [link["minutes"] for link in result["data"]["links"]] == [2, None]
    assert "天后到金鐘" in result["note"]
    assert "沒有加總全程" in result["note"]


def test_same_station_estimate_is_zero(monkeypatch):
    def fail(line, station):
        raise AssertionError("same station does not need a live train")

    monkeypatch.setattr(mtr.mtr_core, "lines_and_stations", lambda: envelope(NETWORK))
    monkeypatch.setattr(mtr.mtr_core, "next_train", fail)
    result = mtr.mtr_ride_estimate("金鐘", "金鐘")
    assert result["data"]["minutes"] == 0
    assert result["data"]["links"] == []


def test_usecase_module_has_no_url_or_cache():
    text = Path(mtr.__file__).read_text(encoding="utf-8")
    assert "http://" not in text
    assert "https://" not in text
    assert "_http" not in text
    assert ".cache" not in text


def test_absent_fare_pair_claims_no_missing_columns(monkeypatch):
    monkeypatch.setattr(mtr.mtr_core, "lines_and_stations", lambda: envelope(NETWORK))
    monkeypatch.setattr(mtr.mtr_core, "domestic_fares", lambda: envelope([]))
    result = mtr.mtr_fare("中環", "紅磡")
    assert result["data"]["pairs"][0]["fares"] is None
    assert "車費檔沒有這一對車站" in result["note"]
    assert "OCT_ADT_FARE" not in result["note"]


def test_missing_status_does_not_claim_no_special_arrangement(monkeypatch):
    monkeypatch.setattr(mtr.mtr_core, "lines_and_stations", lambda: envelope(NETWORK))
    monkeypatch.setattr(
        mtr.mtr_core,
        "next_train",
        lambda line, station: envelope(
            {"message": None, "url": None, "isdelay": None, "directions": []},
            dataset_id="mtr-data2-nexttrain-data",
            endpoint="https://example.test/next",
            data_at="2026-10-29T10:00:00+08:00",
            update_frequency="10s",
        ),
    )
    result = mtr.mtr_next_train("港島線", "金鐘")
    assert result["data"]["alert"] is None
    assert result["note"] == UNKNOWN_SERVICE
    assert result["note"] != NO_ALERT


def one_way_board(direction, dest, times):
    trains = [
        {
            "seq": str(index),
            "dest": dest,
            "platform": "1",
            "time": text,
            "ttnt": "1",
            "valid": "Y",
        }
        for index, text in enumerate(times, start=1)
    ]
    other = "DOWN" if direction == "UP" else "UP"
    return envelope(
        {
            "status": 1,
            "message": "successful",
            "url": None,
            "isdelay": "N",
            "curr_time": "2026-10-29 10:00:00",
            "sys_time": "2026-10-29 10:00:00",
            "directions": [
                {"direction": direction, "trains": trains},
                {"direction": other, "trains": []},
            ],
        },
        dataset_id="mtr-data2-nexttrain-data",
        endpoint=f"https://example.test/next?sta={direction}",
        data_at="2026-10-29T10:00:00+08:00",
        update_frequency="10s",
    )


def test_ride_estimate_never_pairs_the_two_directions(monkeypatch):
    boards = {
        ("ISL", "CHW"): one_way_board("UP", "CEN", ["2026-10-29 10:00:00", "2026-10-29 10:04:00"]),
        ("ISL", "TIH"): one_way_board("DOWN", "CEN", ["2026-10-29 10:02:00", "2026-10-29 10:06:00"]),
    }
    monkeypatch.setattr(mtr.mtr_core, "lines_and_stations", lambda: envelope(NETWORK))
    monkeypatch.setattr(mtr.mtr_core, "next_train", lambda line, station: boards[(line, station)])
    result = mtr.mtr_ride_estimate("柴灣", "天后")
    assert result["data"]["links"][0]["minutes"] is None
    assert result["data"]["minutes"] is None


def test_ride_estimate_has_no_upper_cap(monkeypatch):
    boards = {
        ("ISL", "CHW"): next_board("CHW", "CEN", ["2026-10-29 10:00:00", "2026-10-29 10:12:00", "2026-10-29 10:24:00"]),
        ("ISL", "TIH"): next_board("TIH", "CEN", ["2026-10-29 10:09:00", "2026-10-29 10:21:00", "2026-10-29 10:33:00"]),
    }
    monkeypatch.setattr(mtr.mtr_core, "lines_and_stations", lambda: envelope(NETWORK))
    monkeypatch.setattr(mtr.mtr_core, "next_train", lambda line, station: boards[(line, station)])
    result = mtr.mtr_ride_estimate("柴灣", "天后")
    assert result["data"]["links"][0]["minutes"] == 9
    assert result["data"]["minutes"] == 9


def test_route_fare_unifies_duplicate_rows_and_reports_two_sets():
    rows = [
        {"route_id": "K52", "fares": {"FARE_OCTO_ADULT": "5.1"}},
        {"route_id": "K52", "fares": {"FARE_OCTO_ADULT": "5.1"}},
    ]
    assert mtr._route_fare(rows, "K52") == ({"FARE_OCTO_ADULT": "5.1"}, None)
    rows.append({"route_id": "K52", "fares": {"FARE_OCTO_ADULT": "6"}})
    fare, note = mtr._route_fare(rows, "K52")
    assert len(fare) == 2
    assert "多於一套車費" in note
    assert mtr._route_fare([], "K52") == (None, "車費檔沒有這條路線。")


def test_compose_with_no_sources_invents_nothing():
    result = compose([], None, note="要給路線，或同時給起點同終點。")
    assert result["dataset_id"] is None
    assert result["endpoint"] is None
    assert result["retrieved_at"] is None
    assert result["update_frequency"] is None
    assert result["data"] is None


def test_compose_keeps_a_yearly_source_labelled_yearly():
    yearly = envelope(
        [],
        dataset_id="hk-landsd-openmap-development-location-search-api",
        endpoint="https://example.test/exits",
        update_frequency="yearly",
    )
    result = compose([yearly], [{"exit": "A"}])
    assert result["update_frequency"] == "yearly"
    assert result["data_at"] is None


def test_light_rail_status_is_kept(monkeypatch):
    monkeypatch.setattr(
        mtr.mtr_core,
        "light_rail_routes",
        lambda: envelope([stop("610", "1", "YLL", "600", "元朗", "Yuen Long", 1)]),
    )
    monkeypatch.setattr(
        mtr.mtr_core,
        "light_rail_next_train",
        lambda station_id, with_special=1: envelope(
            {"status": 1, "platforms": []},
            dataset_id="mtr-lrnt_data-light-rail-nexttrain-data",
            endpoint="https://example.test/lrt",
            data_at="2026-10-29T10:00:00+08:00",
            update_frequency="10s",
        ),
    )
    result = mtr.light_rail_next("元朗")
    assert result["data"]["status"] == 1
