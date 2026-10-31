"""One journey search across every network this skill has.

The bus, minibus, tram, ferry and railway graphs are built into a single
graph:

- a **point** node is a place you can stand: a bus stop, a minibus stop, a
  tram stop, a ferry pier, or a station (the average of its exit coordinates);
- a **trip** node is one position on one trip: (mode, trip key, stop order);
- edges are ride (one stop), board (a transfer, and the first stop), alight,
  and walk.

Boarding goes straight to the *next* stop on the trip, so a zero-stop ride does
not exist and a journey must move to count.

Walking happens in three places: from the origin to any point inside the
radius, between two points inside the transfer radius, and from the last point
to the destination. The search prices walking with straight-line distance,
then the chosen walk legs are re-priced with the Lands Department pedestrian
route search. A walk that turns out much longer than its straight line bans
that point pair (or the origin/destination stop) and the search runs once more.

Cost is policy minutes (board wait + ride distance/speed + dwell + walk),
encoded as one integer for a plain Dijkstra. The weights are estimates, not
ETAs or measured ride times.
"""

from __future__ import annotations

import heapq
import math
import re
from collections import defaultdict
from dataclasses import dataclass

from hk_transport import (
    _places,
    bus_core,
    exits,
    ferry_core,
    minibus_core,
    mtr_core,
    pedroute,
    tram_core,
)
from hk_transport._result import compose

_WALK = 800
_LINK = 300
_MTR_LINK = 450
_LINK_NEIGHBOURS = 20
_PRIORITY_MODES = ("mtr", "ferry", "tram")
# The Peak Tram is deliberately not in the graph. It is a tourist line whose
# queue is the dominant cost and we have no queue or headway data, so any
# boarding price would be a guess dressed as a fact. `tram.sh peak_tram`
# answers "how much, which stops" on its own. See TASKS.md, 第四階段.
_EXCLUDED_MODES = ("peaktram",)
# Cross-boundary coaches (companyCode XB) exist to cross the border, and the
# only place they share is the border itself. Keeping them lets a domestic trip
# route 觀塘 → 荃灣 by way of 皇崗, which is nonsense. Drop them.
_EXCLUDED_COMPANIES = ("XB",)
_BAD_WALK_RATIO = 2.5
_WALK_RETRY = 1500
_WALK_CAP = 1500
_WALK_CALLS = 12
_END = -1
_OVERNIGHT = re.compile(r"^N\d")

# The routing policy. There is no ride-time data in Hong Kong, so these are
# judgements, not measurements: the answer never prints them, it only ranks.
# They are deliberately in one table so the numbers can be reviewed and tuned
# as experience accumulates. Change a minute here and every answer follows.
COST = {
    # cost units per policy minute; larger = finer resolution, no other effect
    "units_per_minute": 1000,
    # walking, from the policy (not from the pedestrian API, which has its own)
    "walk_minutes_per_km": 15.0,
    # waiting for the next vehicle, which is the only unpredictable part.
    # Estimates (not official ETAs): rail boards cheapest; road modes wait longer.
    "board_minutes": {
        "mtr": 3.0,
        "lightrail": 5.0,
        "tram": 5.0,
        "bus": 8.0,
        "minibus": 8.0,
        "ferry": 20.0,
    },
    # cruise speed while riding, by mode. Hop cost = dwell + distance/speed.
    "speed_kmh": {
        "mtr": 33.0,
        "lightrail": 25.0,
        "tram": 10.0,
        "bus": 15.0,
        "minibus": 15.0,
        "ferry": 20.0,
    },
    # seconds-scale stop at each station/pier, converted to policy minutes.
    "dwell_minutes": {
        "mtr": 0.4,
        "lightrail": 0.3,
        "tram": 0.2,
        "bus": 0.3,
        "minibus": 0.25,
        "ferry": 1.0,
    },
}


def _units() -> dict:
    """Turn the policy table into integer edge weights.

    Read this next to `COST`: boarding is `board_minutes`, one metre of walking
    is `walk_minutes_per_km / 1000`, and a hop between stops is dwell plus
    distance at `speed_kmh`. Rail is priced cheaper per board and faster per km
    than road modes; the numbers are estimates, not ETAs.
    """
    scale = COST["units_per_minute"]
    return {
        "walk": COST["walk_minutes_per_km"] / 1000 * scale,
        "board": {
            mode: round(minutes * scale)
            for mode, minutes in COST["board_minutes"].items()
        },
        "dwell": {
            mode: round(minutes * scale)
            for mode, minutes in COST["dwell_minutes"].items()
        },
        "speed_kmh": dict(COST["speed_kmh"]),
    }


def _ride_cost(units: dict, mode: str, metres: float) -> int:
    """Ride weight for metres on a mode: dwell + travel time from speed.

    Unknown modes fall back to bus.
    """
    speeds = units["speed_kmh"]
    dwells = units["dwell"]
    speed = speeds.get(mode, speeds["bus"])
    dwell = dwells.get(mode, dwells["bus"])
    if speed <= 0:
        speed = speeds["bus"]
    travel = round((metres / 1000) / speed * 60 * COST["units_per_minute"])
    return dwell + travel


def _note_from_cost() -> str:
    """Build NOTE from COST so the prose cannot drift from the table."""
    board = COST["board_minutes"]
    speed = COST["speed_kmh"]
    dwell = COST["dwell_minutes"]
    walk = COST["walk_minutes_per_km"]
    return (
        "排序用政策權重，唔係時間：轉車／上車罰分"
        f"港鐵 {board['mtr']:g}、輕鐵／電車 {board['lightrail']:g}、"
        f"巴士／小巴 {board['bus']:g}、渡輪 {board['ferry']:g} 分鐘；"
        f"車速港鐵 {speed['mtr']:g}、輕鐵 {speed['lightrail']:g}、"
        f"電車 {speed['tram']:g}、巴士／小巴 {speed['bus']:g}、"
        f"渡輪 {speed['ferry']:g} km/h；"
        f"每站停站港鐵 {dwell['mtr']:g}、輕鐵 {dwell['lightrail']:g}、"
        f"電車 {dwell['tram']:g}、巴士 {dwell['bus']:g}、"
        f"小巴 {dwell['minibus']:g}、渡輪 {dwell['ferry']:g} 分鐘；"
        f"步行一公里當 {walk:g} 分鐘。"
        "呢啲係估算假設，唔係量度出嚟的時間。"
        "已接入：港鐵、九巴／龍運、城巴、新大嶼山、港鐵巴士、綠色專線小巴、電車、渡輪，以及少量離島同跨境路線。"
        "未接入：山頂纜車、的士、高鐵。"
        "步行距離同時間由地政總署行人路網計算，路網冇覆蓋時會改用直線距離並標明。"
        "起點同終點係按地名解析出嚟的一個點，唔代表整個區域；地名由地政總署地點搜尋解析。"
    )


NOTE = _note_from_cost()

_memory: dict | None = None
# Process-level pedroute cache keyed by rounded (from, to) coords. Survives
# across journey() calls in the same process; cleared with clear_cache().
_walk_cache: dict[tuple, dict | None] = {}


@dataclass
class _WalkBudget:
    """How many pedestrian-network calls one answer may still make."""

    calls: int = _WALK_CALLS

    def take(self) -> bool:
        if self.calls <= 0:
            return False
        self.calls -= 1
        return True


def clear_cache() -> None:
    """Forget the built graph and the pedroute walk cache held in this process."""
    global _memory, _walk_cache
    _memory = None
    _walk_cache = {}


def _walk_cache_key(
    from_lat: float, from_lon: float, to_lat: float, to_lon: float
) -> tuple:
    """Rounded coord pair; order matters (A→B is not B→A)."""
    return (
        (round(from_lat, 5), round(from_lon, 5)),
        (round(to_lat, 5), round(to_lon, 5)),
    )


def _trip_rows(
    bus: dict,
    gmb_rows: dict,
    tram_rows: dict,
    ferry_rows: dict,
    mtr_rows: dict,
) -> list[dict]:
    """One row per stop per trip, for every network in the graph."""
    rows: list[dict] = []
    for row in bus["data"]:
        if row["company"] in _EXCLUDED_COMPANIES:
            continue
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
                "seq": 0 if row.get("seq") is None else row["seq"],
                "point": f"bus:{row['stop']}",
                "stop": row["stop"],
                "route": row["route"],
                "operator": row["company"],
            }
        )
    for row in gmb_rows["data"]:
        rows.append(
            {
                "mode": "minibus",
                "key": (
                    row["route_id"],
                    row["route_seq"],
                    row["service_mode"],
                    row["special_type"],
                ),
                "seq": 0 if row.get("seq") is None else row["seq"],
                "point": f"minibus:{row['stop']}",
                "stop": row["stop"],
                "route": row["route"],
                "operator": "GMB",
            }
        )
    # Only Hong Kong Tramways here: see _EXCLUDED_MODES.
    for row in tram_rows["data"]:
        rows.append(
            {
                "mode": "tram",
                "key": (
                    row["company"],
                    row["route_id"],
                    row["route_seq"],
                    row["service_mode"],
                    row["special_type"],
                ),
                "seq": 0 if row.get("seq") is None else row["seq"],
                "point": f"tram:{row['stop']}",
                "stop": row["stop"],
                "route": row["route"],
                "operator": row["company"],
            }
        )
    for row in ferry_rows["data"]:
        rows.append(
            {
                "mode": "ferry",
                "key": (
                    row["route_id"],
                    row["route_seq"],
                    row["service_mode"],
                    row["special_type"],
                ),
                "seq": 0 if row.get("seq") is None else row["seq"],
                "point": f"ferry:{row['stop']}",
                "stop": row["stop"],
                "route": row["route"],
                "operator": "FERRY",
            }
        )
    for row in mtr_rows["data"]:
        zh, _ = mtr_core.line_names(row["line_code"])
        rows.append(
            {
                "mode": "mtr",
                "key": (row["line_code"], row["direction"]),
                "seq": 0 if row.get("sequence") is None else row["sequence"],
                "point": f"mtr:{row['id']}",
                "stop": row["id"],
                "route": zh or row["line_code"],
                "operator": "MTR",
            }
        )
    return rows


def _point_table(bus: dict, gmb_stops: dict, stations: dict) -> dict[str, dict]:
    """Every place you can stand at, with the name that network publishes."""
    points: dict[str, dict] = {}
    seen: dict[str, dict] = {}
    for row in bus["data"]:
        if row["latitude"] is None or row["longitude"] is None:
            continue
        seen.setdefault(row["stop"], row)
    for stop_id, row in seen.items():
        points[f"bus:{stop_id}"] = {
            "point": f"bus:{stop_id}",
            "mode": "bus",
            "stop": stop_id,
            "name_zh": row["name_zh"],
            "name_en": row["name_en"],
            "latitude": row["latitude"],
            "longitude": row["longitude"],
        }
    for row in gmb_stops["data"]:
        if row["latitude"] is None or row["longitude"] is None:
            continue
        points[f"minibus:{row['stop']}"] = {
            "point": f"minibus:{row['stop']}",
            "mode": "minibus",
            "stop": row["stop"],
            "name_zh": row["name_zh"],
            "name_en": row["name_en"],
            "latitude": row["latitude"],
            "longitude": row["longitude"],
        }
    for row in tram_core.tram_stops()["data"]:
        if row["latitude"] is None or row["longitude"] is None:
            continue
        points.setdefault(
            f"tram:{row['stop']}",
            {
                "point": f"tram:{row['stop']}",
                "mode": "tram",
                "stop": row["stop"],
                "name_zh": row["name_zh"],
                "name_en": row["name_en"],
                "latitude": row["latitude"],
                "longitude": row["longitude"],
            },
        )
    for row in ferry_core.ferry_stops()["data"]:
        if row["latitude"] is None or row["longitude"] is None:
            continue
        points.setdefault(
            f"ferry:{row['stop']}",
            {
                "point": f"ferry:{row['stop']}",
                "mode": "ferry",
                "stop": row["stop"],
                "name_zh": row["name_zh"],
                "name_en": row["name_en"],
                "latitude": row["latitude"],
                "longitude": row["longitude"],
            },
        )
    for row in stations["data"]:
        points[f"mtr:{row['station_id']}"] = {
            "point": f"mtr:{row['station_id']}",
            "mode": "mtr",
            "stop": row["station_id"],
            "name_zh": row["name_zh"],
            "name_en": None,
            "latitude": row["latitude"],
            "longitude": row["longitude"],
        }
    return points


def _walk_links(
    points: dict[str, dict],
    adjacency: list[list[tuple]],
    point_index: dict[str, int],
    units: dict,
) -> None:
    """Link nearby points, never letting one crowded mode starve the others.

    A station centroid can sit 250 m from its own exits, so a link that touches
    a station gets the wider radius. The nearest point of each rail or water
    mode is always kept, then the rest fill up to the neighbour cap, so a
    corridor full of bus poles cannot crowd out the station 120 m away.
    """
    cells: dict[tuple[int, int], list[str]] = defaultdict(list)
    for key, row in points.items():
        cells[(int(row["latitude"] / 0.005), int(row["longitude"] / 0.005))].append(key)
    for key, row in points.items():
        cell_y, cell_x = int(row["latitude"] / 0.005), int(row["longitude"] / 0.005)
        near: list[tuple[float, str, str]] = []
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                for other in cells.get((cell_y + dy, cell_x + dx), ()):
                    if other == key:
                        continue
                    other_row = points[other]
                    limit = (
                        _MTR_LINK
                        if row["mode"] == "mtr" or other_row["mode"] == "mtr"
                        else _LINK
                    )
                    gap = _places.distance(
                        row["latitude"],
                        row["longitude"],
                        other_row["latitude"],
                        other_row["longitude"],
                    )
                    if gap <= limit:
                        near.append((gap, other, other_row["mode"]))
        near.sort()
        chosen: dict[str, float] = {}
        for mode in _PRIORITY_MODES:
            for gap, other, other_mode in near:
                if other_mode == mode:
                    chosen[other] = gap
                    break
        for gap, other, _ in near:
            if len(chosen) >= _LINK_NEIGHBOURS:
                break
            chosen.setdefault(other, gap)
        for other, gap in chosen.items():
            adjacency[point_index[key]].append(
                (point_index[other], round(gap * units["walk"]), "walk", ())
            )


def _graph() -> dict:
    """Build the whole network once per process, and keep its sources."""
    global _memory
    if _memory is not None:
        return _memory

    bus = bus_core.td_bus_route_stops()
    gmb_stops = minibus_core.gmb_stops()
    gmb_rows = minibus_core.gmb_route_stops()
    tram_rows = tram_core.tram_stops()
    ferry_rows = ferry_core.ferry_stops()
    mtr_rows = mtr_core.lines_and_stations()
    stations = exits.mtr_station_points()
    sources = [bus, gmb_stops, gmb_rows, tram_rows, ferry_rows, mtr_rows, stations]

    trips = _trip_rows(bus, gmb_rows, tram_rows, ferry_rows, mtr_rows)
    points = _point_table(bus, gmb_stops, stations)
    by_trip: dict[tuple[str, tuple], list[tuple[float, str]]] = defaultdict(list)
    labels: dict[tuple[str, tuple], dict] = {}
    for row in trips:
        if row["point"] not in points:
            continue
        by_trip[(row["mode"], row["key"])].append((row["seq"], row["point"]))
        labels.setdefault(
            (row["mode"], row["key"]),
            {"route": row["route"], "operator": row["operator"]},
        )

    units = _units()
    point_index = {key: index for index, key in enumerate(points)}
    nodes: list[tuple] = [("point", key) for key in points]
    adjacency: list[list[tuple]] = [[] for _ in nodes]

    # Boarding goes straight to the next stop, so every ride moves at least one
    # stop and the search never needs to remember whether it has ridden.
    # Hop weight is dwell + distance/speed between consecutive stop points.
    for (mode, key), stops in by_trip.items():
        stops.sort()
        if len(stops) < 2:
            continue
        previous = None
        for position in range(1, len(stops)):
            node = len(nodes)
            nodes.append(("trip", (mode, key, position)))
            adjacency.append([])
            from_key = stops[position - 1][1]
            to_key = stops[position][1]
            board_point = point_index[from_key]
            from_row = points[from_key]
            to_row = points[to_key]
            metres = _places.distance(
                from_row["latitude"],
                from_row["longitude"],
                to_row["latitude"],
                to_row["longitude"],
            )
            hop = _ride_cost(units, mode, metres)
            board = units["board"].get(mode, units["board"]["bus"])
            adjacency[board_point].append(
                (
                    node,
                    board + hop,
                    "board",
                    (mode, key),
                )
            )
            adjacency[node].append(
                (point_index[to_key], 0, "alight", (mode, key))
            )
            if previous is not None:
                adjacency[previous].append((node, hop, "ride", (mode, key)))
            previous = node

    _walk_links(points, adjacency, point_index, units)

    _memory = {
        "points": points,
        "point_index": point_index,
        "nodes": nodes,
        "adjacency": adjacency,
        "labels": labels,
        "sources": sources,
        "units": units,
        "point_key": {
            index: node[1] for index, node in enumerate(nodes) if node[0] == "point"
        },
    }
    return _memory


def _nearby(
    points: dict[str, dict],
    latitude: float,
    longitude: float,
    radius: float,
) -> list[tuple[float, str]]:
    found = []
    for key, row in points.items():
        gap = _places.distance(latitude, longitude, row["latitude"], row["longitude"])
        if gap <= radius:
            found.append((gap, key))
    found.sort()
    return found


def _dijkstra(
    adjacency: list[list[tuple]],
    starts: list[tuple[int, int]],
    end_weights: dict[int, int],
    point_key: dict[int, str],
    units: dict,
    penalty: set | None = None,
    banned: set | None = None,
    hard_ban: set | None = None,
):
    """Shortest path that must ride, may not chain walks, and may end anywhere.

    The end is not an edge: reaching a destination point without having just
    walked adds its walk cost. That keeps the adjacency immutable, so a query
    no longer copies 80,000 lists.
    """
    best: dict[tuple[int, bool], int] = {}
    previous: dict[tuple[int, bool], tuple[tuple[int, bool] | None, str, tuple]] = {}
    queue: list[tuple[int, int, bool]] = []
    for cost, node in starts:
        state = (node, True)
        if cost < best.get(state, math.inf):
            best[state] = cost
            previous[state] = (None, "start", (point_key.get(node),))
            heapq.heappush(queue, (cost, node, True))

    goal = None
    total = 0
    while queue:
        cost, node, walked = heapq.heappop(queue)
        state = (node, walked)
        if cost > best.get(state, math.inf):
            continue
        if node == _END:
            goal = state
            total = cost
            break
        if not walked and node in end_weights:
            total = cost + end_weights[node]
            end_state = (_END, True)
            if total < best.get(end_state, math.inf):
                best[end_state] = total
                previous[end_state] = (state, "end", (point_key.get(node),))
                heapq.heappush(queue, (total, _END, True))
        for target, weight, kind, meta in adjacency[node]:
            stepping = kind in {"walk"}
            if stepping and walked:
                continue
            if kind == "walk" and banned:
                pair = frozenset((point_key.get(node), point_key.get(target)))
                if pair in banned:
                    continue
            if hard_ban and kind == "board" and meta in hard_ban:
                continue
            step = weight
            if penalty and kind == "board" and meta in penalty:
                step = weight + units["board"].get(
                    meta[0], units["board"]["bus"]
                )
            candidate = cost + step
            nxt = (target, stepping)
            if candidate < best.get(nxt, math.inf):
                best[nxt] = candidate
                previous[nxt] = (state, kind, meta)
                heapq.heappush(queue, (candidate, target, stepping))

    if goal is None:
        return None
    path = []
    state = goal
    while True:
        before, kind, meta = previous[state]
        if before is None:
            path.append((None, state[0], kind, meta))
            break
        path.append((before[0], state[0], kind, meta))
        state = before
    path.reverse()
    return path, total


def _legs(path, graph, origin_point, destination_point) -> list[dict]:
    """Turn an edge path into walk and ride legs."""
    points = graph["points"]
    legs: list[dict] = []
    ride = None

    def point_of(node: int) -> dict:
        if node == _END:
            return destination_point
        return points[graph["nodes"][node][1]]

    def walk_leg(from_point: dict, to_point: dict, from_key, to_key) -> None:
        gap = round(
            _places.distance(
                from_point["latitude"],
                from_point["longitude"],
                to_point["latitude"],
                to_point["longitude"],
            )
        )
        if gap == 0:
            return
        legs.append(
            {
                "type": "walk",
                "metres": gap,
                "from": {
                    "name_zh": from_point["name_zh"],
                    "latitude": from_point["latitude"],
                    "longitude": from_point["longitude"],
                },
                "to": {
                    "name_zh": to_point["name_zh"],
                    "latitude": to_point["latitude"],
                    "longitude": to_point["longitude"],
                },
                "from_point": from_key,
                "to_point": to_key,
            }
        )

    for source, target, kind, meta in path:
        if kind == "start":
            walk_leg(origin_point, point_of(target), None, meta[0])
            continue
        if kind == "walk":
            walk_leg(point_of(source), point_of(target), meta[0] if meta else graph["nodes"][source][1], graph["nodes"][target][1])
            continue
        if kind == "end":
            walk_leg(point_of(source), destination_point, meta[0], None)
            continue
        if kind == "board":
            mode, key = meta[0], meta[1]
            label = graph["labels"].get((mode, key)) or {}
            ride = {
                "type": "ride",
                "mode": mode,
                "trip": (mode, key),
                "route": label.get("route"),
                "overnight": bool(_OVERNIGHT.match(label.get("route") or "")),
                "operator": label.get("operator"),
                "board": points[graph["nodes"][source][1]]["name_zh"],
                "alight": None,
                "stops": 1,
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


def _score_after_walks(option: dict, old_walk_metres: float, units: dict) -> int:
    """Adjust Dijkstra search_cost by the walk-metre delta after pedroute reprice.

    Ride costs stay as searched (distance/speed); only the walk portion moves.
    """
    new_walk = sum(leg["metres"] for leg in option["legs"] if leg["type"] == "walk")
    return option["search_cost"] + round((new_walk - old_walk_metres) * units["walk"])


def _price_walks(legs: list[dict], budget: _WalkBudget, sources: list[dict]) -> dict:
    """Replace straight-line walk metres with the pedestrian network, in place.

    Returns ``{pairs, origins, dests}`` of bad walks (real ≫ straight), so the
    caller can ban mid-journey pairs and/or origin/destination stops and search
    again. Uses the process-level ``_walk_cache`` so identical rounded coord
    pairs are not re-fetched.
    """
    pairs: set = set()
    origins: set = set()
    dests: set = set()
    for leg in legs:
        if leg["type"] != "walk":
            continue
        if leg["metres"] == 0:
            leg["minutes"] = 0.0
            continue
        straight = leg["metres"]
        from_lat = leg["from"]["latitude"]
        from_lon = leg["from"]["longitude"]
        to_lat = leg["to"]["latitude"]
        to_lon = leg["to"]["longitude"]
        cache_key = _walk_cache_key(from_lat, from_lon, to_lat, to_lon)
        if cache_key in _walk_cache:
            data = _walk_cache[cache_key]
            if data is None:
                leg["estimated"] = True
                continue
        else:
            if not budget.take():
                leg["estimated"] = True
                continue
            try:
                result = pedroute.walk_route(from_lat, from_lon, to_lat, to_lon)
            except Exception:  # a failed walk must not lose the journey
                _walk_cache[cache_key] = None
                leg["estimated"] = True
                continue
            sources.append(result)
            payload = result["data"] or {}
            if payload.get("found"):
                data = {
                    "metres": payload["metres"],
                    "minutes": payload["minutes"],
                }
                _walk_cache[cache_key] = data
            else:
                _walk_cache[cache_key] = None
                leg["estimated"] = True
                continue
        leg["straight_line_metres"] = straight
        leg["metres"] = round(data["metres"])
        leg["minutes"] = round(data["minutes"], 1)
        if data["metres"] > straight * _BAD_WALK_RATIO:
            from_point = leg.get("from_point")
            to_point = leg.get("to_point")
            if from_point and to_point:
                pairs.add(frozenset((from_point, to_point)))
            elif from_point is None and to_point:
                origins.add(to_point)
            elif to_point is None and from_point:
                dests.add(from_point)
    return {"pairs": pairs, "origins": origins, "dests": dests}


def _search(graph, starts, end_weights, options: int, banned: set, origin_point, destination_point) -> list[dict]:
    chosen: list[dict] = []
    seen: set[tuple] = set()
    penalty: set = set()
    hard_ban: set = set()
    keys_by_label: dict[tuple, set] = defaultdict(set)
    for (mode, key), label in graph["labels"].items():
        # Penalty / hard_ban compare against board meta `(mode, key)`.
        keys_by_label[(mode, label["operator"], label["route"])].add((mode, key))
    for _ in range(options * 2):
        found = _dijkstra(
            graph["adjacency"],
            starts,
            end_weights,
            graph["point_key"],
            graph["units"],
            penalty,
            banned,
            hard_ban,
        )
        if found is None:
            break
        path, total = found
        legs = _legs(path, graph, origin_point, destination_point)
        rides = [leg for leg in legs if leg["type"] == "ride"]
        if not rides:
            break
        signature = tuple(
            (leg["mode"], leg.get("route"), leg["board_point"], leg["alight_point"])
            for leg in rides
        )
        for leg in rides:
            penalty.update(
                keys_by_label.get((leg["mode"], leg.get("operator"), leg.get("route")), set())
            )
        if signature in seen:
            hard_ban.update(leg["trip"] for leg in rides)
            continue
        seen.add(signature)
        chosen.append(
            {
                "transfers": max(len(rides) - 1, 0),
                "overnight_hint": any(leg.get("overnight") for leg in rides),
                "stops": sum(leg["stops"] for leg in rides),
                "walk_metres": sum(leg["metres"] for leg in legs if leg["type"] == "walk"),
                "search_cost": total,
                "legs": legs,
            }
        )
        if len(chosen) >= options:
            break
    return chosen


def journey(
    origin: str,
    destination: str,
    options: int = 3,
    walk: int = _WALK,
) -> dict:
    """由一個地方去另一個地方，用晒所有已接入的交通網絡。

    資料集：港鐵 `mtr_core.lines_and_stations`、專營巴士
    `bus_core.td_bus_route_stops`（含城巴、新大嶼山、港鐵巴士）、
    綠色專線小巴 `minibus_core.gmb_route_stops`、電車 `tram_core.tram_stops`、
    渡輪 `ferry_core.ferry_stops`、車站座標 `exits.mtr_station_points`、
    步行 `pedroute.walk_route`、地名 `geocode.place_search`。
    用法：`journey("元州邨", "香港迪士尼樂園")`。
    市民會問：由我呢度去 X，搭咩車？要唔要轉車？行幾遠？

    交還多個方案，每個帶步行段同乘車段。成本係政策分鐘（上車等候、
    距離／車速、停站、步行），唔係 ETA 或實測時間；乘車時間冇公布數據，
    只有步行時間來自行人路網。山頂纜車、的士、高鐵未接入，跨出這個範圍的組合接唔上。

    每一次 boarding 都至少坐一個站；純步行方案唔會出現。
    地名由地政總署地點搜尋解析，所以 `sources` 只列網絡同步行來源。
    """
    options = options or 3
    walk = walk or _WALK
    graph = _graph()
    points = graph["points"]
    sources = list(graph["sources"])
    start_point, note = _places.place(origin, points)
    if start_point is None:
        return compose(sources, None, note=note)
    end_point, note = _places.place(destination, points)
    if end_point is None:
        return compose(sources, None, note=note)

    wide = max(walk, _WALK_RETRY)
    origin_edges = _nearby(points, start_point["latitude"], start_point["longitude"], walk)
    target_edges = _nearby(points, end_point["latitude"], end_point["longitude"], walk)
    widened = ""
    if not origin_edges or not target_edges:
        origin_edges = origin_edges or _nearby(
            points, start_point["latitude"], start_point["longitude"], wide
        )
        target_edges = target_edges or _nearby(
            points, end_point["latitude"], end_point["longitude"], wide
        )
        widened = f"最近站超過 {walk} 米，已自動放寬到 {wide} 米。"
    if not origin_edges:
        return compose(sources, None, note=f"起點 {wide} 米內沒有已接入的站。")
    if not target_edges:
        return compose(sources, None, note=f"終點 {wide} 米內沒有已接入的站。")

    walk_unit = graph["units"]["walk"]
    starts = [
        (round(gap * walk_unit), graph["point_index"][key]) for gap, key in origin_edges
    ]
    end_weights = {
        graph["point_index"][key]: round(gap * walk_unit) for gap, key in target_edges
    }
    base_starts = starts
    base_end_weights = end_weights
    banned: set = set()
    banned_origins: set = set()
    banned_dests: set = set()
    chosen: list[dict] = []
    walk_sources: list[dict] = []
    walk_budget_calls = max(_WALK_CALLS, options * 4)
    for attempt in range(2):
        starts = [
            (cost, node)
            for cost, node in base_starts
            if graph["point_key"].get(node) not in banned_origins
        ]
        end_weights = {
            node: weight
            for node, weight in base_end_weights.items()
            if graph["point_key"].get(node) not in banned_dests
        }
        if not starts or not end_weights:
            break  # keep previous chosen (same as empty search)
        found = _search(
            graph, starts, end_weights, options, banned, start_point, end_point
        )
        if not found:
            break  # keep the first-pass options if a retry finds nothing
        chosen = found
        budget = _WalkBudget(calls=walk_budget_calls)
        walk_sources = []
        bad_pairs: set = set()
        bad_origins: set = set()
        bad_dests: set = set()
        for option in chosen:
            old_walk = option["walk_metres"]
            priced = _price_walks(option["legs"], budget, walk_sources)
            bad_pairs |= priced["pairs"]
            bad_origins |= priced["origins"]
            bad_dests |= priced["dests"]
            option["walk_metres"] = sum(
                leg["metres"] for leg in option["legs"] if leg["type"] == "walk"
            )
            option["score"] = _score_after_walks(option, old_walk, graph["units"])
        if not (bad_pairs or bad_origins or bad_dests) or attempt == 1:
            break
        banned = bad_pairs
        banned_origins = bad_origins
        banned_dests = bad_dests
    sources.extend(walk_sources)

    if not chosen:
        return compose(sources, None, note=NOTE + "這兩個地方在已接入的網絡上接不上。")

    kept = [option for option in chosen if option["walk_metres"] <= _WALK_CAP]
    if not kept:
        kept = chosen[:1]
        extra = f"每個方案的總步行都超過 {_WALK_CAP} 米，這裡只列最短的一個。"
    else:
        extra = ""
    # A night route may be the cheapest on paper, but at 2 pm it may not run.
    # There is no service-hours data, so the only honest move is to rank it
    # below every day option and say so.
    kept.sort(key=lambda option: (option["overnight_hint"], option["score"]))
    shown = kept[:options]
    overnight = sum(1 for option in shown if option["overnight_hint"])
    if overnight:
        extra += (
            f"其中 {overnight} 個方案用通宵線（N 字頭），日間未必有車。"
            "服務時間同班次冇數據，請向營辦商確認。"
        )
    return compose(
        sources,
        {
            "origin": start_point,
            "destination": end_point,
            "options": shown,
        },
        note=NOTE + widened + extra,
    )
