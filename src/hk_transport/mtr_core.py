"""One function per MTR open-data resource.

Static functions return the whole table. Live functions pass the API's own
parameters through. Nothing here resolves a Chinese place name or joins two files.
"""

from __future__ import annotations

import csv
import io
from urllib.parse import urlencode

import requests

from hk_transport._http import _fresh, fetch_text
from hk_transport._result import MtrError, as_hkt, envelope, now_hkt

STATIC_DATASET = "mtr-data-routes-fares-barrier-free-facilities"
_OPEN = "https://opendata.mtr.com.hk/data/"
LINES_URL = _OPEN + "mtr_lines_and_stations.csv"
DOMESTIC_FARES_URL = _OPEN + "mtr_lines_fares.csv"
AEL_FARES_URL = _OPEN + "airport_express_fares.csv"
BARRIER_CATEGORIES_URL = _OPEN + "barrier_free_facility_category.csv"
BARRIER_FACILITIES_URL = _OPEN + "barrier_free_facilities.csv"
LR_ROUTES_URL = _OPEN + "light_rail_routes_and_stops.csv"
LR_FARES_URL = _OPEN + "light_rail_fares.csv"
BUS_ROUTES_URL = _OPEN + "mtr_bus_routes.csv"
BUS_STOPS_URL = _OPEN + "mtr_bus_stops.csv"
BUS_FARES_URL = _OPEN + "mtr_bus_fares.csv"

NEXT_DATASET = "mtr-data2-nexttrain-data"
NEXT_URL = "https://rt.data.gov.hk/v1/transport/mtr/getSchedule.php"
LR_NEXT_DATASET = "mtr-lrnt_data-light-rail-nexttrain-data"
LR_NEXT_URL = "https://rt.data.gov.hk/v1/transport/mtr/lrt/getSchedule"
BUS_DATASET = "mtr-mtr_bus-mtr-bus-eta-data"
BUS_URL = "https://rt.data.gov.hk/v1/transport/mtr/bus/getSchedule"

# url -> (retrieved_at, records). Disk freshness is checked again on a hit.
_memory: dict[str, tuple[str, list]] = {}


def clear_cache() -> None:
    """Drop the in-process table cache. The `.cache/` files stay on disk."""
    _memory.clear()


def norm_id(value: str | None) -> str:
    text = (value or "").strip()
    if not text:
        return ""
    try:
        number = float(text)
    except ValueError:
        return text
    if number.is_integer():
        return str(int(number))
    return text


# A cell holding only a dash is the publisher saying "no value", not a value.
_NO_VALUE = {"-", "—", "–"}


def _blank(value: str | None) -> str | None:
    if value is None:
        return None
    text = value.strip()
    if text in _NO_VALUE:
        return None
    return text or None


def _number(value: str | None) -> float | None:
    text = _blank(value)
    if text is None:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _flag(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "y", "true"}


def _rows(text: str) -> list[dict[str, str]]:
    return list(csv.DictReader(io.StringIO(text)))


def _parse_stops(text: str, *, code_key: str, id_key: str) -> list[dict]:
    records = []
    for row in _rows(text):
        line_code = _blank(row.get("Line Code"))
        if not line_code:
            continue
        records.append(
            {
                "line_code": line_code,
                "direction": _blank(row.get("Direction")) or "",
                "code": _blank(row.get(code_key)) or "",
                "id": norm_id(row.get(id_key)),
                "name_zh": _blank(row.get("Chinese Name")) or "",
                "name_en": _blank(row.get("English Name")) or "",
                "sequence": int(float(row["Sequence"])),
            }
        )
    return records


def _parse_lines(text: str) -> list[dict]:
    return _parse_stops(text, code_key="Station Code", id_key="Station ID")


def _parse_lr_routes(text: str) -> list[dict]:
    return _parse_stops(text, code_key="Stop Code", id_key="Stop ID")


def _parse_fare_table(
    text: str,
    *,
    from_id: str,
    to_id: str,
    from_name: str | None,
    to_name: str | None,
) -> list[dict]:
    skip = {from_id, to_id, from_name, to_name}
    records = []
    for row in _rows(text):
        origin = norm_id(row.get(from_id))
        dest = norm_id(row.get(to_id))
        if not origin or not dest:
            continue
        fares = {}
        for key, value in row.items():
            if key is None or key in skip:
                continue
            fares[key] = _blank(value)
        records.append(
            {
                "from_id": origin,
                "to_id": dest,
                "from_name": _blank(row.get(from_name)) if from_name else None,
                "to_name": _blank(row.get(to_name)) if to_name else None,
                "fares": fares,
            }
        )
    return records


def _parse_categories(text: str) -> list[dict]:
    records = []
    for row in _rows(text):
        key = _blank(row.get("Item_Code"))
        if not key:
            continue
        records.append(
            {
                "key": key,
                "category_zh": _blank(row.get("Category_Zh")),
                "category_en": _blank(row.get("Category_En")),
                "name_zh": _blank(row.get("Facility_Zh")),
                "name_en": _blank(row.get("Facility_En")),
            }
        )
    return records


def _parse_facilities(text: str) -> list[dict]:
    records = []
    for row in _rows(text):
        station_id = norm_id(row.get("Station_No"))
        key = _blank(row.get("Key"))
        if not station_id or not key:
            continue
        records.append(
            {
                "station_id": station_id,
                "key": key,
                "present": (row.get("Value") or "").strip().upper() == "Y",
                "exit_zh": _blank(row.get("AJTextZh")),
                "exit_en": _blank(row.get("AJTextEn")),
                "coordinate": _blank(row.get("Exit_Coordinate_X_Y")),
            }
        )
    return records


def _parse_bus_routes(text: str) -> list[dict]:
    records = []
    for row in _rows(text):
        route_id = _blank(row.get("ROUTE_ID"))
        if not route_id:
            continue
        records.append(
            {
                "route_id": route_id,
                "name_zh": _blank(row.get("ROUTE_NAME_CHI")) or "",
                "name_en": _blank(row.get("ROUTE_NAME_ENG")) or "",
                "circular": _flag(row.get("IS_CIRCULAR")),
            }
        )
    return records


def _parse_bus_stops(text: str) -> list[dict]:
    records = []
    for row in _rows(text):
        route_id = _blank(row.get("ROUTE_ID"))
        if not route_id:
            continue
        records.append(
            {
                "route_id": route_id,
                "direction": _blank(row.get("DIRECTION")) or "",
                "sequence": int(float(row["STATION_SEQNO"])),
                "id": norm_id(row.get("STATION_ID")),
                "name_zh": _blank(row.get("STATION_NAME_CHI")) or "",
                "name_en": _blank(row.get("STATION_NAME_ENG")) or "",
                "latitude": _number(row.get("STATION_LATITUDE")),
                "longitude": _number(row.get("STATION_LONGITUDE")),
            }
        )
    return records


def _parse_bus_fares(text: str) -> list[dict]:
    records = []
    for row in _rows(text):
        route_id = _blank(row.get("ROUTE_ID"))
        if not route_id:
            continue
        fares = {}
        for key, value in row.items():
            if key is None or key in {"ROUTE_ID", "REFERENCE_ID"}:
                continue
            fares[key] = _blank(value)
        records.append({"route_id": route_id, "fares": fares})
    return records


def _table(url: str, parse) -> dict:
    cached = _memory.get(url)
    if cached is not None and _fresh(cached[0]):
        retrieved_at, records = cached
        return envelope(
            dataset_id=STATIC_DATASET,
            endpoint=url,
            retrieved_at=retrieved_at,
            data_at=None,
            update_frequency="monthly",
            data=records,
        )
    text, retrieved_at = fetch_text(url, dataset_id=STATIC_DATASET)
    try:
        records = parse(text)
    except (KeyError, ValueError) as exc:
        raise MtrError(str(exc), dataset_id=STATIC_DATASET, endpoint=url) from exc
    _memory[url] = (retrieved_at, records)
    return envelope(
        dataset_id=STATIC_DATASET,
        endpoint=url,
        retrieved_at=retrieved_at,
        data_at=None,
        update_frequency="monthly",
        data=records,
    )


def lines_and_stations() -> dict:
    """Heavy-rail lines and stations, including Airport Express and Disneyland.

    Dataset `mtr-data-routes-fares-barrier-free-facilities`, endpoint
    `https://opendata.mtr.com.hk/data/mtr_lines_and_stations.csv`.
    Answers: which stations a line has, and which lines serve a station.
    """
    return _table(LINES_URL, _parse_lines)


def domestic_fares() -> dict:
    """Station-to-station heavy-rail fares. Station names in this file are English.

    Dataset `mtr-data-routes-fares-barrier-free-facilities`, endpoint
    `https://opendata.mtr.com.hk/data/mtr_lines_fares.csv`.
    Answers: what one adult, child, student, elderly, JoyYou, or PWD trip costs.
    """
    return _table(
        DOMESTIC_FARES_URL,
        lambda text: _parse_fare_table(
            text,
            from_id="SRC_STATION_ID",
            to_id="DEST_STATION_ID",
            from_name="SRC_STATION_NAME",
            to_name="DEST_STATION_NAME",
        ),
    )


def airport_express_fares() -> dict:
    """Airport Express fares. Adult and child columns only.

    Dataset `mtr-data-routes-fares-barrier-free-facilities`, endpoint
    `https://opendata.mtr.com.hk/data/airport_express_fares.csv`.
    Answers: what Hong Kong, Kowloon, or Tsing Yi to the Airport costs.
    """
    return _table(
        AEL_FARES_URL,
        lambda text: _parse_fare_table(
            text,
            from_id="ST_FROM_ID",
            to_id="ST_TO_ID",
            from_name="ST_FROM",
            to_name="ST_TO",
        ),
    )


def barrier_free_categories() -> dict:
    """Names for the facility keys used in `barrier_free_facilities`.

    Dataset `mtr-data-routes-fares-barrier-free-facilities`, endpoint
    `https://opendata.mtr.com.hk/data/barrier_free_facility_category.csv`.
    Answers: what a facility key means in Chinese and English.
    """
    return _table(BARRIER_CATEGORIES_URL, _parse_categories)


def barrier_free_facilities() -> dict:
    """Per-station barrier-free flags. `present` is true only when the file says Y.

    Dataset `mtr-data-routes-fares-barrier-free-facilities`, endpoint
    `https://opendata.mtr.com.hk/data/barrier_free_facilities.csv`.
    Answers: which facilities a station has, and at which exit. The exit
    coordinate column in this file is usually empty.
    """
    return _table(BARRIER_FACILITIES_URL, _parse_facilities)


def light_rail_routes() -> dict:
    """Light-rail routes and stops, one direction at a time.

    Dataset `mtr-data-routes-fares-barrier-free-facilities`, endpoint
    `https://opendata.mtr.com.hk/data/light_rail_routes_and_stops.csv`.
    Answers: which stops a Light Rail route calls at, in order.
    """
    return _table(LR_ROUTES_URL, _parse_lr_routes)


def light_rail_fares() -> dict:
    """Light-rail station-to-station fares. This file has ids and no station names.

    Dataset `mtr-data-routes-fares-barrier-free-facilities`, endpoint
    `https://opendata.mtr.com.hk/data/light_rail_fares.csv`.
    Answers: what one Light Rail trip between two stops costs.
    """
    return _table(
        LR_FARES_URL,
        lambda text: _parse_fare_table(
            text,
            from_id="from_station_id",
            to_id="to_station_id",
            from_name=None,
            to_name=None,
        ),
    )


def bus_routes() -> dict:
    """MTR bus and feeder-bus routes.

    Dataset `mtr-data-routes-fares-barrier-free-facilities`, endpoint
    `https://opendata.mtr.com.hk/data/mtr_bus_routes.csv`.
    Answers: which feeder routes exist, and their Chinese and English names.
    """
    return _table(BUS_ROUTES_URL, _parse_bus_routes)


def bus_stops() -> dict:
    """Stops on those routes, with coordinates.

    Dataset `mtr-data-routes-fares-barrier-free-facilities`, endpoint
    `https://opendata.mtr.com.hk/data/mtr_bus_stops.csv`.
    Answers: which stops a feeder route calls at, in order, and where they are.
    """
    return _table(BUS_STOPS_URL, _parse_bus_stops)


def bus_fares() -> dict:
    """One fare row per route, not per stop.

    Dataset `mtr-data-routes-fares-barrier-free-facilities`, endpoint
    `https://opendata.mtr.com.hk/data/mtr_bus_fares.csv`.
    Answers: what a feeder-bus trip costs. The fare is per route.
    """
    return _table(BUS_FARES_URL, _parse_bus_fares)


def _live(url: str, *, dataset_id: str, method: str = "GET", body: dict | None = None) -> tuple[dict, str]:
    try:
        if method == "POST":
            response = requests.post(url, json=body, timeout=20)
        else:
            response = requests.get(url, timeout=20)
        response.raise_for_status()
        payload = response.json()
    except requests.RequestException as exc:
        raise MtrError(str(exc), dataset_id=dataset_id, endpoint=url) from exc
    except ValueError as exc:
        raise MtrError(str(exc), dataset_id=dataset_id, endpoint=url) from exc
    if not isinstance(payload, dict):
        raise MtrError("回應不是 JSON 物件", dataset_id=dataset_id, endpoint=url)
    return payload, now_hkt()


def _train(row: dict) -> dict:
    return {
        "seq": _blank(row.get("seq")),
        "dest": _blank(row.get("dest")),
        "platform": _blank(row.get("plat")),
        "time": _blank(row.get("time")),
        "ttnt": _blank(row.get("ttnt")),
        "valid": _blank(row.get("valid")),
    }


def next_train(line: str, station: str) -> dict:
    """Next heavy-rail trains. `line` and `station` are API codes such as ISL and ADM.

    Airport Express and the Disneyland Resort line use this same call.
    Provides the next four trains per direction, plus status, message, and any
    special-arrangement URL. Dataset `mtr-data2-nexttrain-data`.
    """
    query = urlencode({"line": line, "sta": station, "lang": "tc"})
    endpoint = f"{NEXT_URL}?{query}"
    payload, retrieved_at = _live(endpoint, dataset_id=NEXT_DATASET)
    block = payload.get("data") or {}
    entry = block.get(f"{line}-{station}") if isinstance(block, dict) else None
    if not isinstance(entry, dict):
        entry = {}
    directions = []
    for name in ("UP", "DOWN"):
        trains = entry.get(name) or []
        directions.append(
            {
                "direction": name,
                "trains": [_train(row) for row in trains if isinstance(row, dict)],
            }
        )
    return envelope(
        dataset_id=NEXT_DATASET,
        endpoint=endpoint,
        retrieved_at=retrieved_at,
        data_at=as_hkt(_blank(payload.get("curr_time")) or _blank(entry.get("curr_time"))),
        update_frequency="10s",
        data={
            "status": payload.get("status"),
            "message": _blank(payload.get("message")),
            "url": _blank(payload.get("url")),
            "isdelay": _blank(payload.get("isdelay")),
            "curr_time": _blank(payload.get("curr_time")),
            "sys_time": _blank(payload.get("sys_time")),
            "directions": directions,
        },
    )


def light_rail_next_train(station_id: str, with_special: int = 1) -> dict:
    """Next light-rail trains for one stop id. Dataset `mtr-lrnt_data-light-rail-nexttrain-data`.

    `with_special=1` asks the API to include special routes. The path is
    `/v1/transport/mtr/lrt/getSchedule`.
    """
    query = urlencode({"station_id": station_id, "with_special": str(with_special)})
    endpoint = f"{LR_NEXT_URL}?{query}"
    payload, retrieved_at = _live(endpoint, dataset_id=LR_NEXT_DATASET)
    platforms = []
    for platform in payload.get("platform_list") or []:
        if not isinstance(platform, dict):
            continue
        trains = []
        for row in platform.get("route_list") or []:
            if not isinstance(row, dict):
                continue
            trains.append(
                {
                    "route_no": _blank(row.get("route_no")),
                    "dest_zh": _blank(row.get("dest_ch")),
                    "dest_en": _blank(row.get("dest_en")),
                    "time_zh": _blank(row.get("time_ch")),
                    "time_en": _blank(row.get("time_en")),
                    "special": row.get("special") in {1, "1", True},
                    "arrival_departure": _blank(row.get("arrival_departure")),
                    "train_length": row.get("train_length"),
                }
            )
        platforms.append({"platform_id": platform.get("platform_id"), "trains": trains})
    return envelope(
        dataset_id=LR_NEXT_DATASET,
        endpoint=endpoint,
        retrieved_at=retrieved_at,
        data_at=as_hkt(_blank(payload.get("system_time"))),
        update_frequency="10s",
        data={
            "status": payload.get("status"),
            "system_time": _blank(payload.get("system_time")),
            "platforms": platforms,
        },
    )


def _bus_trip(row: dict) -> dict:
    location = row.get("busLocation") if isinstance(row.get("busLocation"), dict) else {}
    return {
        "arrival_time_text": _blank(row.get("arrivalTimeText")),
        "departure_time_text": _blank(row.get("departureTimeText")),
        "is_scheduled": _flag(str(row.get("isScheduled"))),
        "is_delayed": _flag(str(row.get("isDelayed"))),
        "location": {
            "latitude": location.get("latitude"),
            "longitude": location.get("longitude"),
        },
        "line_ref": _blank(row.get("lineRef")),
        "bus_id": _blank(row.get("busId")),
    }


def bus_schedule(route_name: str, language: str = "zh") -> dict:
    """Live MTR-bus ETA for one route. POST body is `language` and `routeName`.

    Dataset `mtr-mtr_bus-mtr-bus-eta-data`. Scheduled trips stay marked
    `is_scheduled`; they are not rewritten as live positions.
    """
    payload, retrieved_at = _live(
        BUS_URL,
        dataset_id=BUS_DATASET,
        method="POST",
        body={"language": language, "routeName": route_name},
    )
    stops = []
    for stop in payload.get("busStop") or []:
        if not isinstance(stop, dict):
            continue
        stops.append(
            {
                "stop_id": _blank(stop.get("busStopId")),
                "suspended": _flag(str(stop.get("isSuspended"))),
                "buses": [
                    _bus_trip(row)
                    for row in (stop.get("bus") or [])
                    if isinstance(row, dict)
                ],
            }
        )
    return envelope(
        dataset_id=BUS_DATASET,
        endpoint=BUS_URL,
        retrieved_at=retrieved_at,
        data_at=as_hkt(_blank(payload.get("routeStatusTime"))),
        update_frequency="10s",
        data={
            "route_name": _blank(payload.get("routeName")) or route_name,
            "status": payload.get("status"),
            "route_status": _blank(payload.get("routeStatus")),
            "route_status_remark_title": _blank(payload.get("routeStatusRemarkTitle")),
            "route_status_remark": _blank(payload.get("routeStatusRemarkContent")),
            "stops": stops,
        },
    )
