"""Citizen-facing MTR tools.

Each function calls `hk_transport.mtr_core` and does not fetch HTTP itself.
A result that the published data cannot support has `data: null` and a note.

These tools do not answer: first or last train, which exit serves a building,
crowding, or the high-speed rail. `mtr_ride_estimate` estimates in-vehicle
minutes from live arrivals and leaves the total empty when a link does not agree.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta

from hk_transport import _graph, mtr_core
from hk_transport._result import NO_ALERT, compose

ALERT_CHECK_NEWS = (
    "這一站這一線的回應有特別安排。全港特別交通消息要再查 special_traffic_news。"
)
UNKNOWN_SERVICE = "這次回應沒有車務狀態，不能說有沒有特別安排。"
STATION_AMBIGUOUS = "這個名稱對應多於一個車站。"
PAIRS_AMBIGUOUS = "這個名稱對應多於一個車站，以下是每一對的車費。"
JOURNEY_AMBIGUOUS = "這個名稱對應多於一個車站，沒有選其中一條路徑。"
LINE_STATION_AMBIGUOUS = "這個站名在這條線上對應多於一個車站代碼。"
LIGHT_RAIL_STOP_AMBIGUOUS = "這個名稱對應多於一個輕鐵站，沒有查下一班。"
ROUTE_AMBIGUOUS = "這個名稱對應多於一條路線。"

from hk_transport.mtr_core import LINE_NAMES as LINES, line_names as _line_names

# One physical interchange, three station ids: AEL Hong Kong (44), TCL Hong
# Kong (39), and Central (1). The key is deliberately not a station id, so a
# transfer point cannot be mistaken for a station.
INTERCHANGES = {"central-hong-kong": frozenset({"1", "39", "44"})}

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


def _matches(row: dict, query: str, id_key: str, code_key: str | None) -> bool:
    """One row answers to an id, a code, or a name written in either language."""
    folded = query.casefold()
    row_id = row.get(id_key) or ""
    if row_id == mtr_core.norm_id(query) or row_id.casefold() == folded:
        return True
    if code_key is not None and (row.get(code_key) or "").casefold() == folded:
        return True
    return row["name_zh"] == query or (row.get("name_en") or "").casefold() == folded


def _match_rows(
    query: str,
    rows: list[dict],
    id_key: str = "id",
    code_key: str | None = "code",
) -> list[dict]:
    """Rows matching the query, preferring an exact id over a name."""
    text = query.strip()
    exact = [
        row
        for row in rows
        if (row.get(id_key) or "") == mtr_core.norm_id(text)
        or (row.get(id_key) or "").casefold() == text.casefold()
    ]
    if exact:
        return exact
    return [row for row in rows if _matches(row, text, id_key, code_key)]


def _match_ids(query: str, rows: list[dict]) -> list[str]:
    found: list[str] = []
    seen: set[str] = set()
    for row in _match_rows(query, rows):
        if row["id"] in seen:
            continue
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
    return len(ids) > 1 and not _all_one_interchange(ids)


def _interchange_of(station_id: str) -> str | None:
    for key, ids in INTERCHANGES.items():
        if station_id in ids:
            return key
    return None


def _all_one_interchange(ids: list[str]) -> bool:
    """True when every matched id is another name for the same interchange."""
    keys = {_interchange_of(station_id) for station_id in ids}
    return len(keys) == 1 and None not in keys


def _project(fares: dict, columns: tuple[str, ...]) -> tuple[dict, list[str]]:
    missing = [column for column in columns if column not in fares]
    projected = {column: fares.get(column) for column in columns}
    for key, value in fares.items():
        if key not in projected:
            projected[key] = value
    return projected, missing


def _join_notes(*parts: str | None) -> str | None:
    kept = [part for part in parts if part]
    if not kept:
        return None
    return " ".join(kept)


def _matches_result(source: dict, matches: list[dict], note: str) -> dict:
    """A result that names the candidates instead of choosing one."""
    return compose([source], {"matches": matches}, note=note)


def _fare_note_rows(found: bool, missing: list[str], absent: str) -> str | None:
    """The two notes a fare table can produce, written once for every table."""
    return _join_notes(
        None if found else absent,
        f"車費檔沒有這些欄：{', '.join(missing)}。" if missing else None,
    )


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
        note = STATION_AMBIGUOUS if len(ids) > 1 else None
        return compose([source], {"stations": stations}, note=note)
    if not chosen:
        return compose([source], None, note=f"找不到路線：{line}")
    return compose([source], {"lines": _group_lines(chosen)})


def _transfer_key(station_id: str) -> str:
    return _interchange_of(station_id) or station_id


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

    edges: list[tuple[int, int, str]] = []
    for left, targets in rides.items():
        for right in targets:
            edges.append((left, right, _graph.RIDE))
    for left, targets in transfers.items():
        for right in targets:
            edges.append((left, right, _graph.TRANSFER))
    found = _graph.journeys(len(platforms), edges, starts, ends, k=1)
    if not found:
        return None
    route = found[0]
    chain = list(route.nodes)
    kinds = list(route.kinds)

    legs = []
    walked = []
    index = 0
    while index < len(chain) - 1:
        kind = kinds[index]
        if kind == _graph.TRANSFER:
            walked.append(
                {
                    "from": _view(platforms[chain[index]]),
                    "to": _view(platforms[chain[index + 1]]),
                }
            )
            index += 1
            continue
        end = index
        while end + 1 < len(chain) and kinds[end] == _graph.RIDE:
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
    transfer_count, ride_count = route.transfers, route.rides
    return {
        "transfers": transfer_count,
        "ride_count": ride_count,
        "legs": legs,
        "interchanges": walked,
    }


def _journey_query(origin: str, destination: str) -> tuple[dict, dict | None, str | None]:
    source = mtr_core.lines_and_stations()
    rows = source["data"]
    origin_ids = _match_ids(origin, rows)
    dest_ids = _match_ids(destination, rows)
    if not origin_ids or not dest_ids:
        missing = origin if not origin_ids else destination
        return source, None, _missing(missing)
    if _ambiguous(origin_ids) or _ambiguous(dest_ids):
        reps = _representatives(rows)
        return (
            source,
            {
                "origin_matches": [_view(reps[station_id]) for station_id in origin_ids],
                "destination_matches": [_view(reps[station_id]) for station_id in dest_ids],
            },
            JOURNEY_AMBIGUOUS,
        )
    reps = _representatives(rows)
    if set(origin_ids) & set(dest_ids):
        shared = next(iter(set(origin_ids) & set(dest_ids)))
        return (
            source,
            {
                "origin": _view(reps[shared]),
                "destination": _view(reps[shared]),
                "transfers": 0,
                "ride_count": 0,
                "legs": [],
                "interchanges": [],
            },
            "起點同終點是同一個站。",
        )
    path = _journey_path(rows, origin_ids, dest_ids)
    if path is None:
        return source, None, "這兩站在重鐵路網裡接不上。"
    return (
        source,
        {
            "origin": _view(reps[origin_ids[0]]),
            "destination": _view(reps[dest_ids[0]]),
            **path,
        },
        None,
    )


def mtr_journey(origin: str, destination: str) -> dict:
    """兩站之間的一條路徑：乘哪條線、在哪裡轉車、中間停哪些站。

    提供轉乘路徑。資料集 `mtr-data-routes-fares-barrier-free-facilities`，
    端點由 `lines_and_stations` 帶出。沒有行車分鐘。

    用法：`mtr_journey("柴灣", "荃灣")`。
    市民會問：由柴灣去荃灣，乘哪條線，在哪一站轉車？

    轉車以共用車站編號連接。機場快線香港站（44）、東涌線香港站（39）
    和中環站（1）可以互轉。搜尋先減少轉車次數，再減少停車站數。
    """
    source, data, note = _journey_query(origin, destination)
    return compose([source], data, note=note)


_LINK_TOLERANCE = timedelta(seconds=30)


def _parse_train_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None


def _direction_terminus(rows: list[dict], line_code: str, direction: str) -> str | None:
    stops = [
        row for row in rows if row["line_code"] == line_code and row["direction"] == direction
    ]
    if not stops:
        return None
    stops.sort(key=lambda row: row["sequence"])
    return stops[-1]["code"]


def _arrival_times(live: dict, dest_code: str) -> dict[str, list[datetime]]:
    """Arrival times toward one terminus, kept apart by direction.

    The two directions are never pooled: a train going the other way cannot
    show how long this direction takes.
    """
    grouped: dict[str, list[datetime]] = {}
    for direction in live["data"]["directions"]:
        times = []
        for train in direction["trains"]:
            if train.get("dest") != dest_code:
                continue
            if train.get("valid") not in (None, "", "Y", "y"):
                continue
            parsed = _parse_train_time(train.get("time"))
            if parsed is not None:
                times.append(parsed)
        grouped[direction["direction"]] = sorted(set(times))
    return grouped


def _direction_minutes(starts: list[datetime], arrivals: list[datetime]) -> int | None:
    """The minute most trains agree on within one direction, or None.

    Trains are not identified across stations by this API, so a minute is only
    accepted when at least two trains support it and no other minute has as
    many. That is the whole guarantee; it is not a timetable.
    """
    if not starts or not arrivals:
        return None
    span = int((max(arrivals) - min(starts)).total_seconds() // 60)
    scores: list[tuple[int, int]] = []
    for offset in range(span + 1):
        gap = timedelta(minutes=offset)
        hits = sum(
            any(abs(item - (start + gap)) <= _LINK_TOLERANCE for item in arrivals)
            for start in starts
        )
        scores.append((hits, offset))
    positive = [item for item in scores if item[1] > 0]
    if not positive:
        return None
    best_hits, best_offset = max(positive, key=lambda item: (item[0], -item[1]))
    runner_up = max(
        (hits for hits, offset in scores if offset != best_offset), default=0
    )
    if best_hits >= 2 and best_hits > runner_up:
        return best_offset
    return None


def _agreed_minutes(
    upstream: dict[str, list[datetime]], downstream: dict[str, list[datetime]]
) -> int | None:
    """Minutes from one station to the next, judged one direction at a time.

    A train going the other way is never evidence for this direction, and a
    zero-minute match wins no argument: two station clocks can differ by a few
    seconds, so zero is counted as a competitor but never returned.
    """
    for direction, starts in upstream.items():
        minute = _direction_minutes(starts, downstream.get(direction) or [])
        if minute is not None:
            return minute
    return None


def mtr_ride_estimate(origin: str, destination: str) -> dict:
    """用實時到站時間估算兩站之間的車上分鐘。

    路徑來自 `lines_and_stations`（`mtr-data-routes-fares-barrier-free-facilities`）。
    每一段呼叫 `next_train`（`mtr-data2-nexttrain-data`），只看開往該方向
    終點站的班次。同一班車在下一站的到站時間減去這一站的到站時間，就是這一段。
    至少兩班車同意同一個分鐘，而且沒有另一個分鐘同樣多人同意，才採用。
    任何一段對不齊，全程分鐘留空。

    用法：`mtr_ride_estimate("長沙灣", "海洋公園")`。
    市民會問：全程大約幾耐？

    這不是港鐵公布的行車時間。同一站兩班車相減是班距，不用來估算。
    停站時間已經在兩站的差距裡，不會每站再加 30 秒。不包括轉車步行和等車。
    """
    source, data, note = _journey_query(origin, destination)
    if not data or "legs" not in data:
        return compose([source], data, note=note)
    if not data["legs"]:
        return compose([source], {**data, "minutes": 0, "links": []}, note=note)

    rows = source["data"]
    lives: dict[tuple[str, str], dict] = {}
    links = []
    for leg in data["legs"]:
        terminus = _direction_terminus(rows, leg["line_code"], leg["direction"])
        stations = leg["stations"]
        boards = []
        for station in stations:
            key = (leg["line_code"], station["code"])
            if key not in lives:
                lives[key] = mtr_core.next_train(leg["line_code"], station["code"])
            boards.append(_arrival_times(lives[key], terminus or ""))
        for before, after, upstream, downstream in zip(
            stations, stations[1:], boards, boards[1:]
        ):
            links.append(
                {
                    "line_code": leg["line_code"],
                    "line_zh": leg["line_zh"],
                    "line_en": leg["line_en"],
                    "from": before,
                    "to": after,
                    "minutes": _agreed_minutes(upstream, downstream),
                }
            )
    unknown = [f"{link['from']['name_zh']}到{link['to']['name_zh']}" for link in links if link["minutes"] is None]
    minutes = None if unknown else sum(link["minutes"] for link in links)
    estimate_note = (
        f"有路段的班次對不齊，沒有加總全程。對不齊的是：{'、'.join(unknown)}。"
        if unknown
        else "這是由實時到站時間估算的車上分鐘，不是港鐵公布的行車時間。"
    )
    return compose(
        [source, *lives.values()],
        {**data, "minutes": minutes, "links": links},
        note=_join_notes(
            note,
            estimate_note,
            "不包括轉車步行和等車。",
        ),
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
            if fare is None:
                # No row at all: the pair is absent. Do not claim its columns are absent.
                projected = None
            else:
                projected, absent = _project(fare["fares"], columns)
                missing.extend(column for column in absent if column not in missing)
                any_row = True
            pairs.append(
                {
                    "from": _view(reps[origin_id]),
                    "to": _view(reps[dest_id]),
                    "fares": projected,
                }
            )
    return pairs, missing, any_row


def mtr_fare(origin: str, destination: str) -> dict:
    """兩個重鐵站之間的車費。車費跟路徑無關。

    提供八達通同單程票各欄。資料集
    `mtr-data-routes-fares-barrier-free-facilities`，端點由 `lines_and_stations`
    同 `domestic_fares` 帶出。中文站名經 `lines_and_stations` 對上車站編號，
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
        PAIRS_AMBIGUOUS if len(origin_ids) > 1 or len(dest_ids) > 1 else None,
        _fare_note_rows(found, missing, "車費檔沒有這一對車站。"),
    )
    return compose([lines, fares], {"pairs": pairs}, note=note)


def _service_state(payload: dict) -> str:
    """`normal`, `alert`, or `unknown` from the API's own service fields.

    A missing status is not evidence of normal service, so it is `unknown`
    unless another field already reports a problem.
    """
    message = (payload.get("message") or "").casefold()
    status = payload.get("status")
    delayed = (payload.get("isdelay") or "").upper() == "Y"
    if delayed or payload.get("url") or message not in {"", "successful", "success"}:
        return "alert"
    if status in (1, "1"):
        return "normal"
    if status is None:
        return "unknown"
    return "alert"


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
    不會寫成全線正常。有警報時，note 提示再查 `special_traffic_news`。
    這裡不代為下載那份全港消息。
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
        return _matches_result(
            lines,
            [_view(reps[row["id"]]) for row in on_line],
            LINE_STATION_AMBIGUOUS,
        )
    live = mtr_core.next_train(line_code, codes[0])
    directions = []
    for direction in live["data"]["directions"]:
        directions.append(
            {
                "direction": direction["direction"],
                "trains": [
                    {**train, "dest": _station_by_code(rows, train["dest"])}
                    for train in direction["trains"]
                ],
            }
        )
    zh, en = _line_names(line_code)
    state = _service_state(live["data"])
    alert = (
        {key: live["data"][key] for key in ("status", "message", "url", "isdelay")}
        if state == "alert"
        else None
    )
    if state == "alert":
        note = ALERT_CHECK_NEWS
    elif state == "normal":
        note = NO_ALERT
    else:
        note = UNKNOWN_SERVICE
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
        note=note,
    )


def mtr_airport_express_fare(origin: str, destination: str) -> dict:
    """機場快線成人同小童車費。下一班用 `mtr_next_train`。

    資料集 `mtr-data-routes-fares-barrier-free-facilities`，端點由
    `airport_express_fares` 帶出。只用這一張表。不會套用重鐵的長者、學生或樂悠咭車費。

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
        PAIRS_AMBIGUOUS if len(origin_ids) > 1 or len(dest_ids) > 1 else None,
        _fare_note_rows(found, missing, "機場快線車費檔沒有這一對車站。"),
        "機場快線車費檔只有成人同小童。",
    )
    return compose([lines, fares], {"pairs": pairs}, note=note)


def mtr_barrier_free(station: str) -> dict:
    """一個站有哪些無障礙設施、在哪個出口。

    資料集 `mtr-data-routes-fares-barrier-free-facilities`，端點由
    `barrier_free_facilities` 同 `barrier_free_categories` 帶出。
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
    note = STATION_AMBIGUOUS if len(ids) > 1 else None
    return compose([lines, facilities, categories], {"stations": stations}, note=note)


def light_rail_next(station: str) -> dict:
    """輕鐵這一站即將開出的班次，包括特別班。

    站名經 `light_rail_routes` 對上 stop id，再呼叫 `light_rail_next_train`
    （`with_special=1`）。資料集 `mtr-lrnt_data-light-rail-nexttrain-data`，
    端點由 `light_rail_next_train` 帶出。數據時間用 API 的 `system_time`。

    用法：`light_rail_next("元朗")`。元朗的 stop id 是 600。
    市民會問：下一班是幾號、去哪、還有幾多分鐘？是不是特別班？
    """
    routes = mtr_core.light_rail_routes()
    ids = _match_ids(station, routes["data"])
    if not ids:
        return compose([routes], None, note=_missing(station))
    if len(ids) > 1:
        reps = _representatives(routes["data"])
        return _matches_result(
            routes,
            [_view(reps[station_id]) for station_id in ids],
            LIGHT_RAIL_STOP_AMBIGUOUS,
        )
    live = mtr_core.light_rail_next_train(ids[0])
    return compose(
        [routes, live],
        {
            "station": _view(_representatives(routes["data"])[ids[0]]),
            "status": live["data"].get("status"),
            "platforms": live["data"]["platforms"],
        },
    )


def _light_rail_lines(line: str, routes: dict) -> dict | None:
    """Stop order for one Light Rail route, or None when the route is unknown."""
    code = _resolve_line(line, routes["data"])
    chosen = [row for row in routes["data"] if row["line_code"] == code] if code else []
    if not chosen:
        return None
    return _group_lines(chosen)


def _light_rail_fares(
    origin_ids: list[str],
    dest_ids: list[str],
    routes: dict,
    fares: dict,
) -> tuple[list[dict], str | None]:
    """Fare pairs for two Light Rail stops, with their note."""
    pairs, missing, found = _fare_pairs(
        origin_ids, dest_ids, routes["data"], fares["data"], LR_FARE_COLUMNS
    )
    note = _join_notes(
        PAIRS_AMBIGUOUS if len(origin_ids) > 1 or len(dest_ids) > 1 else None,
        _fare_note_rows(found, missing, "輕鐵車費檔沒有這一對車站。"),
    )
    return pairs, note


def light_rail(
    line: str | None = None,
    origin: str | None = None,
    destination: str | None = None,
) -> dict:
    """輕鐵某線一個方向的車站順序，以及兩站之間的車費。

    資料集 `mtr-data-routes-fares-barrier-free-facilities`，端點由
    `light_rail_routes` 同 `light_rail_fares` 帶出。可以只問路線、
    只問車費，或兩個一起問。

    用法：`light_rail(line="610")`，`light_rail(origin="屯門", destination="元朗")`。
    市民會問：610 線停哪些站？由屯門去元朗幾多錢？
    """
    if line is None and not (origin and destination):
        return compose([], None, note="要給路線，或同時給起點同終點。")
    routes = mtr_core.light_rail_routes()
    sources = [routes]
    payload: dict = {}
    notes: list[str | None] = []
    if line is not None:
        lines = _light_rail_lines(line, routes)
        if lines is None:
            return compose([routes], None, note=f"找不到輕鐵路線：{line}")
        payload["lines"] = lines
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
        payload["pairs"], note = _light_rail_fares(origin_ids, dest_ids, routes, fares)
        notes.append(note)
    return compose(sources, payload, note=_join_notes(*notes))


def _match_routes(query: str, routes: list[dict]) -> list[dict]:
    """Bus routes answer to their route id or either name."""
    return _match_rows(query, routes, id_key="route_id", code_key=None)


def _route_fare(fare_rows: list[dict], route_id: str) -> tuple[dict | list[dict] | None, str | None]:
    """The fare set for one route, and a note when there is not exactly one.

    A bus fare belongs to the route, and the file may repeat the same set on
    more than one row; those rows are one fare. The work stays here because
    `mtr_core` returns whole tables and never filters.
    """
    sets: list[dict] = []
    for row in fare_rows:
        if row["route_id"] == route_id and row["fares"] not in sets:
            sets.append(row["fares"])
    if not sets:
        return None, "車費檔沒有這條路線。"
    if len(sets) == 1:
        return sets[0], None
    return sets, "這條路線有多於一套車費。"


def mtr_bus(route: str) -> dict:
    """港鐵巴士的停站順序、以路線計的車費，以及各站下一班。

    靜態資料集 `mtr-data-routes-fares-barrier-free-facilities`，端點由
    `bus_routes`、`bus_stops`、`bus_fares` 帶出；到站資料集
    `mtr-mtr_bus-mtr-bus-eta-data`，端點由 `bus_schedule` 帶出，每個路線只查一次。
    車費不是分段車費。預定班次同實時位置分開保留。

    用法：`mtr_bus("K52")`。
    市民會問：K52 停哪、車費幾多、這一站下一班幾時到？
    """
    routes = mtr_core.bus_routes()
    matched = _match_routes(route, routes["data"])
    if not matched:
        return compose([routes], None, note=f"找不到港鐵巴士路線：{route}")
    route_ids = list(dict.fromkeys(row["route_id"] for row in matched))
    if len(route_ids) > 1:
        return _matches_result(
            routes,
            [
                {
                    "route_id": row["route_id"],
                    "name_zh": row["name_zh"],
                    "name_en": row["name_en"],
                }
                for row in matched
            ],
            ROUTE_AMBIGUOUS,
        )
    route_id = route_ids[0]
    variants = [row for row in routes["data"] if row["route_id"] == route_id]
    stops = mtr_core.bus_stops()
    fares = mtr_core.bus_fares()
    schedule = mtr_core.bus_schedule(route_id)
    mine = [row for row in stops["data"] if row["route_id"] == route_id]
    mine.sort(key=lambda row: (row["direction"], row["sequence"]))
    fare, fare_note = _route_fare(fares["data"], route_id)
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
        note=fare_note,
    )
