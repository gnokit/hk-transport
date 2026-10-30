"""Citizen-facing ferry tools.

The Transport Department lists every ferry route with fares, pier order and
coordinates, but no operator and no timetable. Questions about the next boat
or the last boat answer "no data" rather than estimating.
"""

from __future__ import annotations

from hk_transport import ferry_core, notices
from hk_transport._places import outside as _outside, place as _place, stops_within as _stops_within
from hk_transport._result import compose

_WALK = 400

DISRUPTION_NOTE = (
    "這是在運輸署兩份通告裡做關鍵字比對，不是渡輪公司的通告。"
    "通告未必逐條列出航線，所以「冇搵到」不等於「冇事」。"
)

NO_TIMETABLE = "這個技能沒有渡輪班次表或尾班船數據，答唔到尾班船幾點。"


def _piers() -> dict[str, dict]:
    rows = ferry_core.ferry_stops()["data"]
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


def ferry_route(route: str | None = None, place: str | None = None) -> dict:
    """渡輪航線的碼頭次序，或問它經不經一個地方。

    資料集 `hk-td-tis_3`，端點由 `ferry_core.ferry_stops` 帶出。
    用法：`ferry_route("長洲")`，`ferry_route("長洲", place="中環")`。
    市民會問：中環去長洲搭咩船？呢條航線停邊幾個碼頭？

    航線名係「起點 - 終點」。數據冇營辦商，所以唔會講邊間公司。
    """
    routes = ferry_core.ferry_routes()
    found = [row for row in routes["data"] if _matches(route or "", row)]
    if not found:
        return compose([routes], None, note=f"找不到渡輪航線：{route}")
    piers = _piers()
    table = ferry_core.ferry_stops()
    wanted = None
    if place is not None:
        wanted, note = _place(place, piers)
        if wanted is None:
            return compose([routes, table], None, note=note)
        near = _stops_within(piers, wanted["latitude"], wanted["longitude"], _WALK)
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
            "piers": [
                {"seq": row["seq"], "stop": row["stop"], "name_zh": row["name_zh"]}
                for row in rows
            ],
        }
        if wanted is not None:
            entry["serves_place"] = any(row["stop"] in near for row in rows)
        payload.append(entry)
    note = "只有渡輪。數據冇營辦商，唔會講邊間公司。"
    if wanted is not None:
        note += "經唔經係用 400 米內的碼頭判斷，唔係官方航線圖。"
    return compose([routes, table], {"route": route, "variants": payload}, note=note)


def ferry_piers_near(place: str, limit: int = 8, walk: int = _WALK) -> dict:
    """一個地方附近的渡輪碼頭同直線距離。

    資料集 `hk-td-tis_3`。用法：`ferry_piers_near("中環")`。
    市民會問：附近有邊個碼頭？

    距離是直線距離，不是步行距離。
    """
    limit = limit or 8
    walk = walk or _WALK
    piers = _piers()
    sources = [ferry_core.ferry_stops()]
    point, note = _place(place, piers)
    if point is None:
        return compose(sources, None, note=note)
    found = _stops_within(piers, point["latitude"], point["longitude"], walk)
    if not found:
        return compose(sources, None, note=_outside(piers, point, walk, "渡輪碼頭"))
    ordered = sorted(found.items(), key=lambda item: item[1])[:limit]
    return compose(
        sources,
        {
            "place": point,
            "radius": walk,
            "piers": [
                {
                    "stop": stop_id,
                    "name_zh": piers[stop_id]["name_zh"],
                    "distance": round(distance),
                }
                for stop_id, distance in ordered
            ],
        },
        note="距離是直線距離，不是步行距離。",
    )


def ferry_fare(route: str | None = None) -> dict:
    """渡輪航線的成人票價。

    資料集 `hk-td-tis_3`。用法：`ferry_fare("長洲")`。
    市民會問：渡輪幾多錢？

    成人全程價；唔係分段，亦唔分營辦商。
    """
    routes = ferry_core.ferry_routes()
    found = [row for row in routes["data"] if _matches(route or "", row)]
    if not found:
        return compose([routes], None, note=f"找不到渡輪航線：{route}")
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
                    "journey_time_minutes": row["journey_time_minutes"],
                    "remark": row["remark"],
                }
                for row in found
            ],
        },
        note="成人全程價，唔係分段；數據冇營辦商。",
    )


def ferry_timetable(route: str | None = None) -> dict:
    """渡輪班次同尾班船：這個技能沒有數據。"""
    return compose([], None, note=NO_TIMETABLE)


def ferry_eta(route: str | None = None, pier: str | None = None) -> dict:
    """渡輪下一班：這個技能沒有數據。"""
    return compose([], None, note="這個技能沒有渡輪實時到站數據，答唔到下一班船。")


def ferry_disruption(route: str, limit: int = 5) -> dict:
    """今日有冇通告影響這條渡輪航線。

    資料集 `hk-td-tis_19-special-traffic-news-v2` 同
    `hk-td-tis_22-traffic-notices`，由 `notices.route_matches` 讀取。
    用法：`ferry_disruption("長洲")`。
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


