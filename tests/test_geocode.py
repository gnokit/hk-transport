import pytest

from hk_transport import geocode
from hk_transport._result import MtrError

# Nam Sang Wai, as the search returns it: HK1980 grid, no latitude.
ROW = {
    "nameZH": "南生圍",
    "nameEN": "Nam Sang Wai",
    "addressZH": "",
    "addressEN": "",
    "districtZH": "元朗區",
    "districtEN": "Yuen Long District",
    "x": 821871,
    "y": 835987,
}


def fake(rows):
    def call(url, *, dataset_id, cache=True, timeout=30, headers=None):
        return rows, "2026-10-30T12:00:00+08:00"

    return call


def test_grid_coordinates_are_converted_to_latitude_and_longitude(monkeypatch):
    monkeypatch.setattr(geocode, "fetch_json", fake([ROW]))
    row = geocode.place_search("南生圍")["data"][0]
    assert row["name_zh"] == "南生圍"
    assert row["district_zh"] == "元朗區"
    assert row["easting"] == 821871
    assert row["latitude"] == pytest.approx(22.4633, abs=0.001)
    assert row["longitude"] == pytest.approx(114.0370, abs=0.001)


def test_the_query_is_url_encoded_and_the_endpoint_recorded(monkeypatch):
    seen = {}

    def call(url, *, dataset_id, cache=True, timeout=30, headers=None):
        seen["url"] = url
        seen["dataset_id"] = dataset_id
        seen["cache"] = cache
        return [ROW], "2026-10-30T12:00:00+08:00"

    monkeypatch.setattr(geocode, "fetch_json", call)
    result = geocode.place_search("南生圍")
    assert "q=%E5%8D%97%E7%94%9F%E5%9C%8D" in seen["url"]
    assert seen["dataset_id"] == "hk-landsd-openmap-development-location-search-api"
    assert seen["cache"] is False
    assert result["endpoint"] == seen["url"]
    assert result["data_at"] is None
    assert result["update_frequency"] == "as and when necessary"


def test_the_note_warns_about_ranking_and_the_grid(monkeypatch):
    monkeypatch.setattr(geocode, "fetch_json", fake([ROW]))
    note = geocode.place_search("南生圍")["note"]
    assert "按相關度排序" in note
    assert "方格網" in note


def test_a_row_without_coordinates_is_dropped(monkeypatch):
    monkeypatch.setattr(geocode, "fetch_json", fake([{**ROW, "x": ""}, ROW]))
    assert len(geocode.place_search("南生圍")["data"]) == 1


def test_limit_keeps_the_first_rows(monkeypatch):
    other = {**ROW, "nameZH": "南生圍路", "nameEN": "NAM SANG WAI ROAD", "x": 821178, "y": 836055}
    monkeypatch.setattr(geocode, "fetch_json", fake([ROW, other]))
    assert len(geocode.place_search("南生圍", limit=1)["data"]) == 1
    assert len(geocode.place_search("南生圍")["data"]) == 2


def test_an_empty_query_does_not_call_the_endpoint(monkeypatch):
    def boom(*args, **kwargs):
        raise AssertionError("should not fetch")

    monkeypatch.setattr(geocode, "fetch_json", boom)
    result = geocode.place_search("   ")
    assert result["data"] is None
    assert "要給一個地點名" in result["note"]


def test_a_non_list_payload_is_an_error(monkeypatch):
    monkeypatch.setattr(geocode, "fetch_json", fake({"error": "nope"}))
    with pytest.raises(MtrError) as caught:
        geocode.place_search("南生圍")
    assert "locationSearch" in caught.value.endpoint
