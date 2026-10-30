"""Citizen-facing bus tools.

Each function answers one citizen question by composing `bus_core` and the
shared `_graph` search. No URL and no cache live here.

Three rules come from testing the raw graph:

1. Every stop inside the walking radius is a candidate. Taking the nearest few
   hides direct routes that board one stop further along the same street.
2. Options are de-duplicated by route sequence, not by node path. Otherwise
   "three options" means the same bus boarded one stop apart.
3. There is no service-hours data, so an option that uses an N-prefixed route
   is returned with a hint rather than silently dropped or silently offered.
"""

from __future__ import annotations

import math
import re
from collections import defaultdict

from hk_transport import _graph, als, bus_core, notices
from hk_transport._result import compose

_WALK = 400
_OVERNIGHT = re.compile(r"^N\d")

JOURNEY_NOTE = (
    "只有九巴／龍運，跨營辦商轉車未接上。"
    "成本是轉車次數同停站數，不是時間。步行距離是直線距離。"
)


def _distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius = 6371000
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    delta_phi = phi2 - phi1
    delta_lambda = math.radians(lon2 - lon1)
    a = (
        math.sin(delta_phi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2) ** 2
    )
    return 2 * radius * math.asin(math.sqrt(a))


def _view(row: dict) -> dict:
    return {"stop": row["stop"], "name_zh": row["name_zh"], "name_en": row["name_en"]}


def _stops_within(
    stops: dict[str, dict], latitude: float, longitude: float, radius: float
) -> dict[str, float]:
    """Every stop inside the radius, with its straight-line distance."""
    found: dict[str, float] = {}
    for stop_id, row in stops.items():
        if row["latitude"] is None or row["longitude"] is None:
            continue
        distance = _distance(latitude, longitude, row["latitude"], row["longitude"])
        if distance <= radius:
            found[stop_id] = distance
    return found


def _place(query: str, stops: dict[str, dict]) -> tuple[dict | None, str | None]:
    """Resolve a stop name, a stop id, or a place name to one point."""
    text = query.strip()
    exact = [
        row
        for row in stops.values()
        if row["stop"] == text or row["name_zh"] == text or row["name_en"] == text
    ]
    if exact and exact[0]["latitude"] is not None:
        row = exact[0]
        return (
            {
                "query": text,
                "resolved_as": "stop",
                "name_zh": row["name_zh"],
                "name_en": row["name_en"],
                "latitude": row["latitude"],
                "longitude": row["longitude"],
            },
            None,
        )
    found = als.address_lookup(text, n=5)
    matches = [
        item for item in (found["data"] or []) if item.get("latitude") and item.get("longitude")
    ]
    if not matches:
        return None, f"找不到地方：{text}"
    matches.sort(key=lambda item: item.get("score") or 0, reverse=True)
    best = matches[0]
    return (
        {
            "query": text,
            "resolved_as": "place",
            "name_zh": best.get("building_zh") or best.get("street_zh"),
            "name_en": best.get("building_en") or best.get("street_en"),
            "latitude": float(best["latitude"]),
            "longitude": float(best["longitude"]),
            "score": best.get("score"),
        },
        None,
    )


def _graph_of(rows: list[dict]) -> tuple[list[tuple], list[tuple[int, int, str]]]:
    """Platform nodes and edges from route-stop rows.

    A node is a position on one trip: (route, direction, service_type, stop).
    Ride edges join consecutive stops on a trip; transfer edges join two trips
    at the same stop.
    """
    variants: dict[tuple[str, str, str], list[tuple[float, str]]] = defaultdict(list)
    for row in rows:
        variants[(row["route"], row["direction"], row["service_type"])].append(
            (row["seq"] or 0, row["stop"])
        )
    nodes: list[tuple] = []
    node_of: dict[tuple, int] = {}
    for key, stops in variants.items():
        stops.sort()
        for index, (_, stop) in enumerate(stops):
            node_of[(key, index)] = len(nodes)
            nodes.append((key, stop))
    edges: list[tuple[int, int, str]] = []
    for key, stops in variants.items():
        for index in range(len(stops) - 1):
            edges.append((node_of[(key, index)], node_of[(key, index + 1)], _graph.RIDE))
    by_stop: dict[str, list[tuple[tuple, int]]] = defaultdict(list)
    for node, (key, stop) in enumerate(nodes):
        by_stop[stop].append((key, node))
    for items in by_stop.values():
        for first_key, first_node in items:
            for second_key, second_node in items:
                if first_key != second_key:
                    edges.append((first_node, second_node, _graph.TRANSFER))
    return nodes, edges


def _legs(route, nodes: list[tuple]) -> list[dict]:
    legs = []
    index = 0
    while index < len(route.nodes) - 1:
        if route.kinds[index] == _graph.TRANSFER:
            index += 1
            continue
        end = index
        while end + 1 < len(route.nodes) and route.kinds[end] == _graph.RIDE:
            end += 1
        key = nodes[route.nodes[index]][0]
        legs.append(
            {
                "route": key[0],
                "direction": key[1],
                "service_type": key[2],
                "board": nodes[route.nodes[index]][1],
                "alight": nodes[route.nodes[end]][1],
                "stops": end - index,
            }
        )
        index = end
    return legs


def bus_journey(
    origin: str,
    destination: str,
    options: int = 3,
    walk: int = _WALK,
) -> dict:
    """由一個地方去另一個地方，搭邊幾條巴士線。

    資料集 `hk-td-tis_21-etakmb`（九巴／龍運），站序來自
    `kmb_route_stops_all` 的快照，站名同座標來自 `kmb_stops`。
    地點由 `address_lookup` 解析。

    用法：`bus_journey("元州邨", "房屋委員會總部")`。
    市民會問：由我呢度去 X，搭咩巴士？要唔要轉車？

    交還多個方案，每個帶上落站、站數、轉車次數同兩端直線步行距離。
    方案唔排名，唔寫「最快」。成本係（轉車次數、停站數），唔係時間。
    只有九巴同龍運；跨營辦商轉車接唔上。冇服務時間數據，所以 N 字頭路線
    會標一個提示，唔會過濾。
    """
    options = options or 3
    walk = walk or _WALK
    stops = {row["stop"]: row for row in bus_core.kmb_stops()["data"]}
    sources = [bus_core.kmb_stops()]
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
    if not origin_stops or not destination_stops:
        return compose(
            sources,
            None,
            note=f"{walk} 米內找不到巴士站，試試另一個地點或者放寬步行距離。",
        )

    route_rows = bus_core.kmb_route_stops_all()
    sources.append(route_rows)
    nodes, edges = _graph_of(route_rows["data"])
    starts = [index for index, (_, stop) in enumerate(nodes) if stop in origin_stops]
    goals = {index for index, (_, stop) in enumerate(nodes) if stop in destination_stops}

    found = _graph.journeys(len(nodes), edges, starts, goals, k=options * 6)
    chosen: list[dict] = []
    seen: set[tuple[tuple[str, str], ...]] = set()
    for route in found:
        legs = _legs(route, nodes)
        if not legs:
            continue
        signature = tuple((leg["route"], leg["direction"]) for leg in legs)
        if signature in seen:
            continue
        seen.add(signature)
        board, alight = legs[0]["board"], legs[-1]["alight"]
        chosen.append(
            {
                "transfers": route.transfers,
                "stops": route.rides,
                "legs": [
                    {
                        **leg,
                        "board_name": stops[leg["board"]]["name_zh"],
                        "alight_name": stops[leg["alight"]]["name_zh"],
                    }
                    for leg in legs
                ],
                "walk_in": round(origin_stops[board]),
                "walk_out": round(destination_stops[alight]),
                "overnight_hint": any(_OVERNIGHT.match(leg["route"]) for leg in legs),
            }
        )
        if len(chosen) >= options:
            break

    if not chosen:
        return compose(
            sources,
            None,
            note="這兩處之間在九巴／龍運路線圖上接不上。跨營辦商轉車未支援。",
        )
    note = JOURNEY_NOTE
    if any(option["overnight_hint"] for option in chosen):
        note += "N 字頭路線通常是通宵線；這裡沒有服務時間數據。"
    return compose(
        sources,
        {
            "origin": origin_point,
            "destination": destination_point,
            "options": chosen,
        },
        note=note,
    )


FARE_NOTE = (
    "車費是成人全程價，逐程上車計，未計轉乘優惠。"
    "journey_time_minutes 是整條路線的公布全程時間，不是分段行車時間。"
)


def bus_fare(route: str, company: str | None = None) -> dict:
    """一條專營巴士路線的成人車費同公布全程時間。

    資料集 `hk-td-tis_23-routes-fares-geojson`，端點
    `https://static.data.gov.hk/td/routes-fares-geojson/JSON_BUS.json`。

    用法：`bus_fare("B1")`，`bus_fare("B1", company="KMB")`。
    市民會問：搭呢條線幾多錢？全程要幾耐？

    交還這條線每一個變體（方向、服務類型）的成人車費同全程時間。
    車費唔係分段收費；全程時間唔係你坐嗰一段的時間。同一條線有幾種行法時，
    會逐個列出，唔會替你揀。
    """
    fares = bus_core.td_bus_fares()
    text = route.strip().upper()
    wanted = company.strip().upper() if company else None
    matches = [
        row
        for row in fares["data"]
        if (row["route"] or "").upper() == text
        and (wanted is None or (row["company"] or "").upper() == wanted)
    ]
    if not matches:
        return compose([fares], None, note=f"車費表沒有這條路線：{route}")
    return compose([fares], {"route": text, "variants": matches}, note=FARE_NOTE)


DISRUPTION_NOTE = (
    "這是在運輸署兩份通告裡做關鍵字比對，不是營辦商的路線警報。"
    "純數字路線（例如 6、45）容易誤中，結果要人手核對。"
)


def _mentions(text: str, token: str) -> bool:
    """True when the route token appears as a whole token, not inside a number."""
    pattern = rf"(?<![0-9A-Za-z]){re.escape(token)}(?![0-9A-Za-z])"
    return re.search(pattern, text, flags=re.IGNORECASE) is not None


def bus_disruption(route: str, limit: int = 5) -> dict:
    """今日有冇通告影響這條巴士線。

    資料集 `hk-td-tis_19-special-traffic-news-v2` 同
    `hk-td-tis_22-traffic-notices`，由 `notices` 的兩個核心函式讀取。

    用法：`bus_disruption("K66")`。
    市民會問：今日呢條線有冇改道、暫停或者塞車？

    交還通告標題、生效日期同節錄，最多 `limit` 條。
    這是關鍵字比對，不是營辦商發出的路線警報；通告未必逐條列出受影響路線，
    所以「冇搵到」不等於「冇事」。純數字路線容易誤中。
    """
    limit = limit or 5
    token = route.strip().upper()
    if not re.fullmatch(r"[A-Z]{0,2}\d{1,3}[A-Z]?", token):
        return compose([], None, note=f"唔似巴士路線號碼：{route}")
    news = notices.special_traffic_news()
    plans = notices.special_traffic_arrangements()
    matches = []
    for source, rows in (("news", news["data"] or []), ("arrangement", plans["data"] or [])):
        for row in rows:
            text = " ".join(
                filter(
                    None,
                    [
                        row.get("heading_zh"),
                        row.get("detail_zh"),
                        row.get("location_zh"),
                        row.get("title_zh"),
                        row.get("content_zh"),
                    ],
                )
            )
            if not _mentions(text, token):
                continue
            matches.append(
                {
                    "source": source,
                    "id": row.get("id"),
                    "title": row.get("heading_zh") or row.get("title_zh"),
                    "effective": row.get("start_date") or row.get("announcement_at"),
                    "excerpt": (row.get("detail_zh") or row.get("content_zh") or "")[:200],
                }
            )
            if len(matches) >= limit:
                break
        if len(matches) >= limit:
            break
    if not matches:
        return compose(
            [news, plans],
            {"route": token, "matches": []},
            note=DISRUPTION_NOTE + "這次兩份通告都沒有提到這條線。",
        )
    return compose([news, plans], {"route": token, "matches": matches}, note=DISRUPTION_NOTE)


NO_DATA = {
    "service_hours": "這個技能沒有巴士服務時間數據，答不到尾班車或服務時間。",
    "frequency": "這個技能沒有班次表，答不到幾分鐘一班，也沒有循環線或特快標記。",
    "accessibility": "這個技能沒有低地台或無障礙巴士數據，答不到輪椅上不上到。",
}


def bus_service_hours(route: str) -> dict:
    """服務時間同尾班車：這個技能沒有數據。

    九巴、城巴、新大嶼山的公開數據只有路線、站、車費同實時到站，
    沒有首尾班車或服務時間。交還 `data: null` 同說明。
    """
    return compose([], None, note=NO_DATA["service_hours"])


def bus_frequency(route: str) -> dict:
    """班次密度、循環線、特快：這個技能沒有數據。

    路線數據沒有班次表，也沒有循環線或特快標記。交還 `data: null` 同說明。
    """
    return compose([], None, note=NO_DATA["frequency"])


def bus_accessibility(route: str) -> dict:
    """低地台同無障礙：這個技能沒有數據。

    公開數據沒有逐條線的低地台或無障礙資訊。交還 `data: null` 同說明。
    """
    return compose([], None, note=NO_DATA["accessibility"])


def bus_stops_near(place: str, limit: int = 8, walk: int = _WALK) -> dict:
    """一個地方附近的巴士站，同直線距離。

    地點由 `address_lookup` 解析，站同座標來自 `kmb_stops`。
    用法：`bus_stops_near("元州邨")`。
    市民會問：我附近有邊幾個巴士站？最近嗰個喺邊？

    只包含九巴／龍運的站。距離是直線距離，不是步行距離。
    """
    limit = limit or 8
    stops = {row["stop"]: row for row in bus_core.kmb_stops()["data"]}
    sources = [bus_core.kmb_stops()]
    point, note = _place(place, stops)
    if point is None:
        return compose(sources, None, note=note)
    found = _stops_within(stops, point["latitude"], point["longitude"], walk)
    ordered = sorted(found.items(), key=lambda item: item[1])[:limit]
    return compose(
        sources,
        {
            "place": point,
            "radius": walk,
            "stops": [
                {**_view(stops[stop_id]), "distance": round(distance)}
                for stop_id, distance in ordered
            ],
        },
        note="只有九巴／龍運的站。距離是直線距離，不是步行距離。",
    )


def bus_route(route: str, place: str | None = None) -> dict:
    """一條巴士線的停站順序，或問它經不經一個地方。

    資料集 `hk-td-tis_21-etakmb`，端點由 `kmb_routes`、`kmb_route_stops`、
    `kmb_stops` 帶出。
    用法：`bus_route("45")`，`bus_route("45", place="何文田廣場")`。
    市民會問：呢條線經唔經 Y？停邊啲站，順序係點？

    逐個方向同服務類型列出，最多四個變體。只涵蓋九巴／龍運。
    """
    text = route.strip().upper()
    stops = {row["stop"]: row for row in bus_core.kmb_stops()["data"]}
    routes = bus_core.kmb_routes()
    sources = [routes, bus_core.kmb_stops()]
    variants = [row for row in routes["data"] if (row["route"] or "").upper() == text]
    if not variants:
        return compose(sources, None, note=f"找不到九巴／龍運路線：{route}")
    wanted = None
    if place is not None:
        wanted, note = _place(place, stops)
        if wanted is None:
            return compose(sources, None, note=note)
        near = _stops_within(stops, wanted["latitude"], wanted["longitude"], _WALK)
    payload = []
    for variant in variants[:4]:
        rows = bus_core.kmb_route_stops(
            variant["route"], variant["bound"], variant["service_type"]
        )
        sources.append(rows)
        ordered = sorted(rows["data"], key=lambda row: row["seq"] or 0)
        sequence = [
            {
                "seq": row["seq"],
                "stop": row["stop"],
                "name_zh": (stops.get(row["stop"]) or {}).get("name_zh"),
            }
            for row in ordered
        ]
        entry = {
            "direction": variant["bound"],
            "service_type": variant["service_type"],
            "origin_zh": variant["orig_zh"],
            "dest_zh": variant["dest_zh"],
            "stops": sequence,
        }
        if wanted is not None:
            entry["serves_place"] = any(row["stop"] in near for row in ordered)
        payload.append(entry)
    note = "只有九巴／龍運。"
    if wanted is not None:
        note += "經唔經係用 400 米內的站判斷，唔係官方路線圖。"
    return compose(sources, {"route": text, "variants": payload}, note=note)


def bus_direct(origin: str, destination: str) -> dict:
    """兩個站之間有冇一程過，同一方向同一程車。

    站序來自 `kmb_route_stops_all` 的快照，站名來自 `kmb_stops`。
    用法：`bus_direct("元州邨", "何文田廣場")`。
    市民會問：由 A 去 B 有冇一程過？冇嘅話喺邊度轉？

    交還每條一程過的路線，同埋上落站在該線的次序。冇就 `data: null`。
    """
    stops = {row["stop"]: row for row in bus_core.kmb_stops()["data"]}
    sources = [bus_core.kmb_stops()]
    start, note = _place(origin, stops)
    if start is None:
        return compose(sources, None, note=note)
    end, note = _place(destination, stops)
    if end is None:
        return compose(sources, None, note=note)
    start_stops = _stops_within(stops, start["latitude"], start["longitude"], _WALK)
    end_stops = _stops_within(stops, end["latitude"], end["longitude"], _WALK)
    if not start_stops or not end_stops:
        return compose(sources, None, note="其中一端 400 米內沒有九巴／龍運站。")
    snapshot = bus_core.kmb_route_stops_all()
    sources.append(snapshot)
    by_variant: dict[tuple[str, str, str], list[tuple[float, str]]] = defaultdict(list)
    for row in snapshot["data"]:
        by_variant[(row["route"], row["direction"], row["service_type"])].append(
            (row["seq"] or 0, row["stop"])
        )
    found = []
    for (route, direction, service), rows in by_variant.items():
        rows.sort()
        order = [stop for _, stop in rows]
        for board_index, board in enumerate(order):
            if board not in start_stops:
                continue
            for alight_index in range(board_index + 1, len(order)):
                alight = order[alight_index]
                if alight in end_stops:
                    found.append(
                        {
                            "route": route,
                            "direction": direction,
                            "service_type": service,
                            "board": _view(stops[board]),
                            "alight": _view(stops[alight]),
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
            note="九巴／龍運沒有一程過的路線；跨營辦商轉車未支援。",
        )
    found.sort(key=lambda option: (option["stops"], option["walk_in"] + option["walk_out"]))
    return compose(
        sources,
        {"origin": start, "destination": end, "direct": found[:5]},
        note="只有九巴／龍運。距離是直線距離，站數是分段數，不是時間。",
    )


def bus_eta(route: str | None = None, stop: str | None = None) -> dict:
    """下一班幾時到。以一條線，或一個站。

    資料集 `hk-td-tis_21-etakmb`，端點由 `kmb_route_eta`、`kmb_stop_eta` 帶出。
    用法：`bus_eta(route="1A")`，`bus_eta(route="1A", stop="元州邨")`。
    市民會問：下一班幾時到？

    只涵蓋九巴／龍運。一個站而冇指定路線時，只查該站頭五條路線，
    因為逐條線查會變成几十個請求。
    """
    stops = {row["stop"]: row for row in bus_core.kmb_stops()["data"]}
    if route is None and stop is None:
        return compose([], None, note="要給一條路線或者一個站。")
    sources = [bus_core.kmb_stops()]
    text = (route or "").strip().upper()
    if stop is not None and text:
        point, note = _place(stop, stops)
        if point is None:
            return compose(sources, None, note=note)
        near = _stops_within(stops, point["latitude"], point["longitude"], _WALK)
        if not near:
            return compose(sources, None, note="這個站 400 米內沒有九巴／龍運站。")
        stop_id = min(near, key=lambda key: near[key])
        live = bus_core.kmb_stop_eta(stop_id, text)
        sources.append(live)
        return compose(
            sources,
            {"route": text, "stop": _view(stops[stop_id]), "eta": live["data"]},
            note="九巴／龍運的實時到站，未計其他營辦商。",
        )
    if text:
        live = bus_core.kmb_route_eta(text)
        sources.append(live)
        return compose(
            sources,
            {"route": text, "eta": live["data"]},
            note="九巴／龍運的實時到站，未計其他營辦商。",
        )
    point, note = _place(stop, stops)
    if point is None:
        return compose(sources, None, note=note)
    near = _stops_within(stops, point["latitude"], point["longitude"], _WALK)
    if not near:
        return compose(sources, None, note="這個站 400 米內沒有九巴／龍運站。")
    stop_id = min(near, key=lambda key: near[key])
    snapshot = bus_core.kmb_route_stops_all()
    sources.append(snapshot)
    routes_here = []
    for row in snapshot["data"]:
        if row["stop"] == stop_id and row["route"] not in routes_here:
            routes_here.append(row["route"])
    eta_rows = []
    for route_name in routes_here[:5]:
        live = bus_core.kmb_stop_eta(stop_id, route_name)
        sources.append(live)
        eta_rows.extend(live["data"])
    return compose(
        sources,
        {"stop": _view(stops[stop_id]), "routes": routes_here[:5], "eta": eta_rows},
        note="九巴／龍運的實時到站。一個站只查頭五條路線。",
    )
