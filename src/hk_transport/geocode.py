"""Lands Department GeoInfo Map location search.

One function for the place-name gazetteer. Addresses, building names, place
names and facility names all come from this one endpoint. Nothing here knows
about stations, stops or routes.

The response carries HK1980 grid easting and northing, not latitude and
longitude. The conversion uses EPSG:2326 to EPSG:4326 and happens here so
callers only ever see ordinary coordinates.
"""

from __future__ import annotations

from urllib.parse import urlencode

from hk_transport._http import fetch_json
from hk_transport._result import MtrError, envelope
from hk_transport._values import blank, number

DATASET_ID = "hk-landsd-openmap-development-location-search-api"
SEARCH_URL = "https://www.map.gov.hk/gs/api/v1.0.0/locationSearch"

NOTE = (
    "地點搜尋按相關度排序，第一項唔一定係你想要嘅地方；同名設施（例如 AED、智郵站）"
    "會排在地方本身前面。座標由香港1980方格網轉做經緯度，回應本身只有東距同北距。"
)

_TRANSFORMER = None


def _to_latlon(easting: float, northing: float) -> tuple[float, float]:
    """HK1980 grid easting/northing to WGS84 latitude and longitude."""
    global _TRANSFORMER
    if _TRANSFORMER is None:
        from pyproj import Transformer

        _TRANSFORMER = Transformer.from_crs("EPSG:2326", "EPSG:4326", always_xy=True)
    longitude, latitude = _TRANSFORMER.transform(easting, northing)
    return latitude, longitude


def _row(item: dict) -> dict:
    easting = number(item.get("x"))
    northing = number(item.get("y"))
    latitude = longitude = None
    if easting is not None and northing is not None:
        latitude, longitude = _to_latlon(easting, northing)
    return {
        "name_zh": blank(item.get("nameZH")),
        "name_en": blank(item.get("nameEN")),
        "address_zh": blank(item.get("addressZH")),
        "address_en": blank(item.get("addressEN")),
        "district_zh": blank(item.get("districtZH")),
        "district_en": blank(item.get("districtEN")),
        "easting": easting,
        "northing": northing,
        "latitude": latitude,
        "longitude": longitude,
    }


def place_search(query: str, limit: int = 5) -> dict:
    """查一個地名、地址、大廈名或設施名，交還座標。

    資料集 `hk-landsd-openmap-development-location-search-api`，
    地政總署測繪處 GeoInfo Map 的地點搜尋。
    端點 `https://www.map.gov.hk/gs/api/v1.0.0/locationSearch`，參數 `q`。
    用法：`place_search("南生圍")`、`place_search("元州街303號")`。

    市民會問：呢個地方喺邊？這個名字對應哪一棟大廈、哪條街？

    回應的 x、y 是香港1980方格網的東距、北距，不是經緯度；這裡已轉成
    緯度經度，兩者都交還。站名同地名係兩份數據，唔可以互相代替。
    官方要求唔可以短時間內大量請求，所以一次查詢只發一個請求。
    """
    text = (query or "").strip()
    if not text:
        return envelope(
            dataset_id=DATASET_ID,
            endpoint=SEARCH_URL,
            retrieved_at=None,
            data_at=None,
            update_frequency="as and when necessary",
            data=None,
            note="要給一個地點名。",
        )
    url = f"{SEARCH_URL}?{urlencode({'q': text})}"
    payload, retrieved_at = fetch_json(url, dataset_id=DATASET_ID, cache=False)
    if not isinstance(payload, list):
        raise MtrError("地點搜尋不是預期的 JSON", dataset_id=DATASET_ID, endpoint=url)
    rows = [_row(item) for item in payload if isinstance(item, dict)]
    rows = [row for row in rows if row["latitude"] is not None]
    return envelope(
        dataset_id=DATASET_ID,
        endpoint=url,
        retrieved_at=retrieved_at,
        data_at=None,
        update_frequency="as and when necessary",
        data=rows[:limit] if limit else rows,
        note=NOTE,
    )
