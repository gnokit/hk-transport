"""One function per bus data resource.

Each function reads one published resource and returns the whole table. Nothing
here resolves a place name, joins two files, or picks a route.

Static route and stop tables are cached for 30 days; ETA calls are never cached.
Every KMB and Citybus request needs a User-Agent, or the host answers 403.
"""

from __future__ import annotations

from urllib.parse import urlencode

from hk_transport._http import fetch_json
from hk_transport._result import MtrError, as_hkt, envelope
from hk_transport._values import blank, number

KMB_DATASET = "hk-td-tis_21-etakmb"
KMB_BASE = "https://data.etabus.gov.hk/v1/transport/kmb"
CTB_DATASET = "ctb-eta-transport-realtime-eta"
CTB_BASE = "https://rt.data.gov.hk/v2/transport/citybus"
NLB_DATASET = "nlb-bus-nlb-bus-service-v2"
NLB_BASE = "https://rt.data.gov.hk/v2/transport/nlb"

STATIC_FREQ = "daily"
ETA_FREQ = "60s"
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


def kmb_all_route_stops() -> dict:
    """Every KMB and LWB route-stop row in one table.

    Endpoint `https://data.etabus.gov.hk/v1/transport/kmb/route-stop`, about
    3 MB. One request, instead of one per route variant. This endpoint answers
    403 unless the request carries a `Referer` header.
    Answers: which routes call at a given stop, and in what order.
    """
    url = f"{KMB_BASE}/route-stop"
    payload, retrieved_at = fetch_json(
        url, dataset_id=KMB_DATASET, headers={"Referer": "https://data.gov.hk/"}
    )
    rows = [_route_stop_row(row) for row in payload.get("data") or []]
    return _envelope(KMB_DATASET, url, payload, retrieved_at, rows, STATIC_FREQ)


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
