"""One journey search across every network this skill has.

The bus, minibus and railway graphs are built into a single graph:

- a **point** node is a place you can stand: a bus stop, a minibus stop, or a
  station (the average of its exit coordinates);
- a **trip** node is one position on one trip: (mode, trip key, stop order);
- edges are ride (one stop), board (a transfer), alight, and walk.

Walking happens in three places: from the origin to any point inside the
radius, between two points within the transfer radius, and from the last
point to the destination. The search prices walking with straight-line
distance, then the chosen walk legs are re-priced with the Lands Department
pedestrian route search, which returns a real path length and time.

Cost is the triple (transfers, stops, walking metres), compared in that
order. One transfer outweighs any number of stops, and one stop outweighs any
walk inside the cap; walking only breaks ties within the same stop count.
That is a policy, not a measurement, and the answer exposes all three parts.
"""

from __future__ import annotations

import heapq
import math
from collections import defaultdict

from hk_transport import _places, bus_core, exits, minibus_core, mtr_core, pedroute
from hk_transport.mtr import _line_names
from hk_transport._result import compose

_WALK = 800
_LINK = 300
_WALK_RETRY = 1500
_WALK_CAP = 1500
_LINK_NEIGHBOURS = 8

# Weights, in one integer so a plain Dijkstra can search them. A transfer is
# worth 100 stops, and a stop is worth 100 metres of walking. Without the
# walking weight the search saves a stop by walking two kilometres, which is
# what the first version did. These are policy numbers, not measurements.
_TRANSFER = 1_000_000
_STOP = 1_000
_WALK_WEIGHT = 10

NOTE = (
    "方案按（轉車、停站、步行）加權排序：一次轉車當 100 個站，一個站當 100 米步行。唔係時間。"
    "已接入：港鐵、九巴／龍運、城巴、新大嶼山、港鐵巴士、綠色專線小巴，以及少量離島同跨境路線。"
    "未接入：電車、渡輪、的士、高鐵。"
    "步行距離同時間由地政總署行人路網計算，路網冇覆蓋時會改用直線距離並標明。"
    "起點同終點係按地名解析出嚟的一個點，唔代表整個區域。"
)

_memory: dict | None = None


def clear_cache() -> None:
    """Forget the built graph held in this process."""
    global _memory
    _memory = None


def _station_points() -> dict[str, dict]:
    """One point per station, averaged from the exit snapshot."""
    buckets: dict[str, list[tuple[float, float]]] = defaultdict(list)
    names: dict[str, str] = {}
    for row in exits._load()["exits"]:
        latitude, longitude = row.get("latitude"), row.get("longitude")
        if latitude is None or longitude is None:
            continue
        for station_id in row.get("station_ids") or []:
            buckets[station_id].append((latitude, longitude))
            names.setdefault(station_id, row.get("station_zh"))
    points = {}
    for station_id, items in buckets.items():
        points[station_id] = {
            "name_zh": names.get(station_id),
            "latitude": sum(item[0] for item in items) / len(items),
            "longitude": sum(item[1] for item in items) / len(items),
        }
    return points


def _trip_rows() -> list[dict]:
    """One row per stop per trip, for every network in the graph."""
    rows: list[dict] = []
    for row in bus_core.td_bus_route_stops()["data"]:
        rows.append(
            {
                "mode": "bus",
                "key": (
                    row["company"],
                    row["route_id"],
                    row["route_seq"],
                    row["service_mode"],
                    row["special_type"],
                ),
                "seq": row["seq"] or 0,
                "point": f"bus:{row['stop']}",
                "route": row["route"],
                "operator": row["company"],
            }
        )
    for row in minibus_core.gmb_route_stops()["data"]:
        rows.append(
            {
                "mode": "minibus",
                "key": (
                    row["route_id"],
                    row["route_seq"],
                    row["service_mode"],
                    row["special_type"],
                ),
                "seq": row["seq"] or 0,
                "point": f"minibus:{row['stop']}",
                "route": row["route"],
                "operator": "GMB",
            }
        )
    for row in mtr_core.lines_and_stations()["data"]:
        zh, _ = _line_names(row["line_code"])
        rows.append(
            {
                "mode": "mtr",
                "key": (row["line_code"], row["direction"]),
                "seq": row["sequence"] or 0,
                "point": f"mtr:{row['id']}",
                "route": zh or row["line_code"],
                "operator": "MTR",
            }
        )
    return rows


def _point_table(rows: list[dict]) -> dict[str, dict]:
    """Every place you can stand at, with the name that network publishes."""
    points: dict[str, dict] = {}
    seen: dict[str, dict] = {}
    for row in bus_core.td_bus_route_stops()["data"]:
        if row.get("latitude") is None or row.get("longitude") is None:
            continue
        seen.setdefault(row["stop"], row)
    for stop_id, row in seen.items():
        points[f"bus:{stop_id}"] = {
            "point": f"bus:{stop_id}",
            "mode": "bus",
            "stop": f"bus:{stop_id}",
            "name_zh": row["name_zh"],
            "name_en": row["name_en"],
            "latitude": row["latitude"],
            "longitude": row["longitude"],
        }
    for row in minibus_core.gmb_stops()["data"]:
        if row.get("latitude") is None or row.get("longitude") is None:
            continue
        points[f"minibus:{row['stop']}"] = {
            "point": f"minibus:{row['stop']}",
            "mode": "minibus",
            "stop": f"minibus:{row['stop']}",
            "name_zh": row["name_zh"],
            "name_en": row["name_en"],
            "latitude": row["latitude"],
            "longitude": row["longitude"],
        }
    for station_id, row in _station_points().items():
        points[f"mtr:{station_id}"] = {
            "point": f"mtr:{station_id}",
            "mode": "mtr",
            "stop": f"mtr:{station_id}",
            "name_zh": row["name_zh"],
            "name_en": None,
            "latitude": row["latitude"],
            "longitude": row["longitude"],
        }
    return points


def _graph() -> dict:
    """Build the whole network once per process."""
    global _memory
    if _memory is not None:
        return _memory

    trips = _trip_rows()
    points = _point_table(trips)
    by_trip: dict[tuple[str, tuple], list[tuple[float, str]]] = defaultdict(list)
    labels: dict[tuple[str, tuple], dict] = {}
    for row in trips:
        if row["point"] not in points:
            continue
        by_trip[(row["mode"], row["key"])].append((row["seq"], row["point"]))
        labels.setdefault((row["mode"], row["key"]), {"route": row["route"], "operator": row["operator"]})

    point_index = {key: index for index, key in enumerate(points)}
    nodes: list[tuple] = [("point", key) for key in points]
    adjacency: list[list[tuple[int, int, str, tuple]]] = [[] for _ in nodes]

    # Board and alight at every point a trip calls at.
    for (mode, key), stops in by_trip.items():
        stops.sort()
        if len(stops) < 2:
            continue
        indices = []
        previous = None
        for position, (_, point) in enumerate(stops):
            node = len(nodes)
            nodes.append(("trip", (mode, key, position)))
            adjacency.append([])
            point_node = point_index[point]
            adjacency[point_node].append((node, _TRANSFER, "board", (mode, key)))
            adjacency[node].append((point_node, 0, "alight", (mode, key)))
            if previous is not None:
                adjacency[previous].append((node, _STOP, "ride", (mode, key)))
            previous = node
            indices.append(node)

    # Walk links between different points inside the transfer radius.
    cells: dict[tuple[int, int], list[str]] = defaultdict(list)
    for key, row in points.items():
        cells[(int(row["latitude"] / 0.005), int(row["longitude"] / 0.005))].append(key)
    for key, row in points.items():
        near: list[tuple[float, str]] = []
        cell_y, cell_x = int(row["latitude"] / 0.005), int(row["longitude"] / 0.005)
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                for other in cells.get((cell_y + dy, cell_x + dx), ()):
                    if other == key:
                        continue
                    gap = _places.distance(
                        row["latitude"],
                        row["longitude"],
                        points[other]["latitude"],
                        points[other]["longitude"],
                    )
                    if gap <= _LINK:
                        near.append((gap, other))
        near.sort()
        for gap, other in near[:_LINK_NEIGHBOURS]:
            adjacency[point_index[key]].append(
                (point_index[other], round(gap) * _WALK_WEIGHT, "walk", ())
            )

    _memory = {
        "points": points,
        "labels": labels,
        "point_index": point_index,
        "nodes": nodes,
        "adjacency": adjacency,
        "cells": cells,
    }
    return _memory


def _nearby(points: dict[str, dict], cell_index: dict, latitude: float, longitude: float, radius: float):
    cell_y, cell_x = int(latitude / 0.005), int(longitude / 0.005)
    found = []
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            for key in cell_index.get((cell_y + dy, cell_x + dx), ()):
                row = points[key]
                gap = _places.distance(latitude, longitude, row["latitude"], row["longitude"])
                if gap <= radius:
                    found.append((gap, key))
    found.sort()
    return found


def _dijkstra(adjacency, start: int, end: int, penalty: set | None = None):
    """Shortest path that must ride at least once and may not chain walks.

    Chaining walk edges would let the search "walk" through five stops in a
    row, adding distances nobody walks. Requiring a ride keeps a pure walk
    from winning on cost, because a walk-only path pays no boarding at all.
    """
    best = {(start, False, False): 0}
    previous: dict[tuple[int, bool, bool], tuple[tuple[int, bool, bool], str, tuple]] = {}
    queue = [(0, start, False, False)]
    goal = None
    while queue:
        cost, node, walked, ridden = heapq.heappop(queue)
        state = (node, walked, ridden)
        if cost > best.get(state, math.inf):
            continue
        if node == end:
            goal = state
            break
        for target, weight, kind, meta in adjacency[node]:
            stepping = kind in {"walk", "start"}
            if stepping and walked:
                continue
            if kind == "end" and not ridden:
                continue
            step = weight
            if penalty and kind == "board" and meta in penalty:
                step = weight * 4
            candidate = cost + step
            nxt = (target, stepping, ridden or kind == "ride")
            if candidate < best.get(nxt, math.inf):
                best[nxt] = candidate
                previous[nxt] = (state, kind, meta)
                heapq.heappush(queue, (candidate, target, nxt[1], nxt[2]))
    if goal is None:
        return None
    path = []
    state = goal
    while state[0] != start:
        before, kind, meta = previous[state]
        path.append((before[0], state[0], kind, meta))
        state = before
    path.reverse()
    return path


def _legs(path, graph, origin_point, destination_point) -> list[dict]:
    """Turn an edge path into walk and ride legs."""
    points = graph["points"]
    count = len(graph["nodes"])
    legs: list[dict] = []
    ride = None

    def point_of(node: int) -> dict:
        if node >= count:
            return origin_point if node == count else destination_point
        key = graph["nodes"][node][1]
        return points[key]

    for source, target, kind, meta in path:
        if kind in {"start", "walk", "end"}:
            from_point = point_of(source)
            to_point = point_of(target)
            gap = round(
                _places.distance(
                    from_point["latitude"],
                    from_point["longitude"],
                    to_point["latitude"],
                    to_point["longitude"],
                )
            )
            if gap == 0:
                continue
            legs.append(
                {
                    "type": "walk",
                    "metres": gap,
                    "from": {"name_zh": from_point["name_zh"], "latitude": from_point["latitude"], "longitude": from_point["longitude"]},
                    "to": {"name_zh": to_point["name_zh"], "latitude": to_point["latitude"], "longitude": to_point["longitude"]},
                }
            )
            continue
        if kind == "board":
            mode, key = meta[0], meta[1]
            label = graph["labels"].get((mode, key)) or {}
            ride = {
                "type": "ride",
                "mode": mode,
                "trip": (mode, key),
                "route": label.get("route"),
                "operator": label.get("operator"),
                "board": points[graph["nodes"][source][1]]["name_zh"],
                "alight": None,
                "stops": 0,
                "board_point": graph["nodes"][source][1],
            }
            legs.append(ride)
            continue
        if kind == "ride" and ride is not None:
            ride["stops"] += 1
            continue
        if kind == "alight" and ride is not None:
            ride["alight"] = points[graph["nodes"][target][1]]["name_zh"]
            ride["alight_point"] = graph["nodes"][target][1]
            ride = None
    return legs


def _start_edges(graph, latitude: float, longitude: float, radius: float):
    return [
        (gap, key) for gap, key in _nearby(graph["points"], graph["cells"], latitude, longitude, radius)
    ]


def _price_walks(legs: list[dict], counter: list[int]) -> None:
    """Replace straight-line walk metres with the pedestrian network, in place."""
    for leg in legs:
        if leg["type"] != "walk":
            continue
        if leg["metres"] == 0:
            leg["minutes"] = 0.0
            continue
        if counter[0] <= 0:
            leg["estimated"] = True
            continue
        counter[0] -= 1
        try:
            result = pedroute.walk_route(
                leg["from"]["latitude"],
                leg["from"]["longitude"],
                leg["to"]["latitude"],
                leg["to"]["longitude"],
            )
        except Exception:  # a failed walk must not lose the journey
            leg["estimated"] = True
            continue
        data = result["data"] or {}
        if data.get("found"):
            leg["straight_line_metres"] = leg["metres"]
            leg["metres"] = round(data["metres"])
            leg["minutes"] = round(data["minutes"], 1)
        else:
            leg["estimated"] = True


def journey(
    origin: str,
    destination: str,
    options: int = 3,
    walk: int = _WALK,
) -> dict:
    """由一個地方去另一個地方，用晒所有已接入的交通網絡。

    資料集：港鐵 `mtr_core.lines_and_stations`、專營巴士
    `bus_core.td_bus_route_stops`（含城巴、新大嶼山、港鐵巴士）、
    綠色專線小巴 `minibus_core.gmb_route_stops`、地政總署行人路網
    `pedroute.walk_route`。
    用法：`journey("元州邨", "香港迪士尼樂園")`。
    市民會問：由我呢度去 X，搭咩車？要唔要轉車？行幾遠？

    交還多個方案，每個帶步行段同乘車段。成本係（轉車、停站、步行米），
    唔係時間；乘車時間冇數據，只有步行時間來自行人路網。
    電車、渡輪、的士同高鐵未接入，跨出這個範圍的組合接唔上。
    """
    options = options or 3
    walk = walk or _WALK
    graph = _graph()
    points = graph["points"]
    start_point, note = _places.place(origin, points)
    if start_point is None:
        return compose([], None, note=note)
    end_point, note = _places.place(destination, points)
    if end_point is None:
        return compose([], None, note=note)

    starts = _start_edges(graph, start_point["latitude"], start_point["longitude"], walk)
    ends = _start_edges(graph, end_point["latitude"], end_point["longitude"], walk)
    widened = ""
    if not starts or not ends:
        wide = max(walk, _WALK_RETRY)
        starts = starts or _start_edges(
            graph, start_point["latitude"], start_point["longitude"], wide
        )
        ends = ends or _start_edges(
            graph, end_point["latitude"], end_point["longitude"], wide
        )
        widened = f"最近站超過 {walk} 米，已自動放寬到 {wide} 米。"
    if not starts:
        return compose([], None, note=f"起點 {_WALK_RETRY} 米內沒有已接入的站。")
    if not ends:
        return compose([], None, note=f"終點 {_WALK_RETRY} 米內沒有已接入的站。")

    start_index = len(graph["nodes"])
    end_index = start_index + 1
    adjacency = [list(edges) for edges in graph["adjacency"]]
    adjacency.extend([[], []])
    for gap, key in starts:
        adjacency[start_index].append(
            (graph["point_index"][key], round(gap) * _WALK_WEIGHT, "start", (key,))
        )
    for gap, key in ends:
        adjacency[graph["point_index"][key]].append(
            (end_index, round(gap) * _WALK_WEIGHT, "end", (key,))
        )

    chosen: list[dict] = []
    seen: set[tuple] = set()
    penalty: set = set()
    for _ in range(options * 2):
        path = _dijkstra(adjacency, start_index, end_index, penalty)
        if path is None:
            break
        legs = _legs(path, graph, start_point, end_point)
        rides = [leg for leg in legs if leg["type"] == "ride"]
        if not rides:
            break
        signature = tuple(
            (leg["mode"], leg.get("route"), leg["board_point"], leg["alight_point"])
            for leg in rides
        )
        for leg in rides:
            penalty.add(leg["trip"])
        if signature in seen:
            continue
        seen.add(signature)
        total_walk = sum(leg["metres"] for leg in legs if leg["type"] == "walk")
        chosen.append(
            {
                "transfers": max(len(rides) - 1, 0),
                "stops": sum(leg["stops"] for leg in rides),
                "walk_metres": total_walk,
                "legs": legs,
            }
        )
        if len(chosen) >= options:
            break

    if not chosen:
        return compose([], None, note=NOTE + "這兩個地方在已接入的網絡上接不上。")

    counter = [12]
    for option in chosen:
        _price_walks(option["legs"], counter)
        option["walk_metres"] = sum(
            leg["metres"] for leg in option["legs"] if leg["type"] == "walk"
        )

    kept = [option for option in chosen if option["walk_metres"] <= _WALK_CAP]
    if not kept:
        kept = chosen[:1]
        extra = f"每個方案的總步行都超過 {_WALK_CAP} 米，這裡只列最短的一個。"
    else:
        extra = ""
    kept.sort(
        key=lambda option: (
            option["transfers"] * _TRANSFER
            + option["stops"] * _STOP
            + option["walk_metres"] * _WALK_WEIGHT
        )
    )
    return compose(
        [],
        {
            "origin": start_point,
            "destination": end_point,
            "options": kept[:options],
        },
        note=NOTE + widened + extra,
    )
