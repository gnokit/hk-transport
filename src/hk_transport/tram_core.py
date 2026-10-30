"""Tram and Peak Tram core: one file each, one function each.

Both are published by the Transport Department in the same stop-level GeoJSON
shape as the buses. Nothing here resolves a place or picks a route.
"""

from __future__ import annotations

from hk_transport import _td_stops
from hk_transport._result import envelope

TRAM_URL = f"{_td_stops.BASE}/JSON_TRAM.json"
PEAK_URL = f"{_td_stops.BASE}/JSON_PTRAM.json"
DATASET_ID = _td_stops.DATASET_ID

NOTE = (
    "香港電車係固定收費，唔係分段；班次同到站時間冇數據。"
    "東行同西行係兩個站，唔可以當同一個。"
    "山頂纜車係另一份檔案，站少但票價高。"
)

_memory: dict[str, dict] = {}


def clear_cache() -> None:
    _memory.clear()


def _load(url: str) -> dict:
    if url not in _memory:
        _memory[url] = _td_stops.stop_rows(url)
    return _memory[url]


def _envelope(url: str, rows: list[dict], note: str) -> dict:
    loaded = _load(url)
    return envelope(
        dataset_id=DATASET_ID,
        endpoint=url,
        retrieved_at=loaded["retrieved_at"],
        data_at=loaded["data_at"],
        update_frequency="biweekly",
        data=rows,
        note=note,
    )


def tram_stops() -> dict:
    """香港電車全部路線的站序，一站一列，帶 WGS84 座標。

    資料集 `hk-td-tis_3`，端點 `JSON_TRAM.json`，30 日快取。
    用法：`tram_stops()`。
    市民會問：電車停邊個站？呢個站有邊幾條線？

    12 個變體、117 個站。東行同西行分開列，名稱會寫「(東行方向)」。
    """
    return _envelope(TRAM_URL, _load(TRAM_URL)["rows"], NOTE)


def tram_routes() -> dict:
    """香港電車的路線同成人全程車費，一個變體一列。

    由 `tram_stops()` 去重而來。用法：`tram_routes()`。
    市民會問：有邊幾條電車線？幾多錢？

    票價係全程一個價，落車再上車要再付。
    """
    rows = [
        {
            "company": row["company"],
            "route": row["route"],
            "route_en": row["route_en"],
            "route_id": row["route_id"],
            "route_seq": row["route_seq"],
            "service_mode": row["service_mode"],
            "special_type": row["special_type"],
            "origin_zh": row["origin_zh"],
            "dest_zh": row["dest_zh"],
            "fare": row["fare"],
            "journey_time_minutes": row["journey_time_minutes"],
            "remark": row["remark"],
        }
        for row in _load(TRAM_URL)["rows"]
    ]
    return _envelope(
        TRAM_URL,
        _td_stops.dedupe_variants(
            rows, ("route_id", "route_seq", "service_mode", "special_type")
        ),
        NOTE,
    )


def peak_tram_stops() -> dict:
    """山頂纜車兩個方向的站序同座標。

    資料集 `hk-td-tis_3`，端點 `JSON_PTRAM.json`。
    用法：`peak_tram_stops()`。
    市民會問：山頂纜車停邊幾個站？

    只有 6 個站、2 個方向；票價遠高於電車。
    """
    return _envelope(
        PEAK_URL,
        _load(PEAK_URL)["rows"],
        "山頂纜車只有 6 個站；票價係全程價，唔係分段。",
    )


def peak_tram_routes() -> dict:
    """山頂纜車的路線同票價。

    由 `peak_tram_stops()` 去重而來。用法：`peak_tram_routes()`。
    市民會問：山頂纜車幾多錢？
    """
    rows = [
        {
            "route": row["route"],
            "route_id": row["route_id"],
            "route_seq": row["route_seq"],
            "service_mode": row["service_mode"],
            "special_type": row["special_type"],
            "origin_zh": row["origin_zh"],
            "dest_zh": row["dest_zh"],
            "fare": row["fare"],
            "journey_time_minutes": row["journey_time_minutes"],
        }
        for row in _load(PEAK_URL)["rows"]
    ]
    return _envelope(
        PEAK_URL,
        _td_stops.dedupe_variants(
            rows, ("route_id", "route_seq", "service_mode", "special_type")
        ),
        "山頂纜車票價係全程價，唔係分段。",
    )
