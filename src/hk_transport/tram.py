"""Citizen-facing tram tools.

Two files, two modes: Hong Kong Tramways and the Peak Tram. Neither has
service hours, headway or real-time arrivals in the published data, so those
questions answer "no data" rather than estimating.
"""

from __future__ import annotations

import re

from hk_transport import notices, tram_core
from hk_transport._places import outside as _outside, place as _place, stops_within as _stops_within
from hk_transport._result import compose

_WALK = 400

DISRUPTION_NOTE = (
    "這是在運輸署兩份通告裡做關鍵字比對，不是電車公司的通告。"
    "通告未必逐條列出路線，所以「冇搵到」不等於「冇事」。"
)


def _stops() -> dict[str, dict]:
    rows = tram_core.tram_stops()["data"]
    return {
        row["stop"]: {
            "stop": row["stop"],
            "name_zh": row["name_zh"],
            "name_en": row["name_en"],
            "latitude": row["latitude"],
            "longitude": row["longitude"],
        }
        for row in rows
        if row["latitude"] is not None
    }


def _matches(route: str, row: dict) -> bool:
    text = route.strip().upper()
    if not text:
        return True
    fields = [row.get("route"), row.get("route_en"), row.get("origin_zh"), row.get("dest_zh")]
    return any(text in (field or "").upper() for field in fields)


def tram_route(route: str | None = None, place: str | None = None) -> dict:
    """電車線的停站順序，或問它經不經一個地方。

    資料集 `hk-td-tis_3`，端點由 `tram_core.tram_stops` 帶出。
    用法：`tram_route("跑馬地")`，`tram_route("跑馬地", place="銅鑼灣")`。
    市民會問：呢條電車線去邊？經唔經 Y？

    電車線用中文線名（例如「筲箕灣 - 跑馬地線」），冇號碼。
    東行同西行係兩個變體，逐個列出。
    """
    routes = tram_core.tram_routes()
    found = [row for row in routes["data"] if _matches(route or "", row)]
    if not found:
        return compose([routes], None, note=f"找不到電車線：{route}")
    stops = _stops()
    table = tram_core.tram_stops()
    wanted = None
    if place is not None:
        wanted, note = _place(place, stops)
        if wanted is None:
            return compose([routes, table], None, note=note)
        near = _stops_within(stops, wanted["latitude"], wanted["longitude"], _WALK)
    payload = []
    for variant in found[:4]:
        rows = [
            row
            for row in table["data"]
            if (row["route_id"], row["route_seq"]) == (variant["route_id"], variant["route_seq"])
        ]
        rows.sort(key=lambda row: row["seq"] or 0)
        entry = {
            "route": variant["route"],
            "route_id": variant["route_id"],
            "route_seq": variant["route_seq"],
            "origin_zh": variant["origin_zh"],
            "dest_zh": variant["dest_zh"],
            "fare": variant["fare"],
            "journey_time_minutes": variant["journey_time_minutes"],
            "stops": [
                {"seq": row["seq"], "stop": row["stop"], "name_zh": row["name_zh"]}
                for row in rows
            ],
        }
        if wanted is not None:
            entry["serves_place"] = any(row["stop"] in near for row in rows)
        payload.append(entry)
    note = "只有香港電車。東行同西行分開列。"
    if wanted is not None:
        note += "經唔經係用 400 米內的站判斷，唔係官方路線圖。"
    return compose([routes, table], {"route": route, "variants": payload}, note=note)


def tram_stops_near(place: str, limit: int = 8, walk: int = _WALK) -> dict:
    """一個地方附近的電車站同直線距離。

    資料集 `hk-td-tis_3`。用法：`tram_stops_near("銅鑼灣")`。
    市民會問：附近有邊個電車站？

    東行同西行會分別出現，距離可能差不多。
    """
    limit = limit or 8
    walk = walk or _WALK
    stops = _stops()
    sources = [tram_core.tram_stops()]
    point, note = _place(place, stops)
    if point is None:
        return compose(sources, None, note=note)
    found = _stops_within(stops, point["latitude"], point["longitude"], walk)
    if not found:
        return compose(sources, None, note=_outside(stops, point, walk, "電車站"))
    ordered = sorted(found.items(), key=lambda item: item[1])[:limit]
    return compose(
        sources,
        {
            "place": point,
            "radius": walk,
            "stops": [
                {
                    "stop": stop_id,
                    "name_zh": stops[stop_id]["name_zh"],
                    "distance": round(distance),
                }
                for stop_id, distance in ordered
            ],
        },
        note="距離是直線距離，不是步行距離。東行同西行是兩個站。",
    )


def tram_fare(route: str | None = None) -> dict:
    """電車的成人全程車費。

    資料集 `hk-td-tis_3`。用法：`tram_fare()`、`tram_fare("跑馬地")`。
    市民會問：電車幾多錢？

    香港電車係固定收費，唔係分段；落車再上車要再付。
    """
    routes = tram_core.tram_routes()
    found = [row for row in routes["data"] if _matches(route or "", row)]
    if not found:
        return compose([routes], None, note=f"找不到電車線：{route}")
    return compose(
        [routes],
        {
            "route": route,
            "variants": [
                {
                    "route": row["route"],
                    "origin_zh": row["origin_zh"],
                    "dest_zh": row["dest_zh"],
                    "fare": row["fare"],
                    "remark": row["remark"],
                }
                for row in found
            ],
        },
        note="成人全程價，固定收費，唔係分段；未計任何優惠。",
    )


def peak_tram() -> dict:
    """山頂纜車的路線、站同票價。

    資料集 `hk-td-tis_3`，端點 `JSON_PTRAM.json`。
    用法：`peak_tram()`。
    市民會問：山頂纜車幾多錢？停邊幾個站？

    只有 6 個站、2 個方向。票價係全程價。
    """
    routes = tram_core.peak_tram_routes()
    stops = tram_core.peak_tram_stops()
    return compose(
        [routes, stops],
        {
            "variants": routes["data"],
            "stops": [
                {"seq": row["seq"], "stop": row["stop"], "name_zh": row["name_zh"]}
                for row in sorted(stops["data"], key=lambda row: (row["route_seq"], row["seq"] or 0))
            ],
        },
        note="山頂纜車票價係全程價；班次同到站時間冇數據。",
    )


def tram_disruption(route: str, limit: int = 5) -> dict:
    """今日有冇通告影響這條電車線。

    資料集 `hk-td-tis_19-special-traffic-news-v2` 同
    `hk-td-tis_22-traffic-notices`，由 `notices.route_matches` 讀取。
    用法：`tram_disruption("跑馬地")`。
    市民會問：今日有冇改道、暫停或者停航？

    關鍵字用整詞邊界比對，所以「6」唔會中「16」。通告未必逐條列出受影響路線，
    所以「冇搵到」不等於「冇事」。
    """
    token = route.strip()
    if not token:
        return compose([], None, note="要給一條路線的名字。")
    matches, sources = notices.route_matches(token, limit or 5)
    if not matches:
        return compose(
            sources,
            {"route": token, "matches": []},
            note=DISRUPTION_NOTE + "這次兩份通告都沒有提到這條線。",
        )
    return compose(sources, {"route": token, "matches": matches}, note=DISRUPTION_NOTE)


def tram_service_hours(route: str | None = None) -> dict:
    """電車服務時間：這個技能沒有數據。"""
    return compose([], None, note="這個技能沒有電車服務時間或尾班車數據，答唔到。")


def tram_eta(stop: str | None = None) -> dict:
    """電車下一班：這個技能沒有數據。"""
    return compose([], None, note="這個技能沒有電車實時到站數據，答唔到下一班。")
