"""Green minibus core: one dataset, one function.

Two sources, both from the Transport Department:

- Routes, fares and stop sequence: `hk-td-tis_3`, the 20 MB
  `JSON_GMB.json` feature collection. One feature per stop per route variant,
  so it carries route identity, fare, whole-route time, stop sequence and
  WGS84 coordinates in one file. Cached for 30 days.
- Real-time arrival: `hk-td-sm_7` at `https://data.etagmb.gov.hk`. Live, never
  cached.

The two share `route_id` and `stop_id` exactly, so nothing is joined by name.
`district` is part of route identity: a route code is unique only inside one
district, and 480 codes contain 87 that appear in more than one.

This module only reads and returns. It does not choose a route.
"""

from __future__ import annotations

import ijson
from ijson.common import JSONError

from hk_transport._http import cached_file, fetch_json
from hk_transport._result import MtrError, as_hkt, envelope
from hk_transport._values import blank, number

DATASET_STATIC = "hk-td-tis_23-routes-fares-geojson"
DATASET_ETA = "hk-td-sm_7-real-time-arrival-data-of-gmb"
STATIC_URL = "https://static.data.gov.hk/td/routes-fares-geojson/JSON_GMB.json"
ETA_BASE = "https://data.etagmb.gov.hk"

NOTE = (
    "路線同車費來自運輸署，成人全程價，唔係分段。"
    "journey_time_minutes 是整條線的公布全程時間，不是分段行車時間。"
    "路線號碼只在區域內唯一，同一個號碼可以出現在唔同區域。"
)

_memory: dict | None = None


def clear_cache() -> None:
    """Forget the parsed 20 MB table held in this process."""
    global _memory
    _memory = None


def _route_row(props: dict, geometry: dict | None) -> dict:
    return {
        "district": blank(props.get("district")),
        "route": blank(props.get("routeNameC")),
        "route_en": blank(props.get("routeNameE")),
        "route_id": props.get("routeId"),
        "route_seq": props.get("routeSeq"),
        "route_type": props.get("routeType"),
        "service_mode": blank(props.get("serviceMode")),
        "special_type": props.get("specialType"),
        "origin_zh": blank(props.get("locStartNameC")),
        "origin_en": blank(props.get("locStartNameE")),
        "dest_zh": blank(props.get("locEndNameC")),
        "dest_en": blank(props.get("locEndNameE")),
        "fare": number(props.get("fullFare")),
        "journey_time_minutes": number(props.get("journeyTime")),
    }


def _stop_row(props: dict, geometry: dict | None) -> dict:
    coords = (geometry or {}).get("coordinates") or [None, None]
    longitude = number(coords[0]) if len(coords) > 0 else None
    latitude = number(coords[1]) if len(coords) > 1 else None
    return {
        "district": blank(props.get("district")),
        "route": blank(props.get("routeNameC")),
        "route_id": props.get("routeId"),
        "route_seq": props.get("routeSeq"),
        "service_mode": blank(props.get("serviceMode")),
        "special_type": props.get("specialType"),
        "seq": props.get("stopSeq"),
        "stop": str(props.get("stopId")),
        "name_zh": blank(props.get("stopNameC")),
        "name_en": blank(props.get("stopNameE")),
        "latitude": latitude,
        "longitude": longitude,
        "pick_drop": props.get("stopPickDrop"),
        "fare": number(props.get("fullFare")),
        "journey_time_minutes": number(props.get("journeyTime")),
    }


def _load() -> dict:
    """Parse the 20 MB file once per process into route variants and stops."""
    global _memory
    if _memory is not None:
        return _memory
    path, retrieved_at = cached_file(STATIC_URL, dataset_id=DATASET_STATIC)
    routes: dict[tuple, dict] = {}
    stops: list[dict] = []
    updated = None
    try:
        with path.open("rb") as handle:
            if handle.read(3) != b"\xef\xbb\xbf":
                handle.seek(0)
            for feature in ijson.items(handle, "features.item"):
                props = feature.get("properties") or {}
                updated = updated or blank(props.get("lastUpdateDate"))
                stops.append(_stop_row(props, feature.get("geometry")))
                key = (
                    props.get("routeId"),
                    props.get("routeSeq"),
                    props.get("serviceMode"),
                    props.get("specialType"),
                )
                if key not in routes:
                    routes[key] = _route_row(props, feature.get("geometry"))
    except (OSError, ValueError, JSONError) as exc:
        raise MtrError(str(exc), dataset_id=DATASET_STATIC, endpoint=STATIC_URL) from exc
    _memory = {
        "routes": list(routes.values()),
        "stops": stops,
        "retrieved_at": retrieved_at,
        "data_at": as_hkt(updated),
    }
    return _memory


def gmb_routes() -> dict:
    """全部綠色專線小巴路線變體，連成人全程車費。

    資料集 `hk-td-tis_3`，端點 `JSON_GMB.json`，30 日快取。
    用法：`gmb_routes()`。
    市民會問：呢條線幾多錢？總站喺邊？係咪循環線？

    一個變體一列（route_id × route_seq × service_mode × special_type）。
    路線號碼只在區域內唯一，所以一定要連 `district` 講。
    """
    loaded = _load()
    return envelope(
        dataset_id=DATASET_STATIC,
        endpoint=STATIC_URL,
        retrieved_at=loaded["retrieved_at"],
        data_at=loaded["data_at"],
        update_frequency="biweekly",
        data=loaded["routes"],
        note=NOTE,
    )


def gmb_route_stops() -> dict:
    """全部綠色專線小巴的站序，一站一列，帶 WGS84 座標。

    資料集 `hk-td-tis_3`，端點 `JSON_GMB.json`，30 日快取。
    用法：`gmb_route_stops()`。
    市民會問：呢條線停邊啲站？順序係點？呢個站有邊幾條線？

    13,165 列。`seq` 是該變體內的次序，不是時間、不是距離。
    同一個 `stop_id` 在不同路線可以有不同名稱，但座標一樣。
    """
    loaded = _load()
    return envelope(
        dataset_id=DATASET_STATIC,
        endpoint=STATIC_URL,
        retrieved_at=loaded["retrieved_at"],
        data_at=loaded["data_at"],
        update_frequency="biweekly",
        data=loaded["stops"],
        note=NOTE + "同一個停車位置在不同路線可以有不同站名。",
    )


def gmb_stops() -> dict:
    """綠色專線小巴的停車位置，一個 stop_id 一列。

    由 `gmb_route_stops()` 去重而來，站名取第一條見到的路線的叫法。
    用法：`gmb_stops()`。
    市民會問：附近有邊個小巴站？

    約 4,800 個位置。名稱隨路線而變，唔可以當成唯一官方名稱。
    """
    loaded = _load()
    seen: dict[str, dict] = {}
    for row in loaded["stops"]:
        if row["latitude"] is None:
            continue
        if row["stop"] not in seen:
            seen[row["stop"]] = {
                "stop": row["stop"],
                "name_zh": row["name_zh"],
                "name_en": row["name_en"],
                "latitude": row["latitude"],
                "longitude": row["longitude"],
                "district": row["district"],
            }
    return envelope(
        dataset_id=DATASET_STATIC,
        endpoint=STATIC_URL,
        retrieved_at=loaded["retrieved_at"],
        data_at=loaded["data_at"],
        update_frequency="biweekly",
        data=list(seen.values()),
        note="同一個停車位置在不同路線可以有不同站名，這裡只保留第一個。",
    )


def gmb_stop(stop_id: str) -> dict:
    """一個小巴站的實時資料同座標。

    資料集 `hk-td-sm_7`，端點 `https://data.etagmb.gov.hk/stop/{stop_id}`。
    不快取。用法：`gmb_stop("20003337")`。
    市民會問：呢個站仲有冇車？
    """
    text = str(stop_id).strip()
    url = f"{ETA_BASE}/stop/{text}"
    payload, retrieved_at = fetch_json(url, dataset_id=DATASET_ETA, cache=False)
    row = (payload or {}).get("data") if isinstance(payload, dict) else None
    if not isinstance(row, dict):
        raise MtrError("小巴站不是預期的 JSON", dataset_id=DATASET_ETA, endpoint=url)
    coords = (row.get("coordinates") or {}).get("wgs84") or {}
    return envelope(
        dataset_id=DATASET_ETA,
        endpoint=url,
        retrieved_at=retrieved_at,
        data_at=as_hkt(row.get("data_timestamp")),
        update_frequency="realtime",
        data={
            "stop": text,
            "enabled": row.get("enabled"),
            "latitude": number(coords.get("latitude")),
            "longitude": number(coords.get("longitude")),
            "remark_zh": blank(row.get("remarks_tc")),
        },
        note="實時資料，不停站時 `enabled` 可能是 false。",
    )


def gmb_stop_eta(stop_id: str) -> dict:
    """一個小巴站所有路線的下一班。

    資料集 `hk-td-sm_7`，端點 `https://data.etagmb.gov.hk/eta/stop/{stop_id}`。
    不快取。用法：`gmb_stop_eta("20015409")`。
    市民會問：呢個站下一班幾時到？邊條線快啲有車？

    交還該站每條線的 `eta` 陣列，最多三班。冇車到的路線唔會出現。
    """
    text = str(stop_id).strip()
    url = f"{ETA_BASE}/eta/stop/{text}"
    payload, retrieved_at = fetch_json(url, dataset_id=DATASET_ETA, cache=False)
    rows = (payload or {}).get("data") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        raise MtrError("小巴到站不是預期的 JSON", dataset_id=DATASET_ETA, endpoint=url)
    return envelope(
        dataset_id=DATASET_ETA,
        endpoint=url,
        retrieved_at=retrieved_at,
        data_at=None,
        update_frequency="every minute",
        data=[
            {
                "route_id": row.get("route_id"),
                "route_seq": row.get("route_seq"),
                "stop_seq": row.get("stop_seq"),
                "enabled": row.get("enabled"),
                "eta": [
                    {
                        "seq": item.get("eta_seq"),
                        "minutes": item.get("diff"),
                        "at": as_hkt(item.get("timestamp")),
                        "remark_zh": blank(item.get("remarks_tc")),
                    }
                    for item in (row.get("eta") or [])
                ],
            }
            for row in rows
            if isinstance(row, dict)
        ],
        note="每一班都帶 `diff`（分鐘）同 `at`（時間）。冇車的線唔會出現。",
    )


def gmb_stop_routes(stop_id: str) -> dict:
    """一個小巴站有邊幾條線經過。

    資料集 `hk-td-sm_7`，端點
    `https://data.etagmb.gov.hk/stop-route/{stop_id}`。不快取。
    用法：`gmb_stop_routes("20015409")`。
    市民會問：呢個站有邊幾條小巴線？
    """
    text = str(stop_id).strip()
    url = f"{ETA_BASE}/stop-route/{text}"
    payload, retrieved_at = fetch_json(url, dataset_id=DATASET_ETA, cache=False)
    rows = (payload or {}).get("data") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        raise MtrError("小巴站路線不是預期的 JSON", dataset_id=DATASET_ETA, endpoint=url)
    return envelope(
        dataset_id=DATASET_ETA,
        endpoint=url,
        retrieved_at=retrieved_at,
        data_at=None,
        update_frequency="as and when necessary",
        data=[
            {
                "route_id": row.get("route_id"),
                "route_seq": row.get("route_seq"),
                "name_zh": blank(row.get("name_tc")),
                "stop_seq": row.get("stop_seq"),
            }
            for row in rows
            if isinstance(row, dict)
        ],
        note="同一條線的正反方向是兩個 `route_seq`。",
    )


def gmb_route_stop_eta(route_id: int, route_seq: int, stop_seq: int) -> dict:
    """一條線在指定站序的下一班。

    資料集 `hk-td-sm_7`，端點
    `https://data.etagmb.gov.hk/eta/route-stop/{route_id}/{route_seq}/{stop_seq}`。
    不快取。用法：`gmb_route_stop_eta(2008632, 1, 3)`。
    市民會問：37 喺呢個站下一班幾時到？

    要提供站序，所以先要由 `gmb_route_stops()` 找 `seq`。
    """
    url = f"{ETA_BASE}/eta/route-stop/{int(route_id)}/{int(route_seq)}/{int(stop_seq)}"
    payload, retrieved_at = fetch_json(url, dataset_id=DATASET_ETA, cache=False)
    row = (payload or {}).get("data") if isinstance(payload, dict) else None
    if not isinstance(row, dict):
        raise MtrError("小巴到站不是預期的 JSON", dataset_id=DATASET_ETA, endpoint=url)
    return envelope(
        dataset_id=DATASET_ETA,
        endpoint=url,
        retrieved_at=retrieved_at,
        data_at=None,
        update_frequency="every minute",
        data={
            "stop": str(row.get("stop_id")),
            "enabled": row.get("enabled"),
            "eta": [
                {
                    "seq": item.get("eta_seq"),
                    "minutes": item.get("diff"),
                    "at": as_hkt(item.get("timestamp")),
                    "remark_zh": blank(item.get("remarks_tc")),
                }
                for item in (row.get("eta") or [])
            ],
        },
        note="最多三班。`diff` 是分鐘。",
    )


def gmb_route(region: str, code: str) -> dict:
    """一條小巴線的官方資料，用區域加號碼定位。

    資料集 `hk-td-sm_7`，端點
    `https://data.etagmb.gov.hk/route/{region}/{code}`。不快取。
    用法：`gmb_route("NT", "37")`。
    市民會問：37 號小巴由邊度去邊度？

    區域係 HKI、KLN、NT。路線號碼只在區域內唯一，所以兩個都要給。
    """
    url = f"{ETA_BASE}/route/{region.strip().upper()}/{code.strip()}"
    payload, retrieved_at = fetch_json(url, dataset_id=DATASET_ETA, cache=False)
    rows = (payload or {}).get("data") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        raise MtrError("小巴路線不是預期的 JSON", dataset_id=DATASET_ETA, endpoint=url)
    return envelope(
        dataset_id=DATASET_ETA,
        endpoint=url,
        retrieved_at=retrieved_at,
        data_at=None,
        update_frequency="as and when necessary",
        data=[
            {
                "route_id": row.get("route_id"),
                "region": row.get("region"),
                "route": row.get("route_code"),
                "description_zh": blank(row.get("description_tc")),
                "directions": [
                    {
                        "route_seq": item.get("route_seq"),
                        "origin_zh": blank(item.get("orig_tc")),
                        "dest_zh": blank(item.get("dest_tc")),
                    }
                    for item in (row.get("directions") or [])
                ],
            }
            for row in rows
            if isinstance(row, dict)
        ],
        note="`route_seq` 是方向；循環線通常只有 1。",
    )
