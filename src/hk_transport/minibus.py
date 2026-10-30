"""Citizen-facing green minibus tools.

Each function answers one citizen question by composing `minibus_core` and the
shared `_graph` search. No URL and no cache live here.

Three rules, the same ones the buses learned:

1. Every stop inside the walking radius is a candidate, not just the nearest.
2. Options are de-duplicated by route sequence, so three options are three
   different journeys and not one bus boarded one stop apart.
3. A route code is only unique inside a district, so a code that exists in two
   districts is listed for both and never silently narrowed to one.
"""

from __future__ import annotations

import re
from collections import defaultdict

from hk_transport import _graph, minibus_core, notices
from hk_transport._places import (
    outside as _outside,
    place as _place,
    stops_within as _stops_within,
)
from hk_transport._result import compose

_WALK = 400

JOURNEY_NOTE = (
    "只有綠色專線小巴，跨營辦商轉車未接上。"
    "成本是轉車次數同停站數，不是時間。步行距離是直線距離。"
    "起點同終點係按地名解析出嚟的一個點，唔代表整個區域。"
)

DISRUPTION_NOTE = (
    "這是在運輸署兩份通告裡做關鍵字比對，不是營辦商的路線警報。"
    "小巴同巴士的號碼會撞，通告亦未必逐條列出受影響路線，"
    "所以「冇搵到」不等於「冇事」。"
)

NO_DATA = {
    "service_hours": "這個技能沒有小巴服務時間數據，答不到尾班車或服務時間。",
    "frequency": "這個技能沒有小巴班次表，答不到幾分鐘一班。",
    "accessibility": "這個技能沒有低地台或無障礙小巴數據，答不到輪椅上不上到。",
}

_RED_MINIBUS = (
    "紅色小巴沒有固定路線、沒有公開的站點同車費，這個技能答不到。"
    "綠色專線小巴有固定路線，可以用其他命令查。"
)


def _stops() -> dict[str, dict]:
    return {row["stop"]: row for row in minibus_core.gmb_stops()["data"]}


def _variants(route: str, region: str | None = None) -> list[dict]:
    text = route.strip().upper()
    rows = [
        row
        for row in minibus_core.gmb_routes()["data"]
        if (row["route"] or "").upper() == text
    ]
    if region is not None:
        wanted = region.strip().upper()
        rows = [row for row in rows if (row["district"] or "").upper() == wanted]
    return rows


def _route_index(rows: list[dict]) -> dict[tuple, dict]:
    return {
        (
            row["route_id"],
            row["route_seq"],
            row["service_mode"],
            row["special_type"],
        ): row
        for row in rows
    }


def minibus_journey(
    origin: str,
    destination: str,
    options: int = 3,
    walk: int = _WALK,
) -> dict:
    """由一個地方去另一個地方，搭邊幾條小巴線。

    資料集 `hk-td-tis_3`（站序同座標）同 `hk-td-sm_7`（實時到站）。
    用法：`minibus_journey("元州邨", "攸潭尾村")`。
    市民會問：由我呢度去 X，搭咩小巴？要唔要轉車？

    交還多個方案，每個帶上落站、站數、轉車次數同兩端直線步行距離。
    方案唔排名，唔寫「最快」。成本係（轉車次數、停站數），唔係時間。
    只有綠色專線小巴；跨營辦商轉車接唔上。車費唔包含在方案內，
    要用 `minibus_fare` 逐條線查。
    """
    options = options or 3
    walk = walk or _WALK
    stops = _stops()
    sources = [minibus_core.gmb_stops()]
    origin_point, origin_note = _place(origin, stops)
    if origin_point is None:
        return compose(sources, None, note=origin_note)
    destination_point, destination_note = _place(destination, stops)
    if destination_point is None:
        return compose(sources, None, note=destination_note)

    origin_stops = _stops_within(
        stops, origin_point["latitude"], origin_point["longitude"], walk
    )
    destination_stops = _stops_within(
        stops, destination_point["latitude"], destination_point["longitude"], walk
    )
    if not origin_stops:
        return compose(sources, None, note=_outside(stops, origin_point, walk, "小巴站"))
    if not destination_stops:
        return compose(
            sources, None, note=_outside(stops, destination_point, walk, "小巴站")
        )

    table = minibus_core.gmb_route_stops()
    sources.append(table)
    index = _route_index(minibus_core.gmb_routes()["data"])
    nodes, edges = _graph.build(
        table["data"],
        key_fields=("route_id", "route_seq", "service_mode", "special_type"),
    )
    starts = [index for index, (_, stop) in enumerate(nodes) if stop in origin_stops]
    goals = {index for index, (_, stop) in enumerate(nodes) if stop in destination_stops}

    found = _graph.journeys(len(nodes), edges, starts, goals, k=options * 6)
    chosen: list[dict] = []
    seen: set[tuple] = set()
    for route in found:
        legs = _graph.legs(route, nodes)
        if not legs:
            continue
        signature = tuple((leg["key"][0], leg["key"][1]) for leg in legs)
        if signature in seen:
            continue
        seen.add(signature)
        board, alight = legs[0]["board"], legs[-1]["alight"]
        display = []
        for leg in legs:
            key = leg["key"]
            route_row = index.get(key) or {}
            display.append(
                {
                    "route": route_row.get("route"),
                    "district": route_row.get("district"),
                    "route_id": key[0],
                    "route_seq": key[1],
                    "board": leg["board"],
                    "alight": leg["alight"],
                    "stops": leg["stops"],
                    "board_name": stops[leg["board"]]["name_zh"],
                    "alight_name": stops[leg["alight"]]["name_zh"],
                }
            )
        chosen.append(
            {
                "transfers": route.transfers,
                "stops": route.rides,
                "legs": display,
                "walk_in": round(origin_stops[board]),
                "walk_out": round(destination_stops[alight]),
            }
        )
        if len(chosen) >= options:
            break

    if not chosen:
        return compose(
            sources,
            None,
            note="這兩處之間在綠色專線小巴路線圖上接不上。跨營辦商轉車未支援。",
        )
    return compose(
        sources,
        {
            "origin": origin_point,
            "destination": destination_point,
            "options": chosen,
        },
        note=JOURNEY_NOTE,
    )


def minibus_route(route: str, region: str | None = None, place: str | None = None) -> dict:
    """一條小巴線的停站順序，或問它經不經一個地方。

    資料集 `hk-td-tis_3`。用法：`minibus_route("37", region="NT")`，
    `minibus_route("37", region="NT", place="元朗大馬路")`。
    市民會問：呢條線經唔經 Y？停邊啲站，順序係點？

    路線號碼只在區域內唯一，所以唔給 `region` 時，同一個號碼在幾個區域
    都會列出，並在 note 講明。逐個變體列出，最多四個。
    """
    variants = _variants(route, region)
    sources = [minibus_core.gmb_routes()]
    if not variants:
        where = f"（{region}）" if region else ""
        return compose(sources, None, note=f"找不到小巴路線：{route}{where}")
    table = minibus_core.gmb_route_stops()
    sources.append(table)
    stops = _stops()
    wanted = None
    if place is not None:
        wanted, note = _place(place, stops)
        if wanted is None:
            return compose(sources, None, note=note)
        near = _stops_within(
            stops, wanted["latitude"], wanted["longitude"], _WALK
        )
    grouped: dict[tuple, list[dict]] = defaultdict(list)
    for row in table["data"]:
        grouped[
            (row["route_id"], row["route_seq"], row["service_mode"], row["special_type"])
        ].append(row)
    payload = []
    for variant in variants[:4]:
        key = (
            variant["route_id"],
            variant["route_seq"],
            variant["service_mode"],
            variant["special_type"],
        )
        ordered = sorted(grouped.get(key, []), key=lambda row: row["seq"] or 0)
        sequence = [
            {"seq": row["seq"], "stop": row["stop"], "name_zh": row["name_zh"]}
            for row in ordered
        ]
        entry = {
            "district": variant["district"],
            "route_id": variant["route_id"],
            "route_seq": variant["route_seq"],
            "service_mode": variant["service_mode"],
            "special_type": variant["special_type"],
            "origin_zh": variant["origin_zh"],
            "dest_zh": variant["dest_zh"],
            "fare": variant["fare"],
            "journey_time_minutes": variant["journey_time_minutes"],
            "stops": sequence,
        }
        if wanted is not None:
            entry["serves_place"] = any(row["stop"] in near for row in ordered)
        payload.append(entry)
    districts = sorted({variant["district"] for variant in variants})
    note = "只有綠色專線小巴。"
    if len(districts) > 1:
        note += f"這個號碼在 {len(districts)} 個區域都有：{'、'.join(districts)}；冇代你揀。"
    if wanted is not None:
        note += "經唔經係用 400 米內的站判斷，唔係官方路線圖。"
    return compose(
        sources,
        {"route": route.strip().upper(), "variants": payload},
        note=note,
    )


def minibus_stops_near(place: str, limit: int = 8, walk: int = _WALK) -> dict:
    """一個地方附近的小巴站，同直線距離。

    資料集 `hk-td-tis_3`。用法：`minibus_stops_near("攸潭尾村")`。
    市民會問：我附近有邊幾個小巴站？最近嗰個喺邊？

    距離是直線距離，不是步行距離。站名是其中一條線的叫法。
    """
    limit = limit or 8
    walk = walk or _WALK
    stops = _stops()
    sources = [minibus_core.gmb_stops()]
    point, note = _place(place, stops)
    if point is None:
        return compose(sources, None, note=note)
    found = _stops_within(stops, point["latitude"], point["longitude"], walk)
    if not found:
        return compose(sources, None, note=_outside(stops, point, walk, "小巴站"))
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
                    "district": stops[stop_id]["district"],
                    "distance": round(distance),
                }
                for stop_id, distance in ordered
            ],
        },
        note="距離是直線距離，不是步行距離。站名是其中一條線的叫法。",
    )


def minibus_direct(origin: str, destination: str) -> dict:
    """兩個地方之間有冇一程過，同一方向同一程車。

    資料集 `hk-td-tis_3`。用法：`minibus_direct("元州邨", "攸潭尾村")`。
    市民會問：由 A 去 B 有冇一程過？冇嘅話喺邊度轉？

    交還每條一程過的路線，同埋上落站在該線的次序。冇就 `data: null`。
    """
    stops = _stops()
    sources = [minibus_core.gmb_stops()]
    start, note = _place(origin, stops)
    if start is None:
        return compose(sources, None, note=note)
    end, note = _place(destination, stops)
    if end is None:
        return compose(sources, None, note=note)
    start_stops = _stops_within(stops, start["latitude"], start["longitude"], _WALK)
    end_stops = _stops_within(stops, end["latitude"], end["longitude"], _WALK)
    if not start_stops:
        return compose(sources, None, note=_outside(stops, start, _WALK, "小巴站"))
    if not end_stops:
        return compose(sources, None, note=_outside(stops, end, _WALK, "小巴站"))
    table = minibus_core.gmb_route_stops()
    sources.append(table)
    index = _route_index(minibus_core.gmb_routes()["data"])
    by_variant: dict[tuple, list[tuple[float, str]]] = defaultdict(list)
    for row in table["data"]:
        key = (row["route_id"], row["route_seq"], row["service_mode"], row["special_type"])
        by_variant[key].append((row["seq"] or 0, row["stop"]))
    found = []
    for key, rows in by_variant.items():
        rows.sort()
        order = [stop for _, stop in rows]
        for board_index, board in enumerate(order):
            if board not in start_stops:
                continue
            for alight_index in range(board_index + 1, len(order)):
                alight = order[alight_index]
                if alight in end_stops:
                    route_row = index.get(key) or {}
                    found.append(
                        {
                            "route": route_row.get("route"),
                            "district": route_row.get("district"),
                            "route_id": key[0],
                            "route_seq": key[1],
                            "board": {
                                "stop": board,
                                "name_zh": stops[board]["name_zh"],
                            },
                            "alight": {
                                "stop": alight,
                                "name_zh": stops[alight]["name_zh"],
                            },
                            "stops": alight_index - board_index,
                            "walk_in": round(start_stops[board]),
                            "walk_out": round(end_stops[alight]),
                        }
                    )
                    break
    if not found:
        return compose(
            sources,
            None,
            note="綠色專線小巴沒有一程過的路線；跨營辦商轉車未支援。",
        )
    found.sort(key=lambda option: (option["stops"], option["walk_in"] + option["walk_out"]))
    return compose(
        sources,
        {"origin": start, "destination": end, "direct": found[:5]},
        note="只有綠色專線小巴。距離是直線距離，站數是分段數，不是時間。",
    )


def minibus_fare(route: str, region: str | None = None) -> dict:
    """一條小巴線的成人車費同公布全程時間。

    資料集 `hk-td-tis_3`。用法：`minibus_fare("37", region="NT")`。
    市民會問：幾多錢？係咪全程一個價？

    `fare` 是成人全程價，唔係分段收費。路線號碼只在區域內唯一。
    """
    variants = _variants(route, region)
    if not variants:
        where = f"（{region}）" if region else ""
        return compose([], None, note=f"找不到小巴路線：{route}{where}")
    districts = sorted({variant["district"] for variant in variants})
    note = "車費是成人全程價，逐程上車計；唔係分段收費，亦未計任何優惠。"
    if len(districts) > 1:
        note += f"這個號碼在 {len(districts)} 個區域都有，逐個列出。"
    return compose(
        [minibus_core.gmb_routes()],
        {
            "route": route.strip().upper(),
            "variants": [
                {
                    "district": variant["district"],
                    "route_id": variant["route_id"],
                    "route_seq": variant["route_seq"],
                    "service_mode": variant["service_mode"],
                    "special_type": variant["special_type"],
                    "origin_zh": variant["origin_zh"],
                    "dest_zh": variant["dest_zh"],
                    "fare": variant["fare"],
                    "journey_time_minutes": variant["journey_time_minutes"],
                }
                for variant in variants
            ],
        },
        note=note,
    )


def minibus_eta(
    route: str | None = None,
    stop: str | None = None,
    region: str | None = None,
) -> dict:
    """下一班幾時到。一定要給一個站。

    資料集 `hk-td-sm_7`，端點由 `minibus_core.gmb_stop_eta` 帶出。
    用法：`minibus_eta(stop="攸潭尾村")`，`minibus_eta(route="37", stop="攸潭尾村")`。
    市民會問：下一班幾時到？

    小巴 API 只有「一個站」同「一條線一個站序」兩種，冇全線下一班；
    所以只給路線時，答案會講要指定一個站。
    """
    stops = _stops()
    if stop is None:
        if route is None:
            return compose([], None, note="要給一個路線或者一個站。")
        return compose(
            [],
            None,
            note="小巴實時到站要指定一個站；請給 `--stop`，例如「37 喺攸潭尾村」。",
        )
    sources = [minibus_core.gmb_stops()]
    point, note = _place(stop, stops)
    if point is None:
        return compose(sources, None, note=note)
    near = _stops_within(stops, point["latitude"], point["longitude"], _WALK)
    if not near:
        return compose(sources, None, note=_outside(stops, point, _WALK, "小巴站"))
    stop_id = min(near, key=lambda key: near[key])
    live = minibus_core.gmb_stop_eta(stop_id)
    sources.append(live)
    rows = live["data"]
    if route is not None:
        wanted = {
            variant["route_id"]
            for variant in _variants(route, region)
        }
        if not wanted:
            return compose(sources, None, note=f"找不到小巴路線：{route}")
        rows = [row for row in rows if row["route_id"] in wanted]
        note_text = f"只有 {route.strip().upper()} 的下一班。"
    else:
        note_text = "這個站所有路線的下一班。"
    return compose(
        sources,
        {
            "stop": {
                "stop": stop_id,
                "name_zh": stops[stop_id]["name_zh"],
                "district": stops[stop_id]["district"],
            },
            "route": (route or "").strip().upper() or None,
            "eta": rows,
        },
        note=note_text + "`diff` 是分鐘，最多三班。",
    )


def minibus_service_hours(route: str) -> dict:
    """服務時間同尾班車：這個技能沒有數據。"""
    return compose([], None, note=NO_DATA["service_hours"])


def minibus_frequency(route: str) -> dict:
    """班次密度：這個技能沒有數據。

    循環線可以由 `minibus_route` 的 `dest_zh` 看出（官方名稱會寫「循環線」）。
    """
    return compose([], None, note=NO_DATA["frequency"])


def minibus_accessibility(route: str) -> dict:
    """低地台同無障礙：這個技能沒有數據。"""
    return compose([], None, note=NO_DATA["accessibility"])


def _mentions(text: str, token: str) -> bool:
    """True when the route token appears as a whole token, not inside a number."""
    pattern = rf"(?<![0-9A-Za-z]){re.escape(token)}(?![0-9A-Za-z])"
    return re.search(pattern, text, flags=re.IGNORECASE) is not None


def minibus_disruption(route: str, limit: int = 5) -> dict:
    """今日有冇通告影響這條小巴線。

    資料集 `hk-td-tis_19-special-traffic-news-v2` 同
    `hk-td-tis_22-traffic-notices`，由 `notices.route_matches` 讀取。
    用法：`minibus_disruption("37")`。
    市民會問：今日有冇改道、暫停或者停航？

    關鍵字用整詞邊界比對，所以「6」唔會中「16」。通告未必逐條列出受影響路線，
    所以「冇搵到」不等於「冇事」。
    """
    token = route.strip().upper()
    if not re.fullmatch(r"[A-Z]{0,2}\d{1,3}[A-Z]?", token):
        return compose([], None, note=f"唔似小巴路線號碼：{route}")
    matches, sources = notices.route_matches(token, limit or 5)
    if not matches:
        return compose(
            sources,
            {"route": token, "matches": []},
            note=DISRUPTION_NOTE + "這次兩份通告都沒有提到這條線。",
        )
    return compose(sources, {"route": token, "matches": matches}, note=DISRUPTION_NOTE)


def red_minibus(route: str | None = None) -> dict:
    """紅色小巴：沒有固定路線、公開站點或車費。

    紅色小巴唔屬於專線，冇路線編號制度、冇公開站表、冇公開車費，
    所以呢個技能只可以講「冇數據」，唔可以估。
    """
    return compose([], None, note=_RED_MINIBUS)
