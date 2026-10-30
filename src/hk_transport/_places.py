"""Place resolution and walking helpers shared by the answer layers.

Both the bus and the minibus layers ask the same three questions: how far
apart are two points, which stops are inside a walking radius, and what place
does this name mean. They live here so the two answers cannot drift apart.

Nothing here picks a route or reads a timetable.
"""

from __future__ import annotations

import math

from hk_transport import als, geocode


def distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Straight-line metres between two points."""
    radius = 6371000
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    delta_phi = phi2 - phi1
    delta_lambda = math.radians(lon2 - lon1)
    a = (
        math.sin(delta_phi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2) ** 2
    )
    return 2 * radius * math.asin(math.sqrt(a))


def stops_within(
    stops: dict[str, dict], latitude: float, longitude: float, radius: float
) -> dict[str, float]:
    """Every stop inside the radius, with its straight-line distance."""
    found: dict[str, float] = {}
    for stop_id, row in stops.items():
        if row["latitude"] is None or row["longitude"] is None:
            continue
        gap = distance(latitude, longitude, row["latitude"], row["longitude"])
        if gap <= radius:
            found[stop_id] = gap
    return found


def nearest_stop(
    stops: dict[str, dict], latitude: float, longitude: float
) -> tuple[float, dict] | None:
    """The closest stop and its straight-line distance, whatever the radius."""
    best: tuple[float, dict] | None = None
    for row in stops.values():
        if row["latitude"] is None or row["longitude"] is None:
            continue
        gap = distance(latitude, longitude, row["latitude"], row["longitude"])
        if best is None or gap < best[0]:
            best = (gap, row)
    return best


def outside(
    stops: dict[str, dict], point: dict, radius: int, subject: str = "站"
) -> str:
    """Say there is no stop in the radius, and how far the nearest one is.

    A bare "no stop" leaves the caller unable to tell a wrong place name from
    a place with no service. The nearest distance separates the two.
    """
    nearest = nearest_stop(stops, point["latitude"], point["longitude"])
    head = f"{radius} 米內沒有{subject}。"
    if nearest is None:
        return head
    gap, row = nearest
    return f"{head}最近的是{row['name_zh']}，直線 {round(gap)} 米。"


def name_rank(query: str, row: dict) -> int:
    """How well a search result's own name matches what was asked for."""
    folded = query.casefold()
    names = [name.casefold() for name in (row.get("name_zh"), row.get("name_en")) if name]
    if any(name == folded for name in names):
        return 0
    if any(name.startswith(folded) for name in names):
        return 1
    if any(folded in name for name in names):
        return 2
    return 3


def place(query: str, stops: dict[str, dict]) -> tuple[dict | None, str | None]:
    """Resolve a stop name, a stop id, or a place name to one point.

    A stop name or id wins outright: those are the operator's own names. A
    place goes to the Lands Department place search, which knows place and
    facility names that the address lookup does not. The address lookup is
    the fallback for a street address the place search cannot place.
    """
    text = query.strip()
    exact = [
        row
        for row in stops.values()
        if row["stop"] == text or row["name_zh"] == text or row["name_en"] == text
    ]
    if exact and exact[0]["latitude"] is not None:
        row = exact[0]
        return (
            {
                "query": text,
                "resolved_as": "stop",
                "name_zh": row["name_zh"],
                "name_en": row["name_en"],
                "latitude": row["latitude"],
                "longitude": row["longitude"],
            },
            None,
        )
    found = geocode.place_search(text)
    matches = [row for row in (found["data"] or []) if row["latitude"] is not None]
    if matches:
        matches.sort(key=lambda row: name_rank(text, row))
        best = matches[0]
        point = {
            "query": text,
            "resolved_as": "place",
            "name_zh": best["name_zh"],
            "name_en": best["name_en"],
            "district_zh": best["district_zh"],
            "latitude": best["latitude"],
            "longitude": best["longitude"],
        }
        other = [
            {"name_zh": row["name_zh"], "district_zh": row["district_zh"]}
            for row in matches[1:]
            if row["district_zh"] != best["district_zh"]
        ][:2]
        if other:
            point["also_matched"] = other
        return point, None
    found = als.address_lookup(text, n=5)
    matches = [
        item for item in (found["data"] or []) if item.get("latitude") and item.get("longitude")
    ]
    if not matches:
        return None, f"找不到地方：{text}"
    matches.sort(key=lambda item: item.get("score") or 0, reverse=True)
    best = matches[0]
    return (
        {
            "query": text,
            "resolved_as": "address",
            "name_zh": best.get("building_zh") or best.get("street_zh"),
            "name_en": best.get("building_en") or best.get("street_en"),
            "district_zh": best.get("district_zh"),
            "latitude": float(best["latitude"]),
            "longitude": float(best["longitude"]),
            "score": best.get("score"),
        },
        None,
    )
