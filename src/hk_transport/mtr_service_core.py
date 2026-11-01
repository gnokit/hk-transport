"""First and last MTR departures from the MTR website snapshot.

Dataset `mtr-service-hours` is a snapshot of
`https://www.mtr.com.hk/ch/customer/services/service_hours_search.php`,
one page per station. It is **not** a data.gov.hk dataset; the source and
retrieval time are kept in the snapshot and repeated in the answer.

The page gives first and last departures per line and destination. It does
not give headways; `journey.COST["mtr_headway_minutes"]` is a policy estimate.
Short-turn trips are not separate trips in `mtr_core`, so a per-destination
window can close a direction even when a short-turn still runs.
"""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from hk_transport import mtr_core
from hk_transport._result import HKT, MtrError, compose

DATASET = "mtr-service-hours"
BASE = "https://www.mtr.com.hk/ch/customer/services/service_hours_search.php"
SNAPSHOT = Path(__file__).resolve().parent / "data" / "mtr_service_hours.json"

_memory: dict | None = None
_destinations: dict[tuple[str, str], str] | None = None


def clear_cache() -> None:
    """Forget the parsed snapshot and destination map in this process."""
    global _memory, _destinations
    _memory = None
    _destinations = None


def _load() -> dict:
    global _memory
    if _memory is not None:
        return _memory
    try:
        payload = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise MtrError(
            f"讀不到 MTR 服務時間快照：{exc}",
            dataset_id=DATASET,
            endpoint=BASE,
        ) from exc
    if not isinstance(payload, dict) or not payload.get("stations"):
        raise MtrError(
            "MTR 服務時間快照沒有 stations",
            dataset_id=DATASET,
            endpoint=BASE,
        )
    _memory = payload
    return payload


def trip_destinations() -> dict[tuple[str, str], str]:
    """The last station id of each MTR line/direction."""
    global _destinations
    if _destinations is not None:
        return _destinations
    rows = mtr_core.lines_and_stations()["data"]
    groups: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for row in rows:
        groups[(row["line_code"], row["direction"])].append(row)
    found: dict[tuple[str, str], str] = {}
    for key, stops in groups.items():
        stops.sort(key=lambda row: row["sequence"])
        found[key] = stops[-1]["id"]
    _destinations = found
    return found


def _minutes(value: str) -> int:
    hour, minute = value.split(":")
    return int(hour) * 60 + int(minute)


def _in_window(now: int, first: str, last: str) -> bool:
    start = _minutes(first)
    end = _minutes(last)
    if start <= end:
        return start <= now <= end
    return now >= start or now <= end


def service_at(at: datetime) -> dict:
    """First/last and in-service flags for every station and line at `at`."""
    if at.tzinfo is None:
        at = at.replace(tzinfo=HKT)
    at = at.astimezone(HKT)
    payload = _load()
    now = at.hour * 60 + at.minute
    stations: dict[str, dict] = {}
    for station_id, station in payload["stations"].items():
        lines: dict[str, dict] = {}
        for line_code, rows in (station.get("lines") or {}).items():
            if not rows:
                continue
            destinations = {
                row["dest_id"]: {
                    "first": row["first"],
                    "last": row["last"],
                    "in_service": _in_window(now, row["first"], row["last"]),
                }
                for row in rows
            }
            first = min(row["first"] for row in rows)
            first_minutes = _minutes(first)

            def adjusted(value: str) -> int:
                minutes = _minutes(value)
                return minutes + 24 * 60 if minutes < first_minutes else minutes

            last = max((row["last"] for row in rows), key=adjusted)
            lines[line_code] = {
                "first": first,
                "last": last,
                "in_service": _in_window(now, first, last),
                "destinations": destinations,
            }
        stations[station_id] = {
            "name_zh": station.get("name_zh"),
            "open": station.get("open"),
            "lines": lines,
        }
    source = {
        "dataset_id": DATASET,
        "endpoint": BASE,
        "retrieved_at": payload.get("retrieved_at"),
        "data_at": None,
        "update_frequency": "as and when necessary",
    }
    return compose(
        [source],
        stations,
        note=(
            "MTR 首末班車來自港鐵官網服務時間頁的快照，不是 data.gov.hk 開放數據；"
            "官網只公布首末班車，沒有公布班次頻率，所以班次等候仍是政策估算。"
        ),
    )
