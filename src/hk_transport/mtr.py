"""Citizen-facing MTR tools.

Each function calls `hk_transport.mtr_core` and does not fetch HTTP itself.
A result that the published data cannot support has `data: null` and a note.

These tools do not answer: first or last train, journey minutes, which exit
serves a building, crowding, or the high-speed rail.
"""

from __future__ import annotations

import heapq
from collections import defaultdict

from hk_transport import mtr_core
from hk_transport._result import NO_ALERT, compose

# Codes published in mtr_lines_and_stations.csv. The CSV has no line names.
LINES = {
    "AEL": ("機場快線", "Airport Express"),
    "DRL": ("迪士尼線", "Disneyland Resort Line"),
    "EAL": ("東鐵線", "East Rail Line"),
    "ISL": ("港島線", "Island Line"),
    "KTL": ("觀塘線", "Kwun Tong Line"),
    "SIL": ("南港島線", "South Island Line"),
    "TCL": ("東涌線", "Tung Chung Line"),
    "TKL": ("將軍澳線", "Tseung Kwan O Line"),
    "TML": ("屯馬線", "Tuen Ma Line"),
    "TWL": ("荃灣線", "Tsuen Wan Line"),
}

# AEL Hong Kong, TCL Hong Kong, and Central use different ids for one interchange.
_ALIAS = {"1", "39", "44"}

DOMESTIC_FARE_COLUMNS = (
    "OCT_ADT_FARE",
    "OCT_STD_FARE",
    "OCT_JOYYOU_SIXTY_FARE",
    "OCT_CON_CHILD_FARE",
    "OCT_CON_ELDERLY_FARE",
    "OCT_CON_PWD_FARE",
    "SINGLE_ADT_FARE",
    "SINGLE_CON_CHILD_FARE",
    "SINGLE_CON_ELDERLY_FARE",
)
AEL_FARE_COLUMNS = (
    "OCT_ADT_FARE",
    "OCT_CHD_FARE",
    "SINGLE_ADT_FARE",
    "SINGLE_CHD_FARE",
)
LR_FARE_COLUMNS = (
    "fare_octo_adult",
    "fare_octo_child",
    "fare_octo_elderly",
    "fare_octo_pwd",
    "fare_octo_student",
    "fare_octo_joyyou_sixty",
    "fare_single_adult",
    "fare_single_child",
    "fare_single_elderly",
)


def _view(row: dict) -> dict:
    return {
        "id": row["id"],
        "code": row["code"],
        "name_zh": row["name_zh"],
        "name_en": row["name_en"],
    }


def _line_names(code: str) -> tuple[str | None, str | None]:
    return LINES.get(code, (None, None))


def _matches(row: dict, query: str) -> bool:
    folded = query.casefold()
    return (
        row["id"] == mtr_core.norm_id(query)
        or row["code"].casefold() == folded
        or row["name_zh"] == query
        or row["name_en"].casefold() == folded
    )


def _match_ids(query: str, rows: list[dict]) -> list[str]:
    found: list[str] = []
    seen: set[str] = set()
    text = query.strip()
    for row in rows:
        if row["id"] in seen:
            continue
        if _matches(row, text):
            seen.add(row["id"])
            found.append(row["id"])
    return found


def _representatives(rows: list[dict]) -> dict[str, dict]:
    chosen: dict[str, dict] = {}
    for row in rows:
        chosen.setdefault(row["id"], row)
    return chosen


def _resolve_line(query: str, rows: list[dict]) -> str | None:
    text = query.strip()
    folded = text.casefold()
    for code, (zh, en) in LINES.items():
        if folded == code.casefold() or text == zh or folded == en.casefold():
            return code
    codes = {row["line_code"] for row in rows}
    if text in codes:
        return text
    upper = text.upper()
    if upper in codes:
        return upper
    return None


def _missing(query: str) -> str:
    return f"找不到車站：{query}"


def _group_lines(rows: list[dict]) -> list[dict]:
    grouped: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for row in rows:
        grouped[(row["line_code"], row["direction"])].append(row)
    by_line: dict[str, list[dict]] = defaultdict(list)
    for (code, direction), stops in sorted(grouped.items()):
        stops.sort(key=lambda row: row["sequence"])
        by_line[code].append(
            {
                "direction": direction,
                "first": _view(stops[0]),
                "last": _view(stops[-1]),
                "stations": [_view(stop) for stop in stops],
            }
        )
    result = []
    for code in sorted(by_line):
        zh, en = _line_names(code)
        result.append(
            {
                "line_code": code,
                "line_zh": zh,
                "line_en": en,
                "directions": by_line[code],
            }
        )
    return result


def _ambiguous(ids: list[str]) -> bool:
    return len(ids) > 1 and not set(ids) <= _ALIAS


def _project(fares: dict | None, columns: tuple[str, ...]) -> tuple[dict, list[str]]:
    source = fares or {}
    missing = [column for column in columns if column not in source]
    projected = {column: source.get(column) for column in columns}
    for key, value in source.items():
        if key not in projected:
            projected[key] = value
    return projected, missing


def _join_notes(*parts: str | None) -> str | None:
    kept = [part for part in parts if part]
    if not kept:
        return None
    return " ".join(kept)


def mtr_lines(line: str | None = None, station: str | None = None) -> dict:
    """一條線上、一個方向的車站順序，或一個站屬於哪些線。

    提供路線與車站。資料集 `mtr-data-routes-fares-barrier-free-facilities`，
    端點由 `lines_and_stations` 帶出。

    用法：`mtr_lines(line="觀塘線")`，`mtr_lines(station="金鐘")`。
    市民會問：觀塘線有哪些站？金鐘是哪幾條線的轉車站？

    東鐵線的羅湖和落馬洲、將軍澳線的康城各自一個方向，不會併成一條順序。
    方向代碼保持原樣（DT、UT、LMC-*、TKS-*）。
    """
    source = mtr_core.lines_and_stations()
    rows = source["data"]
    chosen = rows
    if line is not None:
        code = _resolve_line(line, rows)
        if code is None:
            return compose([source], None, note=f"找不到路線：{line}")
        chosen = [row for row in chosen if row["line_code"] == code]
    if station is not None:
        ids = _match_ids(station, chosen)
        if not ids:
            return compose([source], None, note=_missing(station))
        reps = _representatives(rows)
        stations = []
        for station_id in ids:
            mine = [row for row in chosen if row["id"] == station_id]
            stations.append({"station": _view(reps[station_id]), "lines": _group_lines(mine)})
        note = "這個名稱對應多於一個車站。" if len(ids) > 1 else None
        return compose([source], {"stations": stations}, note=note)
    if not chosen:
        return compose([source], None, note=f"找不到路線：{line}")
    return compose([source], {"lines": _group_lines(chosen)})


def _transfer_key(station_id: str) -> str:
    if station_id in _ALIAS:
        return "central-hk"
    return station_id


def _journey_path(rows: list[dict], origin_ids: list[str], dest_ids: list[str]) -> dict | None:
    platforms = list(rows)
    rides: dict[int, list[int]] = defaultdict(list)
    by_direction: dict[tuple[str, str], list[int]] = defaultdict(list)
    for index, platform in enumerate(platforms):
        by_direction[(platform["line_code"], platform["direction"])].append(index)
    for indexes in by_direction.values():
        indexes.sort(key=lambda index: platforms[index]["sequence"])
        for left, right in zip(indexes, indexes[1:]):
            rides[left].append(right)

    transfers: dict[int, list[int]] = defaultdict(list)
    by_key: dict[str, list[int]] = defaultdict(list)
    for index, platform in enumerate(platforms):
        by_key[_transfer_key(platform["id"])].append(index)
    for indexes in by_key.values():
        for left in indexes:
            for right in indexes:
                if left == right:
                    continue
                same_ride = (
                    platforms[left]["line_code"] == platforms[right]["line_code"]
                    and platforms[left]["direction"] == platforms[right]["direction"]
                )
                if not same_ride:
                    transfers[left].append(right)

    origin_set = set(origin_ids)
    dest_set = set(dest_ids)
    starts = [index for index, platform in enumerate(platforms) if platform["id"] in origin_set]
    ends = {index for index, platform in enumerate(platforms) if platform["id"] in dest_set}
    if not starts or not ends:
        return None

    best: dict[int, tuple[int, int]] = {}
    previous: dict[int, tuple[int, str]] = {}
    heap: list[tuple[int, int, int]] = []
    for start in starts:
        best[start] = (0, 0)
        heapq.heappush(heap, (0, 0, start))
    found: int | None = None
    while heap:
        transfer_count, ride_count, node = heapq.heappop(heap)
        if best.get(node) != (transfer_count, ride_count):
            continue
        if node in ends:
            found = node
            break
        for nxt in rides[node]:
            cost = (transfer_count, ride_count + 1)
            if nxt not in best or cost < best[nxt]:
                best[nxt] = cost
                previous[nxt] = (node, "ride")
                heapq.heappush(heap, (*cost, nxt))
        for nxt in transfers[node]:
            cost = (transfer_count + 1, ride_count)
            if nxt not in best or cost < best[nxt]:
                best[nxt] = cost
                previous[nxt] = (node, "transfer")
                heapq.heappush(heap, (*cost, nxt))
    if found is None:
        return None

    chain = [found]
    while chain[-1] in previous:
        chain.append(previous[chain[-1]][0])
    chain.reverse()

    legs = []
    walked = []
    index = 0
    while index < len(chain) - 1:
        kind = previous[chain[index + 1]][1]
        if kind == "transfer":
            walked.append(
                {
                    "from": _view(platforms[chain[index]]),
                    "to": _view(platforms[chain[index + 1]]),
                }
            )
            index += 1
            continue
        end = index
        while end + 1 < len(chain) and previous[chain[end + 1]][1] == "ride":
            end += 1
        first = platforms[chain[index]]
        zh, en = _line_names(first["line_code"])
        legs.append(
            {
                "line_code": first["line_code"],
                "line_zh": zh,
                "line_en": en,
                "direction": first["direction"],
                "board": _view(first),
                "alight": _view(platforms[chain[end]]),
                "stations": [_view(platforms[step]) for step in chain[index : end + 1]],
            }
        )
        index = end
    transfer_count, ride_count = best[found]
    return {
        "transfers": transfer_count,
        "ride_count": ride_count,
        "legs": legs,
        "interchanges": walked,
    }


def mtr_journey(origin: str, destination: str) -> dict:
    """兩站之間的一條路徑：乘哪條線、在哪裡轉車、中間停哪些站。

    提供轉乘路徑。只用 `lines_and_stations`。沒有行車分鐘。

    用法：`mtr_journey("柴灣", "荃灣")`。
    市民會問：由柴灣去荃灣，乘哪條線，在哪一站轉車？

    轉車以共用車站編號連接。機場快線香港站（44）、東涌線香港站（39）
    和中環站（1）可以互轉。搜尋先減少轉車次數，再減少停車站數。
    """
    source = mtr_core.lines_and_stations()
    rows = source["data"]
    origin_ids = _match_ids(origin, rows)
    dest_ids = _match_ids(destination, rows)
    if not origin_ids or not dest_ids:
        missing = origin if not origin_ids else destination
        return compose([source], None, note=_missing(missing))
    if _ambiguous(origin_ids) or _ambiguous(dest_ids):
        reps = _representatives(rows)
        return compose(
            [source],
            {
                "origin_matches": [_view(reps[station_id]) for station_id in origin_ids],
                "destination_matches": [_view(reps[station_id]) for station_id in dest_ids],
            },
            note="這個名稱對應多於一個車站，沒有選其中一條路徑。",
        )
    if set(origin_ids) & set(dest_ids):
        reps = _representatives(rows)
        shared = next(iter(set(origin_ids) & set(dest_ids)))
        return compose(
            [source],
            {
                "origin": _view(reps[shared]),
                "destination": _view(reps[shared]),
                "transfers": 0,
                "ride_count": 0,
                "legs": [],
                "interchanges": [],
            },
            note="起點同終點是同一個站。",
        )
    path = _journey_path(rows, origin_ids, dest_ids)
    if path is None:
        return compose([source], None, note="這兩站在重鐵路網裡接不上。")
    reps = _representatives(rows)
    return compose(
        [source],
        {
            "origin": _view(reps[origin_ids[0]]),
            "destination": _view(reps[dest_ids[0]]),
            **path,
        },
    )


def _fare_pairs(
    origin_ids: list[str],
    dest_ids: list[str],
    rows: list[dict],
    fare_rows: list[dict],
    columns: tuple[str, ...],
) -> tuple[list[dict], list[str], bool]:
    reps = _representatives(rows)
    index = {(row["from_id"], row["to_id"]): row for row in fare_rows}
    pairs = []
    missing: list[str] = []
    any_row = False
    for origin_id in origin_ids:
        for dest_id in dest_ids:
            fare = index.get((origin_id, dest_id))
            projected, absent = _project(None if fare is None else fare["fares"], columns)
            missing.extend(column for column in absent if column not in missing)
            any_row = any_row or fare is not None
            pairs.append(
                {
                    "from": _view(reps[origin_id]),
                    "to": _view(reps[dest_id]),
                    "fares": projected if fare is not None else None,
                }
            )
    return pairs, missing, any_row


def mtr_fare(origin: str, destination: str) -> dict:
    """兩個重鐵站之間的車費。車費跟路徑無關。

    提供八達通同單程票各欄。中文站名經 `lines_and_stations` 對上車站編號，
    再查 `domestic_fares`。車費檔裡的站名是英文。

    用法：`mtr_fare("中環", "紅磡")`。
    市民會問：由中環去紅磡，八達通同單程票幾多錢？

    檔案沒有的票種留空。不會用另一種票頂替。
    """
    lines = mtr_core.lines_and_stations()
    origin_ids = _match_ids(origin, lines["data"])
    dest_ids = _match_ids(destination, lines["data"])
    if not origin_ids or not dest_ids:
        missing = origin if not origin_ids else destination
        return compose([lines], None, note=_missing(missing))
    fares = mtr_core.domestic_fares()
    pairs, missing, found = _fare_pairs(
        origin_ids, dest_ids, lines["data"], fares["data"], DOMESTIC_FARE_COLUMNS
    )
    note = _join_notes(
        "這個名稱對應多於一個車站，以下是每一對的車費。"
        if len(origin_ids) > 1 or len(dest_ids) > 1
        else None,
        None if found else "車費檔沒有這一對車站。",
        f"車費檔沒有這些欄：{', '.join(missing)}。" if missing else None,
    )
    return compose([lines, fares], {"pairs": pairs}, note=note)


def _normal_service(payload: dict) -> bool:
    message = (payload.get("message") or "").casefold()
    status = payload.get("status")
    delayed = (payload.get("isdelay") or "").upper() == "Y"
    return (
        str(status) in {"1", "None"}
        and message in {"", "successful", "success"}
        and not payload.get("url")
        and not delayed
    )


def _station_by_code(rows: list[dict], code: str | None) -> dict:
    if code:
        for row in rows:
            if row["code"] == code:
                return _view(row)
    return {"id": None, "code": code, "name_zh": None, "name_en": None}


def mtr_next_train(line: str, station: str) -> dict:
    """這一站、這一線，下一個方向最多四班車，以及這次回應有沒有特別車務安排。

    提供到站或開出時間、終點站、月台。機場快線和迪士尼線走同一個核心函式
    `next_train`。資料集 `mtr-data2-nexttrain-data`。

    用法：`mtr_next_train("港島線", "金鐘")`。
    市民會問：下一班幾時到？哪個月台？終點站是哪？而家有沒有特別車務安排？

    這不是頭班車或尾班車。沒有警報時，note 是「這次回應沒有特別安排」，
    不會寫成全線正常。
    """
    lines = mtr_core.lines_and_stations()
    rows = lines["data"]
    line_code = _resolve_line(line, rows)
    if line_code is None:
        return compose([lines], None, note=f"找不到路線：{line}")
    ids = _match_ids(station, rows)
    if not ids:
        return compose([lines], None, note=_missing(station))
    on_line = [row for row in rows if row["line_code"] == line_code and row["id"] in ids]
    if not on_line:
        return compose([lines], None, note="這個站不在這條線上。")
    codes = []
    for row in on_line:
        if row["code"] not in codes:
            codes.append(row["code"])
    if len(codes) > 1:
        reps = _representatives(rows)
        return compose(
            [lines],
            {"matches": [_view(reps[row["id"]]) for row in on_line]},
            note="這個站名在這條線上對應多於一個車站代碼。",
        )
    live = mtr_core.next_train(line_code, codes[0])
    directions = []
    for direction in live["data"]["directions"]:
        trains = []
        for train in direction["trains"]:
            trains.append(
                {
                    "seq": train["seq"],
                    "dest": _station_by_code(rows, train["dest"]),
                    "platform": train["platform"],
                    "time": train["time"],
                    "ttnt": train["ttnt"],
                    "valid": train["valid"],
                }
            )
        directions.append({"direction": direction["direction"], "trains": trains})
    zh, en = _line_names(line_code)
    alert = None if _normal_service(live["data"]) else {
        "status": live["data"]["status"],
        "message": live["data"]["message"],
        "url": live["data"]["url"],
        "isdelay": live["data"]["isdelay"],
    }
    return compose(
        [lines, live],
        {
            "line_code": line_code,
            "line_zh": zh,
            "line_en": en,
            "station": _view(on_line[0]),
            "directions": directions,
            "alert": alert,
        },
        note=None if alert else NO_ALERT,
    )


def mtr_airport_express_fare(origin: str, destination: str) -> dict:
    """機場快線成人同小童車費。下一班用 `mtr_next_train`。

    只用 `airport_express_fares`。不會套用重鐵的長者、學生或樂悠咭車費。

    用法：`mtr_airport_express_fare("香港", "機場")`。
    市民會問：機場快線由香港站去機場，成人同小童幾多錢？
    """
    lines = mtr_core.lines_and_stations()
    origin_ids = _match_ids(origin, lines["data"])
    dest_ids = _match_ids(destination, lines["data"])
    if not origin_ids or not dest_ids:
        missing = origin if not origin_ids else destination
        return compose([lines], None, note=_missing(missing))
    fares = mtr_core.airport_express_fares()
    pairs, missing, found = _fare_pairs(
        origin_ids, dest_ids, lines["data"], fares["data"], AEL_FARE_COLUMNS
    )
    note = _join_notes(
        "這個名稱對應多於一個車站，以下是每一對的車費。"
        if len(origin_ids) > 1 or len(dest_ids) > 1
        else None,
        None if found else "機場快線車費檔沒有這一對車站。",
        "機場快線車費檔只有成人同小童。",
        f"車費檔沒有這些欄：{', '.join(missing)}。" if missing else None,
    )
    return compose([lines, fares], {"pairs": pairs}, note=note)


def mtr_barrier_free(station: str) -> dict:
    """一個站有哪些無障礙設施、在哪個出口。

    設施鍵由 `barrier_free_categories` 譯成名稱。只交還標成有的設施。
    出口座標是空的就留空。

    用法：`mtr_barrier_free("金鐘")`。
    市民會問：這個站有沒有升降機、寬閘、無障礙洗手間？

    這不是「去某座大廈行哪個出口」。
    """
    lines = mtr_core.lines_and_stations()
    ids = _match_ids(station, lines["data"])
    if not ids:
        return compose([lines], None, note=_missing(station))
    facilities = mtr_core.barrier_free_facilities()
    categories = mtr_core.barrier_free_categories()
    names = {row["key"]: row for row in categories["data"]}
    reps = _representatives(lines["data"])
    stations = []
    for station_id in ids:
        items = []
        for row in facilities["data"]:
            if row["station_id"] != station_id or not row["present"]:
                continue
            category = names.get(row["key"], {})
            items.append(
                {
                    "key": row["key"],
                    "name_zh": category.get("name_zh"),
                    "name_en": category.get("name_en"),
                    "category_zh": category.get("category_zh"),
                    "category_en": category.get("category_en"),
                    "exit_zh": row["exit_zh"],
                    "exit_en": row["exit_en"],
                    "coordinate": row["coordinate"],
                }
            )
        stations.append({"station": _view(reps[station_id]), "facilities": items})
    note = "這個名稱對應多於一個車站。" if len(ids) > 1 else None
    return compose([lines, facilities, categories], {"stations": stations}, note=note)


def light_rail_next(station: str) -> dict:
    """輕鐵這一站即將開出的班次，包括特別班。

    站名經 `light_rail_routes` 對上 stop id，再呼叫 `light_rail_next_train`
    （`with_special=1`）。資料集 `mtr-lrnt_data-light-rail-nexttrain-data`。
    數據時間用 API 的 `system_time`。

    用法：`light_rail_next("元朗")`。元朗的 stop id 是 600。
    市民會問：下一班是幾號、去哪、還有幾多分鐘？是不是特別班？
    """
    routes = mtr_core.light_rail_routes()
    ids = _match_ids(station, routes["data"])
    if not ids:
        return compose([routes], None, note=_missing(station))
    if len(ids) > 1:
        reps = _representatives(routes["data"])
        return compose(
            [routes],
            {"matches": [_view(reps[station_id]) for station_id in ids]},
            note="這個名稱對應多於一個輕鐵站，沒有查下一班。",
        )
    live = mtr_core.light_rail_next_train(ids[0])
    return compose(
        [routes, live],
        {
            "station": _view(_representatives(routes["data"])[ids[0]]),
            "platforms": live["data"]["platforms"],
        },
    )


def light_rail(
    line: str | None = None,
    origin: str | None = None,
    destination: str | None = None,
) -> dict:
    """輕鐵某線一個方向的車站順序，以及兩站之間的車費。

    路線用 `light_rail_routes`，車費用 `light_rail_fares`。可以只問路線、
    只問車費，或兩個一起問。

    用法：`light_rail(line="610")`，`light_rail(origin="屯門", destination="元朗")`。
    市民會問：610 線停哪些站？由屯門去元朗幾多錢？
    """
    if line is None and not (origin and destination):
        return {
            "dataset_id": None,
            "endpoint": None,
            "retrieved_at": None,
            "data_at": None,
            "update_frequency": None,
            "data": None,
            "note": "要給路線，或同時給起點同終點。",
        }
    routes = mtr_core.light_rail_routes()
    sources = [routes]
    payload: dict = {}
    notes: list[str | None] = []
    if line is not None:
        code = _resolve_line(line, routes["data"])
        chosen = [row for row in routes["data"] if row["line_code"] == code] if code else []
        if not chosen:
            return compose([routes], None, note=f"找不到輕鐵路線：{line}")
        payload["lines"] = _group_lines(chosen)
    if origin or destination:
        if not origin or not destination:
            return compose([routes], None, note="車費要同時給起點同終點。")
        origin_ids = _match_ids(origin, routes["data"])
        dest_ids = _match_ids(destination, routes["data"])
        if not origin_ids or not dest_ids:
            missing = origin if not origin_ids else destination
            return compose([routes], None, note=_missing(missing))
        fares = mtr_core.light_rail_fares()
        sources.append(fares)
        pairs, missing, found = _fare_pairs(
            origin_ids, dest_ids, routes["data"], fares["data"], LR_FARE_COLUMNS
        )
        payload["pairs"] = pairs
        notes.append(None if found else "輕鐵車費檔沒有這一對車站。")
        notes.append(f"車費檔沒有這些欄：{', '.join(missing)}。" if missing else None)
        if len(origin_ids) > 1 or len(dest_ids) > 1:
            notes.append("這個名稱對應多於一個車站，以下是每一對的車費。")
    return compose(sources, payload, note=_join_notes(*notes))


def _match_routes(query: str, routes: list[dict]) -> list[dict]:
    folded = query.strip().casefold()
    exact = [row for row in routes if row["route_id"].casefold() == folded]
    if exact:
        return exact
    return [
        row
        for row in routes
        if row["name_zh"] == query.strip() or row["name_en"].casefold() == folded
    ]


def mtr_bus(route: str) -> dict:
    """港鐵巴士的停站順序、以路線計的車費，以及各站下一班。

    靜態資料用 `bus_routes`、`bus_stops`、`bus_fares`。到站時間用
    `bus_schedule`，每個路線只查一次。車費不是分段車費。
    預定班次同實時位置分開保留。

    用法：`mtr_bus("K52")`。
    市民會問：K52 停哪、車費幾多、這一站下一班幾時到？
    """
    routes = mtr_core.bus_routes()
    matched = _match_routes(route, routes["data"])
    if not matched:
        return compose([routes], None, note=f"找不到港鐵巴士路線：{route}")
    route_ids = list(dict.fromkeys(row["route_id"] for row in matched))
    if len(route_ids) > 1:
        return compose(
            [routes],
            {
                "matches": [
                    {
                        "route_id": row["route_id"],
                        "name_zh": row["name_zh"],
                        "name_en": row["name_en"],
                    }
                    for row in matched
                ]
            },
            note="這個名稱對應多於一條路線。",
        )
    route_id = route_ids[0]
    variants = [row for row in routes["data"] if row["route_id"] == route_id]
    stops = mtr_core.bus_stops()
    fares = mtr_core.bus_fares()
    schedule = mtr_core.bus_schedule(route_id)
    mine = [row for row in stops["data"] if row["route_id"] == route_id]
    mine.sort(key=lambda row: (row["direction"], row["sequence"]))
    unique_fares: list[dict] = []
    for row in fares["data"]:
        if row["route_id"] == route_id and row["fares"] not in unique_fares:
            unique_fares.append(row["fares"])
    note = None
    if not unique_fares:
        fare = None
        note = "車費檔沒有這條路線。"
    elif len(unique_fares) == 1:
        fare = unique_fares[0]
    else:
        fare = unique_fares
        note = "這條路線有多於一套車費。"
    return compose(
        [routes, stops, fares, schedule],
        {
            "route": {
                "route_id": route_id,
                "name_zh": variants[0]["name_zh"],
                "name_en": variants[0]["name_en"],
                "names": [
                    {"name_zh": row["name_zh"], "name_en": row["name_en"]} for row in variants
                ],
                "circular": variants[0]["circular"],
            },
            "stops": mine,
            "fare": fare,
            "eta": schedule["data"],
        },
        note=note,
    )
