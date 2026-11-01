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
