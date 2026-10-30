import pytest

from hk_transport import pedroute
from hk_transport._result import MtrError


def route_payload(length, minutes):
    def call(url, *, dataset_id, cache=True, timeout=30, headers=None):
        return (
            {
                "routes": {
                    "features": [
                        {"attributes": {"Total_Length": length, "Total_Time": minutes}}
                    ]
                }
            },
            "2026-10-30T12:00:00+08:00",
        )

    return call


def test_a_route_returns_metres_and_minutes(monkeypatch):
    monkeypatch.setattr(pedroute, "fetch_json", route_payload(527.77, 8.79))
    result = pedroute.walk_route(22.3383, 114.15502, 22.3356, 114.1555)
    assert result["data"]["found"] is True
    assert result["data"]["metres"] == pytest.approx(527.77)
    assert result["data"]["minutes"] == pytest.approx(8.79)
    assert result["dataset_id"] == "hk-landsd-mapapi-3d-pedestrian-route-search"


def test_the_query_carries_both_points_and_asks_for_walking(monkeypatch):
    seen = {}

    def call(url, *, dataset_id, cache=True, timeout=30, headers=None):
        seen["url"] = url
        return {"routes": {"features": [{"attributes": {"Total_Length": 1, "Total_Time": 1}}]}}, "t"

    monkeypatch.setattr(pedroute, "fetch_json", call)
    pedroute.walk_route(22.3383, 114.15502, 22.3356, 114.1555)
    assert "travelMode=1" in seen["url"]
    assert "114.15502" in seen["url"]


def test_no_solution_is_reported_not_invented(monkeypatch):
    monkeypatch.setattr(
        pedroute,
        "fetch_json",
        lambda *a, **k: (
            {"error": {"code": 400, "details": ["No route from A to B. No solution found."]}},
            "2026-10-30T12:00:00+08:00",
        ),
    )
    result = pedroute.walk_route(22.46, 114.03, 22.47, 114.05)
    assert result["data"]["found"] is False
    assert result["data"]["metres"] is None
    assert result["data"]["minutes"] is None
    assert "找不到路線" in result["note"]


def test_an_empty_route_list_is_not_a_zero_metre_walk(monkeypatch):
    monkeypatch.setattr(pedroute, "fetch_json", lambda *a, **k: ({"routes": {"features": []}}, "t"))
    result = pedroute.walk_route(22.46, 114.03, 22.47, 114.05)
    assert result["data"]["found"] is False


def test_a_non_object_payload_is_an_error(monkeypatch):
    monkeypatch.setattr(pedroute, "fetch_json", lambda *a, **k: ([], "t"))
    with pytest.raises(MtrError):
        pedroute.walk_route(22.46, 114.03, 22.47, 114.05)
