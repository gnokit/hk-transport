from hk_transport import _places


def stop(name, latitude, longitude):
    return {
        "point": f"test:{name}",
        "mode": "bus",
        "stop": name,
        "name_zh": name,
        "name_en": None,
        "latitude": latitude,
        "longitude": longitude,
    }


def test_a_coordinate_pair_is_taken_as_a_point():
    point, note = _places.place("22.31930, 114.16940", {})
    assert note is None
    assert point["resolved_as"] == "coordinates"
    assert round(point["latitude"], 5) == 22.31930
    assert round(point["longitude"], 5) == 114.16940


def test_a_coordinate_pair_outside_the_world_is_rejected_without_a_lookup():
    point, note = _places.place("122.3193,114.1694", {})
    assert point is None
    assert "座標超出範圍" in note


def test_a_district_name_is_flagged_as_one_point():
    point = {"name_zh": "屯門", "latitude": 22.39508, "longitude": 113.97331}
    note = _places.district_note(point)
    assert "地區名" in note
    assert "22.39508" in note


def test_a_place_inside_a_district_is_not_flagged():
    point = {"name_zh": "屯門站", "latitude": 22.39, "longitude": 113.97}
    assert _places.district_note(point) is None


def test_a_coordinate_pair_is_not_flagged_as_a_district():
    point = {"name_zh": "22.31930,114.16940", "latitude": 22.3193, "longitude": 114.1694}
    assert _places.district_note(point) is None


def test_the_place_with_a_bad_label_point_falls_back_to_the_station():
    """香港國際機場 comes back 2.4 km west of the terminal; 機場 is the real node."""
    points = {
        "mtr:47": {
            "point": "mtr:47",
            "mode": "mtr",
            "stop": "47",
            "name_zh": "機場",
            "name_en": "Airport",
            "latitude": 22.31588,
            "longitude": 113.93649,
        },
        "mtr:39": {
            "point": "mtr:39",
            "mode": "mtr",
            "stop": "39",
            "name_zh": "香港",
            "name_en": "Hong Kong",
            "latitude": 22.2850,
            "longitude": 114.1580,
        },
    }
    found = {row["point"]: row for row in points.values()}
    point, note = _places.name_fallback("香港國際機場", found)
    assert point is not None
    assert point["name_zh"] == "機場"
    assert point["resolved_as"] == "stop_name"
    assert "已改用名稱相符的「機場」" in note


def test_the_longest_name_wins_and_ties_go_to_the_end_of_the_query():
    """香港國際機場 contains both 香港 and 機場; the facility type comes last."""
    points = {
        "a": stop("香港", 22.2850, 114.1580),
        "b": stop("機場", 22.31588, 113.93649),
    }
    found = {key: row for key, row in points.items()}
    point, _note = _places.name_fallback("香港國際機場", found)
    assert point["name_zh"] == "機場"

    long_name = {
        "c": stop("香港國際機場", 22.3150, 113.9370),
        "d": stop("機場", 22.31588, 113.93649),
    }
    point, _note = _places.name_fallback("香港國際機場", long_name)
    assert point["name_zh"] == "香港國際機場"


def test_a_query_with_no_stop_name_in_it_has_no_fallback():
    points = {"a": stop("南生圍", 22.4500, 114.0400)}
    point, note = _places.name_fallback("西貢", points)
    assert point is None
    assert note is None


def test_a_stop_without_coordinates_is_skipped():
    points = {"a": stop("機場", None, None)}
    point, note = _places.name_fallback("香港國際機場", points)
    assert point is None
    assert note is None
