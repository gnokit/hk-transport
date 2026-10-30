"""The Transport Department stop-level files, read once.

Tram, Peak Tram and ferry are published in the same GeoJSON shape as the buses
and the minibuses: one feature per stop per route variant, carrying the route,
the fare, the whole-route time, the stop order and a WGS84 point. One parser
here means the three modes cannot drift apart.
"""

from __future__ import annotations

import ijson

from hk_transport._http import cached_file
from hk_transport._result import MtrError, as_hkt
from hk_transport._values import blank, clean_breaks, number

DATASET_ID = "hk-td-tis_23-routes-fares-geojson"
BASE = "https://static.data.gov.hk/td/routes-fares-geojson"


def split_remark(text: str | None) -> tuple[str | None, str | None]:
    """TD appends a fare remark in brackets, e.g. 跑馬地(樂悠卡兩元)."""
    value = blank(text)
    if value is None:
        return None, None
    if "(" in value:
        head, _, _tail = value.partition("(")
        remark = value[len(head):].replace(")(", "; ").strip("() ")
        return head.strip() or None, remark or None
    return value, None


def stop_rows(url: str) -> dict:
    """Every stop of every variant in one TD file.

    Returns a dict with `rows`, `retrieved_at` and `data_at`; the caller wraps
    it in an envelope. The file is cached for 30 days by `_http`.
    """
    path, retrieved_at = cached_file(url, dataset_id=DATASET_ID)
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
                origin, _ = split_remark(props.get("locStartNameC"))
                dest, dest_remark = split_remark(props.get("locEndNameC"))
                rows.append(
                    {
                        "company": blank(props.get("companyCode")),
                        "route": blank(props.get("routeNameC")),
                        "route_en": blank(props.get("routeNameE")),
                        "route_id": props.get("routeId"),
                        "route_seq": props.get("routeSeq"),
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
                        "origin_zh": origin,
                        "dest_zh": dest,
                        "remark": dest_remark,
                    }
                )
    except (OSError, ValueError) as exc:
        raise MtrError(str(exc), dataset_id=DATASET_ID, endpoint=url) from exc
    return {"rows": rows, "retrieved_at": retrieved_at, "data_at": as_hkt(updated)}


def dedupe_variants(rows: list[dict], fields: tuple[str, ...]) -> list[dict]:
    """One row per route variant, keeping the first, for the route tables."""
    seen: dict[tuple, dict] = {}
    for row in rows:
        key = tuple(row[field] for field in fields)
        seen.setdefault(key, row)
    return list(seen.values())
