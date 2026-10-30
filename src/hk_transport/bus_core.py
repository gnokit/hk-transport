"""One function per bus data resource.

Each function reads one published resource and returns the whole table. Nothing
here resolves a place name, joins two files, or picks a route.

Static route and stop tables are cached for 30 days; ETA calls are never cached.
Every KMB and Citybus request needs a User-Agent, or the host answers 403.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urlencode

import ijson

from hk_transport._http import cached_file, fetch_json
from hk_transport._result import HKT, MtrError, as_hkt, envelope
from hk_transport._values import blank, clean_breaks, number

KMB_DATASET = "hk-td-tis_21-etakmb"
KMB_BASE = "https://data.etabus.gov.hk/v1/transport/kmb"
CTB_DATASET = "ctb-eta-transport-realtime-eta"
CTB_BASE = "https://rt.data.gov.hk/v2/transport/citybus"
NLB_DATASET = "nlb-bus-nlb-bus-service-v2"
NLB_BASE = "https://rt.data.gov.hk/v2/transport/nlb"
TD_FARES_DATASET = "hk-td-tis_23-routes-fares-geojson"
TD_BUS_FARES_URL = "https://static.data.gov.hk/td/routes-fares-geojson/JSON_BUS.json"

STATIC_FREQ = "daily"
ETA_FREQ = "60s"
_SNAPSHOT_TTL = timedelta(days=30)
_BOUNDS = {"o": "outbound", "outbound": "outbound", "i": "inbound", "inbound": "inbound"}


def _bound(value: str) -> str:
    """KMB writes bound as O/I in data and outbound/inbound in the path."""
    text = (value or "").strip().lower()
    if text not in _BOUNDS:
        raise MtrError(
            f"方向只接受 O／I 或 outbound／inbound：{value}",
            dataset_id=KMB_DATASET,
            endpoint=KMB_BASE,
        )
    return _BOUNDS[text]


def _envelope(
    dataset_id: str,
    endpoint: str,
    payload: object,
    retrieved_at: str,
    rows: object,
    frequency: str,
) -> dict:
    generated = payload.get("generated_timestamp") if isinstance(payload, dict) else None
    return envelope(
        dataset_id=dataset_id,
        endpoint=endpoint,
        retrieved_at=retrieved_at,
        data_at=as_hkt(blank(generated)),
        update_frequency=frequency,
        data=rows,
    )


def _kmb_route_row(row: dict) -> dict:
    return {
        "route": blank(row.get("route")),
        "bound": blank(row.get("bound")),
        "service_type": blank(row.get("service_type")),
        "orig_zh": blank(row.get("orig_tc")),
        "orig_en": blank(row.get("orig_en")),
        "dest_zh": blank(row.get("dest_tc")),
        "dest_en": blank(row.get("dest_en")),
    }


def _kmb_stop_row(row: dict) -> dict:
    return {
        "stop": blank(row.get("stop")),
        "name_zh": blank(row.get("name_tc")),
        "name_en": blank(row.get("name_en")),
        "latitude": number(row.get("lat")),
        "longitude": number(row.get("long")),
    }


def _route_stop_row(row: dict) -> dict:
    return {
        "route": blank(row.get("route")),
        "direction": blank(row.get("bound")) or blank(row.get("dir")),
        "service_type": blank(row.get("service_type")),
        "seq": number(row.get("seq")),
        "stop": blank(row.get("stop")),
    }


def _eta_row(row: dict) -> dict:
    return {
        "operator": blank(row.get("co")),
        "route": blank(row.get("route")),
        "direction": blank(row.get("dir")),
        "service_type": blank(row.get("service_type")),
        "seq": number(row.get("seq")),
        "dest_zh": blank(row.get("dest_tc")),
        "dest_en": blank(row.get("dest_en")),
        "eta_seq": number(row.get("eta_seq")),
        "eta": as_hkt(blank(row.get("eta"))),
        "remark_zh": blank(row.get("rmk_tc")),
        "remark_en": blank(row.get("rmk_en")),
        "data_timestamp": as_hkt(blank(row.get("data_timestamp"))),
    }


def kmb_routes() -> dict:
    """All KMB and LWB routes, one row per bound and service type.

    Dataset `hk-td-tis_21-etakmb`, endpoint
    `https://data.etabus.gov.hk/v1/transport/kmb/route/`.
    Answers: which routes exist, where each one starts and ends.
    """
    url = f"{KMB_BASE}/route/"
    payload, retrieved_at = fetch_json(url, dataset_id=KMB_DATASET)
    rows = [_kmb_route_row(row) for row in payload.get("data") or []]
    result = _envelope(KMB_DATASET, url, payload, retrieved_at, rows, STATIC_FREQ)
    result["note"] = (
        "這份表同時包含九巴同龍運，表內沒有分開標明營辦商。"
    )
    return result


def kmb_route(route: str, bound: str = "outbound", service_type: str = "1") -> dict:
    """One KMB route variant.

    Endpoint `/route/{route}/{bound}/{service_type}`. `bound` accepts O/I or
    outbound/inbound; the API only accepts the words.
    """
    url = f"{KMB_BASE}/route/{route}/{_bound(bound)}/{service_type}"
    payload, retrieved_at = fetch_json(url, dataset_id=KMB_DATASET)
    data = payload.get("data")
    row = _kmb_route_row(data) if isinstance(data, dict) else None
    return _envelope(
        KMB_DATASET, url, payload, retrieved_at, row, STATIC_FREQ
    )


def kmb_stops() -> dict:
    """Every KMB and LWB stop, with coordinates.

    Dataset `hk-td-tis_21-etakmb`, endpoint
    `https://data.etabus.gov.hk/v1/transport/kmb/stop`.
    Answers: where a stop is, and what it is called.
    """
    url = f"{KMB_BASE}/stop"
    payload, retrieved_at = fetch_json(url, dataset_id=KMB_DATASET)
    rows = [_kmb_stop_row(row) for row in payload.get("data") or []]
    return _envelope(KMB_DATASET, url, payload, retrieved_at, rows, STATIC_FREQ)


def kmb_stop(stop_id: str) -> dict:
    """One KMB stop.

    Endpoint `/stop/{stop_id}`.
    """
    url = f"{KMB_BASE}/stop/{stop_id}"
    payload, retrieved_at = fetch_json(url, dataset_id=KMB_DATASET)
    data = payload.get("data")
    row = _kmb_stop_row(data) if isinstance(data, dict) else None
    return _envelope(KMB_DATASET, url, payload, retrieved_at, row, STATIC_FREQ)


def kmb_route_stops(
    route: str, bound: str = "outbound", service_type: str = "1"
) -> dict:
    """Stop order for one KMB route variant.

    Endpoint `/route-stop/{route}/{bound}/{service_type}`.
    Answers: which stops a route calls at, in order, going one way.
    """
    url = f"{KMB_BASE}/route-stop/{route}/{_bound(bound)}/{service_type}"
    payload, retrieved_at = fetch_json(url, dataset_id=KMB_DATASET)
    rows = [_route_stop_row(row) for row in payload.get("data") or []]
    return _envelope(KMB_DATASET, url, payload, retrieved_at, rows, STATIC_FREQ)


def kmb_download_route_stops() -> dict:
    """Every KMB and LWB route-stop row, fetched live. Rebuilds the snapshot.

    Endpoint `https://data.etabus.gov.hk/v1/transport/kmb/route-stop`, about
    3 MB and 36,000 rows. This endpoint answers 403 unless the request carries
    a `Referer` header, and the host throttles repeated downloads. Prefer
    `kmb_route_stops_all`, and rebuild rarely.
    """
    url = f"{KMB_BASE}/route-stop"
    payload, retrieved_at = fetch_json(
        url, dataset_id=KMB_DATASET, headers={"Referer": "https://data.gov.hk/"}
    )
    rows = [_route_stop_row(row) for row in payload.get("data") or []]
    return _envelope(KMB_DATASET, url, payload, retrieved_at, rows, STATIC_FREQ)


def _snapshot_path() -> Path:
    return Path(__file__).resolve().parent / "data" / "bus_route_stops.json"


def _load_snapshot() -> dict:
    path = _snapshot_path()
    endpoint = f"{KMB_BASE}/route-stop"
    if not path.is_file():
        raise MtrError(
            "找不到巴士站序快照，請跑 scripts/build_bus_route_stops.py",
            dataset_id=KMB_DATASET,
            endpoint=endpoint,
        )
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise MtrError(str(exc), dataset_id=KMB_DATASET, endpoint=endpoint) from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("variants"), dict):
        raise MtrError(
            "巴士站序快照不是預期的 JSON", dataset_id=KMB_DATASET, endpoint=endpoint
        )
    return payload


def _stale(retrieved_at: str) -> bool:
    fetched = datetime.fromisoformat(retrieved_at)
    if fetched.tzinfo is None:
        fetched = fetched.replace(tzinfo=HKT)
    return datetime.now(HKT) - fetched >= _SNAPSHOT_TTL


def kmb_route_stops_all() -> dict:
    """Every KMB and LWB stop sequence, read from the bundled snapshot.

    No network call. Each route variant is stored as its stops in order, keyed
    `route|direction|service_type`. Rebuild with
    `scripts/build_bus_route_stops.py`; after 30 days the note says so and the
    data is still returned.
    Answers: which routes call at a given stop, and in what order.
    """
    snapshot = _load_snapshot()
    rows = []
    for key, stops in snapshot["variants"].items():
        route, direction, service = key.split("|")
        for index, stop in enumerate(stops, start=1):
            rows.append(
                {
                    "route": route,
                    "direction": direction,
                    "service_type": service,
                    "seq": index,
                    "stop": stop,
                }
            )
    retrieved_at = snapshot.get("retrieved_at")
    note = (
        "巴士站序是九巴／龍運完整路線站表的快照，查詢時不重新下載。"
        "路線改動後要跑 scripts/build_bus_route_stops.py 重建。"
    )
    if isinstance(retrieved_at, str) and _stale(retrieved_at):
        note += "這份快照已超過 30 日。"
    return envelope(
        dataset_id=KMB_DATASET,
        endpoint=f"{KMB_BASE}/route-stop",
        retrieved_at=retrieved_at if isinstance(retrieved_at, str) else None,
        data_at=snapshot.get("data_at"),
        update_frequency=STATIC_FREQ,
        data=rows,
        note=note,
    )


def kmb_route_eta(route: str, service_type: str = "1") -> dict:
    """Next buses for every stop on one KMB route variant. Live, never cached.

    Endpoint `/route-eta/{route}/{service_type}`.
    Answers: when the next bus reaches each stop on this route.
    """
    url = f"{KMB_BASE}/route-eta/{route}/{service_type}"
    payload, retrieved_at = fetch_json(url, dataset_id=KMB_DATASET, cache=False)
    rows = [_eta_row(row) for row in payload.get("data") or []]
    return _envelope(KMB_DATASET, url, payload, retrieved_at, rows, ETA_FREQ)


def kmb_stop_eta(stop_id: str, route: str, service_type: str = "1") -> dict:
    """Next buses for one KMB route at one stop. Live, never cached.

    Endpoint `/eta/{stop_id}/{route}/{service_type}`.
    Answers: when the next bus of this route reaches this stop.
    """
    url = f"{KMB_BASE}/eta/{stop_id}/{route}/{service_type}"
    payload, retrieved_at = fetch_json(url, dataset_id=KMB_DATASET, cache=False)
    rows = [_eta_row(row) for row in payload.get("data") or []]
    return _envelope(KMB_DATASET, url, payload, retrieved_at, rows, ETA_FREQ)


def ctb_routes() -> dict:
    """All Citybus routes.

    Dataset `ctb-eta-transport-realtime-eta`, endpoint
    `https://rt.data.gov.hk/v2/transport/citybus/route/CTB`.
    Answers: which Citybus routes exist, and where they start and end.
    """
    url = f"{CTB_BASE}/route/CTB"
    payload, retrieved_at = fetch_json(url, dataset_id=CTB_DATASET)
    rows = [
        {
            "route": blank(row.get("route")),
            "orig_zh": blank(row.get("orig_tc")),
            "orig_en": blank(row.get("orig_en")),
            "dest_zh": blank(row.get("dest_tc")),
            "dest_en": blank(row.get("dest_en")),
        }
        for row in payload.get("data") or []
        if isinstance(row, dict)
    ]
    return _envelope(CTB_DATASET, url, payload, retrieved_at, rows, STATIC_FREQ)


def ctb_route(route: str) -> dict:
    """One Citybus route.

    Endpoint `/route/CTB/{route}`.
    """
    url = f"{CTB_BASE}/route/CTB/{route}"
    payload, retrieved_at = fetch_json(url, dataset_id=CTB_DATASET)
    data = payload.get("data")
    row = (
        {
            "route": blank(data.get("route")),
            "orig_zh": blank(data.get("orig_tc")),
            "orig_en": blank(data.get("orig_en")),
            "dest_zh": blank(data.get("dest_tc")),
            "dest_en": blank(data.get("dest_en")),
        }
        if isinstance(data, dict)
        else None
    )
    return _envelope(CTB_DATASET, url, payload, retrieved_at, row, STATIC_FREQ)


def ctb_route_stops(route: str, direction: str = "outbound") -> dict:
    """Stop order for one Citybus route, one direction.

    Endpoint `/route-stop/CTB/{route}/{direction}`. Citybus has no bulk
    route-stop resource, so this is one route per call.
    """
    url = f"{CTB_BASE}/route-stop/CTB/{route}/{_bound(direction)}"
    payload, retrieved_at = fetch_json(url, dataset_id=CTB_DATASET)
    rows = [
        {
            "route": blank(row.get("route")),
            "direction": blank(row.get("dir")),
            "seq": number(row.get("seq")),
            "stop": blank(row.get("stop")),
        }
        for row in payload.get("data") or []
        if isinstance(row, dict)
    ]
    return _envelope(CTB_DATASET, url, payload, retrieved_at, rows, STATIC_FREQ)


def ctb_stop(stop_id: str) -> dict:
    """One Citybus stop.

    Endpoint `/stop/{stop_id}`.
    """
    url = f"{CTB_BASE}/stop/{stop_id}"
    payload, retrieved_at = fetch_json(url, dataset_id=CTB_DATASET)
    data = payload.get("data")
    row = (
        {
            "stop": blank(data.get("stop")),
            "name_zh": blank(data.get("name_tc")),
            "name_en": blank(data.get("name_en")),
            "latitude": number(data.get("lat")),
            "longitude": number(data.get("long")),
        }
        if isinstance(data, dict)
        else None
    )
    return _envelope(CTB_DATASET, url, payload, retrieved_at, row, STATIC_FREQ)


def ctb_eta(stop_id: str, route: str) -> dict:
    """Next buses for one Citybus route at one stop. Live, never cached.

    Endpoint `/eta/CTB/{stop_id}/{route}`. An empty list means no bus of that
    route is due at that stop, not that the stop is wrong.
    """
    url = f"{CTB_BASE}/eta/CTB/{stop_id}/{route}"
    payload, retrieved_at = fetch_json(url, dataset_id=CTB_DATASET, cache=False)
    rows = [_eta_row(row) for row in payload.get("data") or []]
    return _envelope(CTB_DATASET, url, payload, retrieved_at, rows, ETA_FREQ)


def nlb_routes() -> dict:
    """All New Lantao Bus routes.

    Dataset `nlb-bus-nlb-bus-service-v2`, endpoint
    `https://rt.data.gov.hk/v2/transport/nlb/route.php?action=list`.
    Answers: which Lantau routes exist, and whether they run overnight.
    """
    url = f"{NLB_BASE}/route.php?action=list"
    payload, retrieved_at = fetch_json(url, dataset_id=NLB_DATASET)
    rows = [
        {
            "route_id": blank(row.get("routeId")),
            "route": blank(row.get("routeNo")),
            "name_zh": blank(row.get("routeName_c")),
            "name_en": blank(row.get("routeName_e")),
            "overnight": number(row.get("overnightRoute")) == 1,
            "special": number(row.get("specialRoute")) == 1,
        }
        for row in (payload.get("routes") if isinstance(payload, dict) else []) or []
        if isinstance(row, dict)
    ]
    return _envelope(NLB_DATASET, url, payload, retrieved_at, rows, STATIC_FREQ)


def nlb_stops(route_id: str) -> dict:
    """Stop order for one New Lantao Bus route, with fares.

    Endpoint `stop.php?action=list&routeId={id}`. This is the only bus feed in
    scope that carries a fare, and it carries a holiday fare as well.
    Answers: which stops a Lantau route calls at, and what it costs to reach
    each one.
    """
    url = f"{NLB_BASE}/stop.php?{urlencode({'action': 'list', 'routeId': route_id})}"
    payload, retrieved_at = fetch_json(url, dataset_id=NLB_DATASET)
    rows = [
        {
            "stop_id": blank(row.get("stopId")),
            "name_zh": blank(row.get("stopName_c")),
            "name_en": blank(row.get("stopName_e")),
            "latitude": number(row.get("latitude")),
            "longitude": number(row.get("longitude")),
            "fare": number(row.get("fare")),
            "fare_holiday": number(row.get("fareHoliday")),
        }
        for row in (payload.get("stops") if isinstance(payload, dict) else []) or []
        if isinstance(row, dict)
    ]
    return _envelope(NLB_DATASET, url, payload, retrieved_at, rows, STATIC_FREQ)


def _station_name(value: object) -> tuple[str | None, str | None]:
    """Split a published stop name from a sentence appended to it.

    Some routes carry a payment remark inside `locEndNameE`, for example
    "LOK MA CHAU STATION ‧ FUTIAN PORT Please inquire with the operator ...".
    """
    text = blank(value)
    if text is None:
        return None, None
    marker = text.find(" Please ")
    if marker == -1:
        return text, None
    return text[:marker].strip(), text[marker + 1 :].strip()


def td_bus_fares() -> dict:
    """Adult route fare and whole-route journey time for franchised buses.

    Dataset `hk-td-tis_23-routes-fares-geojson`, endpoint
    `https://static.data.gov.hk/td/routes-fares-geojson/JSON_BUS.json`.
    About 75 MB and 56,000 stop features, read with a streaming parser and
    cached for 30 days.

    `fare` is the adult full fare for boarding that route, not a section fare.
    `journey_time_minutes` is the whole route, not the segment a caller rides.
    Answers: what this route costs, and how long its full run is published as.
    """
    path, retrieved_at = cached_file(TD_BUS_FARES_URL, dataset_id=TD_FARES_DATASET)
    seen: dict[tuple, dict] = {}
    updated = None
    with path.open("rb") as handle:
        for feature in ijson.items(handle, "features.item"):
            props = feature.get("properties") or {}
            key = (
                blank(props.get("companyCode")),
                blank(props.get("routeNameE")),
                props.get("routeType"),
                blank(props.get("serviceMode")),
            )
            updated = updated or blank(props.get("lastUpdateDate"))
            if key in seen:
                continue
            end_en, remark = _station_name(props.get("locEndNameE"))
            start_en, _ = _station_name(props.get("locStartNameE"))
            seen[key] = {
                "company": key[0],
                "route": key[1],
                "route_type": key[2],
                "service_mode": key[3],
                "origin_zh": blank(props.get("locStartNameC")),
                "origin_en": start_en,
                "dest_zh": blank(props.get("locEndNameC")),
                "dest_en": end_en,
                "fare": number(props.get("fullFare")),
                "journey_time_minutes": number(props.get("journeyTime")),
                "remark": remark,
            }
    note = (
        "車費是成人全程價，逐程上車計，未計轉乘優惠。"
        "journey_time_minutes 是整條路線的公布全程時間，不是分段行車時間。"
    )
    return envelope(
        dataset_id=TD_FARES_DATASET,
        endpoint=TD_BUS_FARES_URL,
        retrieved_at=retrieved_at,
        data_at=as_hkt(updated),
        update_frequency="biweekly",
        data=list(seen.values()),
        note=note,
    )


_TD_STOP_MEMORY: dict | None = None


def clear_td_cache() -> None:
    """Forget the parsed 75 MB stop table held in this process."""
    global _TD_STOP_MEMORY
    _TD_STOP_MEMORY = None


def td_bus_route_stops() -> dict:
    """全部專營巴士的站序，一站一列，帶 WGS84 座標。

    資料集 `hk-td-tis_23-routes-fares-geojson`，端點 `JSON_BUS.json`
    （75 MB，30 日快取，有 UTF-8 BOM）。
    用法：`td_bus_route_stops()`。
    市民會問：呢條線停邊啲站？呢個站有邊幾條線？

    56,103 列，涵蓋 KMB、CTB、LWB、NLB、LRTFeeder（港鐵巴士）、XB、DB、PI。
    **`companyCode` 可以是 `KMB+CTB` 這種聯營寫法，係一個變體，唔可以數兩次。**
    停止位置用運輸署的數字站號，跨營辦商共用：4,490 個站號之中，2,366 個
    由多過一個營辦商使用，所以 CTB 同 KMB 的同一個站會是同一個號。
    站名有時夾住 `<br>`，這裡會清走。
    """
    global _TD_STOP_MEMORY
    if _TD_STOP_MEMORY is not None:
        return _TD_STOP_MEMORY
    path, retrieved_at = cached_file(TD_BUS_FARES_URL, dataset_id=TD_FARES_DATASET)
    rows: list[dict] = []
    updated = None
    try:
        with path.open("rb") as handle:
            if handle.read(3) != b"\xef\xbb\xbf":
                handle.seek(0)
            for feature in ijson.items(handle, "features.item"):
                props = feature.get("properties") or {}
                geometry = feature.get("geometry") or {}
                coords = geometry.get("coordinates") or [None, None]
                updated = updated or blank(props.get("lastUpdateDate"))
                rows.append(
                    {
                        "company": blank(props.get("companyCode")),
                        "route": blank(props.get("routeNameC")),
                        "route_id": props.get("routeId"),
                        "route_seq": props.get("routeSeq"),
                        "route_type": props.get("routeType"),
                        "service_mode": blank(props.get("serviceMode")),
                        "special_type": props.get("specialType"),
                        "seq": props.get("stopSeq"),
                        "stop": str(props.get("stopId")),
                        "name_zh": clean_breaks(props.get("stopNameC")),
                        "name_en": blank(props.get("stopNameE")),
                        "latitude": number(coords[1]) if len(coords) > 1 else None,
                        "longitude": number(coords[0]) if len(coords) > 0 else None,
                        "pick_drop": props.get("stopPickDrop"),
                        "fare": number(props.get("fullFare")),
                        "journey_time_minutes": number(props.get("journeyTime")),
                    }
                )
    except (OSError, ValueError) as exc:
        raise MtrError(str(exc), dataset_id=TD_FARES_DATASET, endpoint=TD_BUS_FARES_URL) from exc
    _TD_STOP_MEMORY = envelope(
        dataset_id=TD_FARES_DATASET,
        endpoint=TD_BUS_FARES_URL,
        retrieved_at=retrieved_at,
        data_at=as_hkt(updated),
        update_frequency="biweekly",
        data=rows,
        note=(
            "站序同座標來自運輸署；`companyCode` 的 `KMB+CTB` 是聯營線，算一個變體。"
            "站號跨營辦商共用。站名已清走 `<br>`。"
        ),
    )
    return _TD_STOP_MEMORY
