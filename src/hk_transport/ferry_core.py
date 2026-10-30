"""Ferry core: one TD file, one function, no operator attribution.

The Transport Department lists every ferry route with fares, stop order and
pier coordinates, but it does not say which company runs a route. Answers say
the route name and the piers, never "this is Sun Ferry".
"""

from __future__ import annotations

from hk_transport import _td_stops
from hk_transport._result import envelope

FERRY_URL = f"{_td_stops.BASE}/JSON_FERRY.json"
DATASET_ID = _td_stops.DATASET_ID

NOTE = (
    "渡輪航線同票價來自運輸署，成人全程價，唔係分段。"
    "數據冇營辦商欄，所以唔會講「呢班係邊間公司」。"
    "班次、尾班船同到站時間冇數據。"
)

_memory: dict | None = None


def clear_cache() -> None:
    global _memory
    _memory = None


def _load() -> dict:
    global _memory
    if _memory is None:
        _memory = _td_stops.stop_rows(FERRY_URL)
    return _memory


def ferry_stops() -> dict:
    """全部渡輪航線的碼頭次序，一個碼頭一列，帶 WGS84 座標。

    資料集 `hk-td-tis_3`，端點 `JSON_FERRY.json`，30 日快取。
    用法：`ferry_stops()`。
    市民會問：呢條航線停邊幾個碼頭？

    102 個航線變體、68 個碼頭。跨海航線通常只有兩個碼頭。
    """
    loaded = _load()
    return envelope(
        dataset_id=DATASET_ID,
        endpoint=FERRY_URL,
        retrieved_at=loaded["retrieved_at"],
        data_at=loaded["data_at"],
        update_frequency="biweekly",
        data=loaded["rows"],
        note=NOTE,
    )


def ferry_routes() -> dict:
    """渡輪航線同成人票價，一個變體一列。

    由 `ferry_stops()` 去重而來。用法：`ferry_routes()`。
    市民會問：有邊幾條渡輪航線？幾多錢？

    航線名係「起點 - 終點」；同一對碼頭可以有兩個方向。
    """
    seen: dict[tuple, dict] = {}
    for row in _load()["rows"]:
        key = (row["route_id"], row["route_seq"], row["service_mode"], row["special_type"])
        seen.setdefault(
            key,
            {
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
            },
        )
    loaded = _load()
    return envelope(
        dataset_id=DATASET_ID,
        endpoint=FERRY_URL,
        retrieved_at=loaded["retrieved_at"],
        data_at=loaded["data_at"],
        update_frequency="biweekly",
        data=list(seen.values()),
        note=NOTE,
    )
