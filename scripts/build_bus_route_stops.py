"""Rebuild the KMB route-stop snapshot.

    uv run python scripts/build_bus_route_stops.py

One request downloads every KMB and LWB route-stop row and writes the compact
snapshot used by `bus_core.kmb_route_stops_all`. Run it when routes change; the
committed file is what the tools read at run time.
"""

from __future__ import annotations

import json
from pathlib import Path

from hk_transport import bus_core

ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT = ROOT / "src" / "hk_transport" / "data" / "bus_route_stops.json"


def main() -> None:
    live = bus_core.kmb_download_route_stops()
    groups: dict[tuple[str, str, str], list[tuple[float, str]]] = {}
    for row in live["data"]:
        key = (row["route"], row["direction"], row["service_type"])
        groups.setdefault(key, []).append((row["seq"] or 0, row["stop"]))
    variants = {}
    for (route, direction, service), stops in groups.items():
        stops.sort()
        variants[f"{route}|{direction}|{service}"] = [stop for _, stop in stops]
    payload = {
        "dataset_id": bus_core.KMB_DATASET,
        "endpoint": live["endpoint"],
        "retrieved_at": live["retrieved_at"],
        "data_at": live["data_at"],
        "variants": variants,
    }
    SNAPSHOT.parent.mkdir(parents=True, exist_ok=True)
    SNAPSHOT.write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    print(f"{len(variants)} variants, {sum(len(v) for v in variants.values())} stops -> {SNAPSHOT}")


if __name__ == "__main__":
    main()
