"""Rebuild the MTR first/last-train snapshot from the MTR website.

    uv run python scripts/build_mtr_service_hours.py

The MTR service-hours page is server-rendered per station. One request per
station (about 97) is enough; the result is a compact JSON snapshot that
`mtr_service_core` reads at run time. The page gives first and last departures
per line and destination, not headways. Headways remain a policy estimate.

This is not a data.gov.hk dataset. The snapshot records the source URL and
when it was taken so the answer can say where the times came from.
"""

from __future__ import annotations

import argparse
import json
import re
import time
from pathlib import Path

import requests

from hk_transport import mtr_core
from hk_transport._result import now_hkt

ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT = ROOT / "src" / "hk_transport" / "data" / "mtr_service_hours.json"
BASE = "https://www.mtr.com.hk/ch/customer/services/service_hours_search.php"
DATASET = "mtr-service-hours"
HEADERS = {
    "User-Agent": "hk-transport",
    "Referer": "https://www.mtr.com.hk/ch/customer/services/timetable_index.html",
}
COMMENT = re.compile(r"<!--.*?-->", re.S)
OPEN = re.compile(r"車站開放時間:\s*(\d{2}:\d{2})-(\d{2}:\d{2})")
SECTION = re.compile(r'<h2 class="trainLine ([A-Z]+)"')
ROW = re.compile(
    r'<span class="js_station_(\d+)"[^>]*>\s*-\s*</span>\s*</td>\s*'
    r'<td\s+class="firstTrain">\s*(\d{4})\s*</td>\s*'
    r'<td>\s*(\d{4})\s*</td>',
    re.S,
)
# The service-hours pages do not include the Airport Express; the MTR
# timetable page publishes AEL first/last separately (effective 2026-09-13).
AEL_SERVICE = {
    "44": [("47", "05:50", "00:48"), ("56", "05:50", "00:48")],
    "45": [("47", "05:53", "00:52"), ("56", "05:53", "00:52")],
    "46": [("47", "06:00", "00:59"), ("56", "06:00", "00:59")],
    "47": [("44", "05:54", "00:48"), ("56", "06:15", "01:13")],
    "56": [("44", "06:00", "00:45")],
}


def _clock(value: str) -> str:
    return f"{value[:2]}:{value[2:]}"


def _fetch(station_id: str) -> str:
    url = f"{BASE}?query_type=search&station={station_id}"
    last: Exception | None = None
    for attempt in range(3):
        try:
            response = requests.get(url, headers=HEADERS, timeout=30)
            response.raise_for_status()
            return response.content.decode("utf-8", errors="replace")
        except requests.RequestException as exc:
            last = exc
            time.sleep(1 + attempt)
    raise RuntimeError(f"station {station_id}: {last}")


def _parse(text: str) -> dict:
    text = COMMENT.sub("", text)
    opened = OPEN.search(text)
    lines: dict[str, list[dict]] = {}
    parts = SECTION.split(text)
    for index in range(1, len(parts), 2):
        line_code = parts[index]
        body = parts[index + 1]
        rows = []
        seen = set()
        for dest_id, first, last in ROW.findall(body):
            if dest_id in seen:
                continue
            seen.add(dest_id)
            rows.append(
                {
                    "dest_id": dest_id,
                    "first": _clock(first),
                    "last": _clock(last),
                }
            )
        if rows:
            lines[line_code] = rows
    return {
        "open": f"{opened.group(1)}-{opened.group(2)}" if opened else None,
        "lines": lines,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--station", help="only fetch this station id")
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()

    rows = mtr_core.lines_and_stations()["data"]
    stations: dict[str, str] = {}
    for row in rows:
        stations.setdefault(row["id"], row["name_zh"])
    ids = [args.station] if args.station else sorted(stations, key=int)
    if args.limit:
        ids = ids[: args.limit]

    result: dict[str, dict] = {}
    for count, station_id in enumerate(ids, 1):
        text = _fetch(station_id)
        parsed = _parse(text)
        result[station_id] = {
            "name_zh": stations.get(station_id),
            "open": parsed["open"],
            "lines": parsed["lines"],
        }
        print(f"{count}/{len(ids)} station {station_id} {stations.get(station_id)}")
        time.sleep(0.15)

    payload = {
        "dataset_id": DATASET,
        "endpoint": BASE,
        "retrieved_at": now_hkt(),
        "data_at": None,
        "update_frequency": "as and when necessary",
        "note": (
            "MTR website service-hours pages, one request per station. "
            "First and last departures are published; headway is not. "
            "Airport Express first/last is from the MTR timetable page."
        ),
        "stations": result,
    }
    for station_id, rows in AEL_SERVICE.items():
        station = result.setdefault(
            station_id,
            {"name_zh": stations.get(station_id), "open": None, "lines": {}},
        )
        line_rows = station["lines"].setdefault("AEL", [])
        existing = {row["dest_id"] for row in line_rows}
        for dest_id, first, last in rows:
            if dest_id in existing:
                continue
            line_rows.append({"dest_id": dest_id, "first": first, "last": last})
    SNAPSHOT.parent.mkdir(parents=True, exist_ok=True)
    SNAPSHOT.write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    print(f"{len(result)} stations -> {SNAPSHOT}")


if __name__ == "__main__":
    main()
