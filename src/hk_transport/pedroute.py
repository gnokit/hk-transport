"""Lands Department 3D pedestrian route search.

One function for walking between two points. The service solves on the 3D
Pedestrian Network, which covers streets and, inside MTR stations, indoor
levels. It returns a real path length and a walking time, not a straight
line, so the answer no longer has to invent a walking speed.

The network does not cover every path in Hong Kong. A rural pair such as
南生圍 to 壆圍 returns "No solution found", and the caller must fall back to
a straight-line distance and say so.
"""

from __future__ import annotations

import json
from urllib.parse import quote

from hk_transport._http import fetch_json
from hk_transport._result import MtrError, envelope
from hk_transport._values import number

DATASET_ID = "hk-landsd-mapapi-3d-pedestrian-route-search"
SOLVE_URL = "https://mapapi.hkmapservice.gov.hk/PedRoute/NAServer/route/solve"

NOTE = (
    "步行距離同時間來自地政總署 3D 行人路網，不是直線距離。"
    "路網未覆蓋全部地方，冇路線時會講明並改用直線距離。"
    "時間是路網的行人估算，不是官方承諾。"
)


def _stops(origin: tuple[float, float], destination: tuple[float, float]) -> str:
    payload = {
        "features": [
            {
                "attributes": {"Name": "origin"},
                "geometry": {
                    "spatialReference": {"latestWkid": 4326},
                    "x": origin[1],
                    "y": origin[0],
                },
            },
            {
                "attributes": {"Name": "destination"},
                "geometry": {
                    "spatialReference": {"latestWkid": 4326},
                    "x": destination[1],
                    "y": destination[0],
                },
            },
        ]
    }
    return quote(json.dumps(payload))


def walk_route(
    origin_lat: float,
    origin_lon: float,
    destination_lat: float,
    destination_lon: float,
) -> dict:
    """兩點之間的步行路線距離同時間。

    資料集 `hk-landsd-mapapi-3d-pedestrian-route-search`，端點
    `https://mapapi.hkmapservice.gov.hk/PedRoute/NAServer/route/solve`。
    不快取。用法：`walk_route(22.3383, 114.15502, 22.3356, 114.1555)`。
    市民會問：由呢度行去車站幾遠？要行幾耐？

    交還 `metres` 同 `minutes`；路網冇路線時 `found` 是 false，兩個數字都是
    null，並在 note 講明要改用直線距離。唔可以用直線距離假裝成步行路線。
    """
    stops = _stops((origin_lat, origin_lon), (destination_lat, destination_lon))
    url = (
        f"{SOLVE_URL}?stops={stops}"
        "&travelMode=1&directionsLanguage=zh-HK&outSR=4326&f=json&returnZ=true"
        f"&directionStyleName={quote('NA Campus')}"
    )
    payload, retrieved_at = fetch_json(url, dataset_id=DATASET_ID, cache=False, timeout=20)
    if not isinstance(payload, dict):
        raise MtrError("行人路線不是預期的 JSON", dataset_id=DATASET_ID, endpoint=url)
    if payload.get("error"):
        message = (payload.get("error") or {}).get("details") or []
        return envelope(
            dataset_id=DATASET_ID,
            endpoint=url,
            retrieved_at=retrieved_at,
            data_at=None,
            update_frequency="realtime",
            data={"found": False, "metres": None, "minutes": None},
            note=NOTE + "這次路網找不到路線：" + ("；".join(message) or "沒有解"),
        )
    routes = (payload.get("routes") or {}).get("features") or []
    if not routes:
        return envelope(
            dataset_id=DATASET_ID,
            endpoint=url,
            retrieved_at=retrieved_at,
            data_at=None,
            update_frequency="realtime",
            data={"found": False, "metres": None, "minutes": None},
            note=NOTE + "這次路網交還空的結果。",
        )
    attributes = routes[0].get("attributes") or {}
    return envelope(
        dataset_id=DATASET_ID,
        endpoint=url,
        retrieved_at=retrieved_at,
        data_at=None,
        update_frequency="realtime",
        data={
            "found": True,
            "metres": number(attributes.get("Total_Length")),
            "minutes": number(attributes.get("Total_Time")),
        },
        note=NOTE,
    )
