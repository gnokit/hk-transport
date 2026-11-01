"""Headway and service hours from the Transport Department GTFS feed.

Dataset `hk-td-tis_11-pt-headway-en`, four files under
`https://static.data.gov.hk/td/pt-headway-tc/`:
`frequencies.txt`, `trips.txt`, `calendar.txt`, `calendar_dates.txt`.
The files are biweekly and cached for 30 days by `_http`.

This module maps a query time to one row per route:

    route_id -> {
        "headway_minutes": float | None,
        "in_service": bool | None,
        "first": "HH:MM" | None,
        "last": "HH:MM" | None,
    }

MTR heavy rail is not in this feed; the caller keeps its policy wait for it.
`in_service` is None when the route has trips but no frequencies rows: the
service hours are unknown, so the caller must not close it.
"""

from __future__ import annotations

import csv
from datetime import datetime, timedelta

from hk_transport._http import fetch_text
from hk_transport._result import HKT, compose

DATASET = "hk-td-tis_11-pt-headway-en"
BASE = "https://static.data.gov.hk/td/pt-headway-tc"
FILES = ("frequencies", "trips", "calendar", "calendar_dates")
URLS = {name: f"{BASE}/{name}.txt" for name in FILES}

_memory: dict | None = None


def clear_cache() -> None:
    """Forget the parsed GTFS tables held in this process."""
    global _memory
    _memory = None


def _rows(text: str) -> list[dict]:
    return list(csv.DictReader(text.splitlines()))


def _integer(value: str | None) -> int | None:
    if value is None:
        return None
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _seconds(value: str | None) -> int | None:
    if not value:
        return None
    try:
        hour, minute, second = (int(part) for part in value.split(":"))
    except (TypeError, ValueError):
        return None
    return hour * 3600 + minute * 60 + second


def _hhmm(seconds: int | None) -> str | None:
    if seconds is None:
        return None
    seconds %= 24 * 3600
    return f"{seconds // 3600:02d}:{(seconds % 3600) // 60:02d}"


def _load() -> dict:
    global _memory
    if _memory is not None:
        return _memory

    sources: list[dict] = []
    texts: dict[str, str] = {}
    for name in FILES:
        text, retrieved_at = fetch_text(URLS[name], dataset_id=DATASET)
        texts[name] = text
        sources.append(
            {
                "dataset_id": DATASET,
                "endpoint": URLS[name],
                "retrieved_at": retrieved_at,
                "data_at": None,
                "update_frequency": "biweekly",
            }
        )

    frequencies: dict[str, list[tuple[int, int, int]]] = {}
    for row in _rows(texts["frequencies"]):
        trip_id = (row.get("trip_id") or "").strip()
        start = _seconds(row.get("start_time"))
        end = _seconds(row.get("end_time"))
        headway = _integer(row.get("headway_secs"))
        if not trip_id or start is None or end is None or headway is None:
            continue
        frequencies.setdefault(trip_id, []).append((start, end, headway))

    trips: dict[str, list[tuple[str, str]]] = {}
    for row in _rows(texts["trips"]):
        route_id = (row.get("route_id") or "").strip()
        trip_id = (row.get("trip_id") or "").strip()
        service_id = (row.get("service_id") or "").strip()
        if not route_id or not trip_id or not service_id:
            continue
        trips.setdefault(route_id, []).append((trip_id, service_id))

    calendar: dict[str, dict] = {}
    for row in _rows(texts["calendar"]):
        service_id = (row.get("service_id") or "").strip()
        if not service_id:
            continue
        calendar[service_id] = {
            "days": tuple(
                (row.get(day) or "0").strip() == "1"
                for day in (
                    "monday",
                    "tuesday",
                    "wednesday",
                    "thursday",
                    "friday",
                    "saturday",
                    "sunday",
                )
            ),
            "start": (row.get("start_date") or "").strip(),
            "end": (row.get("end_date") or "").strip(),
        }

    exceptions: dict[tuple[str, str], str] = {}
    for row in _rows(texts["calendar_dates"]):
        service_id = (row.get("service_id") or "").strip()
        date = (row.get("date") or "").strip()
        kind = (row.get("exception_type") or "").strip()
        if service_id and date and kind:
            exceptions[(service_id, date)] = kind

    _memory = {
        "frequencies": frequencies,
        "trips": trips,
        "calendar": calendar,
        "exceptions": exceptions,
        "sources": sources,
    }
    return _memory


def _active_services(data: dict, at: datetime) -> set[str]:
    date = at.strftime("%Y%m%d")
    weekday = at.weekday()
    active: set[str] = set()
    for service_id, info in data["calendar"].items():
        if info["start"] <= date <= info["end"] and info["days"][weekday]:
            active.add(service_id)
    for (service_id, exception_date), kind in data["exceptions"].items():
        if exception_date != date:
            continue
        if kind == "1":
            active.add(service_id)
        elif kind == "2":
            active.discard(service_id)
    return active


def _current_headway(
    windows: list[tuple[int, int, int]], seconds: int
) -> int | None:
    found = [headway for start, end, headway in windows if start <= seconds < end]
    return min(found) if found else None


def service_at(at: datetime) -> dict:
    """Headway and service status for every route at `at` (Hong Kong time)."""
    if at.tzinfo is None:
        at = at.replace(tzinfo=HKT)
    at = at.astimezone(HKT)
    data = _load()
    active = _active_services(data, at)
    previous_active = _active_services(data, at - timedelta(days=1))
    seconds = at.hour * 3600 + at.minute * 60 + at.second
    early = seconds < 6 * 3600
    result: dict[str, dict] = {}
    for route_id, trips in data["trips"].items():
        active_trips = [
            (trip_id, service_id)
            for trip_id, service_id in trips
            if service_id in active
        ]
        previous_trips = [
            (trip_id, service_id)
            for trip_id, service_id in trips
            if service_id in previous_active
        ]
        if not active_trips and not previous_trips:
            result[route_id] = {
                "headway_minutes": None,
                "in_service": False,
                "first": None,
                "last": None,
            }
            continue
        windows: list[tuple[int, int, int]] = []
        for trip_id, _service_id in active_trips:
            windows.extend(data["frequencies"].get(trip_id, []))
        previous_windows: list[tuple[int, int, int]] = []
        for trip_id, _service_id in previous_trips:
            previous_windows.extend(data["frequencies"].get(trip_id, []))
        all_windows = windows + previous_windows
        if not all_windows:
            result[route_id] = {
                "headway_minutes": None,
                "in_service": None,
                "first": None,
                "last": None,
            }
            continue
        headway = _current_headway(windows, seconds)
        if headway is None and early:
            # A trip that starts before midnight can end after 24:00.
            headway = _current_headway(previous_windows, seconds + 24 * 3600)
        result[route_id] = {
            "headway_minutes": round(headway / 60, 1) if headway else None,
            "in_service": headway is not None,
            "first": _hhmm(min(start for start, _end, _h in all_windows)),
            "last": _hhmm(max(end for _start, end, _h in all_windows)),
        }
    return compose(
        data["sources"],
        result,
        note=(
            "班次同服務時間來自運輸署 GTFS 班次資料；只覆蓋有班次資料的路線，"
            "有路線但冇 frequencies 的，服務時間未知，會保留；"
            "沒有實時延誤。港鐵重鐵不在這份資料內。"
        ),
    )
