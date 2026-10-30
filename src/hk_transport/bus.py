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

from hk_transport import _graph, als, bus_core
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
