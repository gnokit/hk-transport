"""Heavy-rail station exits from a one-year Lands Department snapshot.

Location Search returns HK1980 grid easting and northing. Latitude and
longitude were converted once with the Lands Department transform API and
stored beside them. Reading this table does not call the network.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

from hk_transport._names import station_name as _station_name
from hk_transport._result import HKT, MtrError, envelope

DATASET_ID = "hk-landsd-openmap-development-location-search-api"
TRANSFORM_DATASET_ID = "hk-landsd-openmap-coordinates-transformation-api"
SEARCH_ENDPOINT = "https://www.map.gov.hk/gs/api/v1.0.0/locationSearch"
TRANSFORM_ENDPOINT = "https://www.geodetic.gov.hk/transform/v2/?inSys=hkgrid&outSys=wgsgeog"
_YEAR = timedelta(days=365)


def _path() -> Path:
    return Path(__file__).resolve().parent / "data" / "mtr_exits.json"


def _load() -> dict:
    path = _path()
    endpoint = SEARCH_ENDPOINT
    if not path.is_file():
        raise MtrError("找不到出入口快照", dataset_id=DATASET_ID, endpoint=endpoint)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise MtrError(str(exc), dataset_id=DATASET_ID, endpoint=endpoint) from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("exits"), list):
        raise MtrError("出入口快照不是預期的 JSON", dataset_id=DATASET_ID, endpoint=endpoint)
    return payload


def _stale(retrieved_at: str) -> bool:
    fetched = datetime.fromisoformat(retrieved_at)
    if fetched.tzinfo is None:
        fetched = fetched.replace(tzinfo=HKT)
    return datetime.now(HKT) - fetched >= _YEAR


def _matches_station(row: dict, query: str) -> bool:
    """One snapshot row belongs to a station asked for by name, code, or id."""
    folded = query.casefold()
    if row.get("station_zh") == query:
        return True
    if (row.get("station_en") or "").casefold() == folded:
        return True
    if folded.upper() in {str(code).upper() for code in row.get("station_codes") or []}:
        return True
    return query in {str(item) for item in row.get("station_ids") or []}


def mtr_exits(station: str) -> dict:
    """交還一個重鐵站的出入口座標。

    資料集 `hk-landsd-openmap-development-location-search-api`。
    端點 `https://www.map.gov.hk/gs/api/v1.0.0/locationSearch`。
    每個站曾以 `港鐵{中文站名}站 出口` 搜尋一次。只保留站名對得上、名稱以「出口」結尾的結果，包括「進出口」和「出口」。
    舊網址 `geodata.gov.hk` 不使用。

    搜尋回應的 x、y 是香港1980方格網的東距、北距，不是經緯度。
    緯度、經度來自 `hk-landsd-openmap-coordinates-transformation-api`，
    端點 `https://www.geodetic.gov.hk/transform/v2/?inSys=hkgrid&outSys=wgsgeog`。

    出入口幾乎不變。這份快照約一年內重用，查詢時不重新下載，也不寫入 `.cache/`。
    超過一年仍交還同一份，並在 note 說明。

    用法：`mtr_exits("金鐘")`。站名一定要給，可以是中文、英文、車站編號或代碼；
    空白會報錯。整份快照只在模組內部用，不經這個函式交還。
    市民會問：這個站有哪些出口？出口的座標是多少？

    這不是港鐵公布的出口名冊。輕鐵站不在這份表。沒有出口編號的出入口，`exit` 留空。
    青衣、九龍、香港在機場快線和東涌線各有一個車站編號，出入口是同一組，`station_ids` 兩個都列。
    """
    station = _station_name(station or "")
    if not station:
        raise MtrError(
            "要給一個站名", dataset_id=DATASET_ID, endpoint=SEARCH_ENDPOINT
        )
    snapshot = _load()
    retrieved_at = snapshot.get("retrieved_at")
    if not isinstance(retrieved_at, str) or not retrieved_at:
        raise MtrError("出入口快照沒有擷取時間", dataset_id=DATASET_ID, endpoint=SEARCH_ENDPOINT)
    missing = snapshot.get("missing_stations") or []
    if not isinstance(missing, list):
        raise MtrError("出入口快照的缺站名單不是清單", dataset_id=DATASET_ID, endpoint=SEARCH_ENDPOINT)
    note = (
        "重鐵站出入口是地政總署地理位置搜尋的快照，約一年內當不變，查詢時不重新下載。"
        "東距和北距是香港1980方格網。緯度經度由地政總署坐標轉換而來，搜尋結果本身沒有經緯度。"
        "這不是港鐵公布的出口名冊。"
    )
    if _stale(retrieved_at):
        note += "這份快照已超過一年。"
    if missing:
        note += "這次沒有進出口的車站：" + "、".join(str(name) for name in missing) + "。"
    rows = snapshot["exits"]
    if station is not None:
        rows = [row for row in rows if _matches_station(row, station)]
        note += f"只列出「{station}」的出入口。"
        if not rows:
            note += f"快照沒有這個站的出入口：{station}。"
    return envelope(
        dataset_id=[DATASET_ID, TRANSFORM_DATASET_ID],
        endpoint=[SEARCH_ENDPOINT, TRANSFORM_ENDPOINT],
        retrieved_at=retrieved_at,
        data_at=None,
        update_frequency="yearly",
        data=rows or None,
        note=note,
    )


def mtr_station_points() -> dict:
    """每個重鐵站一個點，由該站所有出口的座標平均而來。

    資料集 `hk-landsd-openmap-development-location-search-api`，
    端點 `https://www.map.gov.hk/gs/api/v1.0.0/locationSearch`（快照）。
    用法：`mtr_station_points()`。
    市民會問：這個站喺邊？行程要由邊個站開始？

    港鐵沒有公布單一站中心座標，所以這裡用出口平均，並在 note 講明。
    一個站有多個編號（機場快線香港站 44、東涌線香港站 39）會各自成一點。
    這份表是約一年的快照，查詢時不重新下載。
    """
    snapshot = _load()
    retrieved_at = snapshot.get("retrieved_at") or ""
    buckets: dict[str, list[tuple[float, float]]] = {}
    names: dict[str, str] = {}
    for row in snapshot["exits"]:
        latitude, longitude = row.get("latitude"), row.get("longitude")
        if latitude is None or longitude is None:
            continue
        for station_id in row.get("station_ids") or []:
            buckets.setdefault(station_id, []).append((latitude, longitude))
            names.setdefault(station_id, row.get("station_zh"))
    data = [
        {
            "station_id": station_id,
            "name_zh": names.get(station_id),
            "latitude": round(sum(p[0] for p in points) / len(points), 6),
            "longitude": round(sum(p[1] for p in points) / len(points), 6),
            "exits": len(points),
        }
        for station_id, points in sorted(buckets.items(), key=lambda item: int(item[0]) if item[0].isdigit() else 0)
    ]
    note = (
        "站中心是該站所有出口座標的平均，港鐵沒有公布站中心座標。"
        "這份快照約一年內重用，查詢時不重新下載。"
    )
    if _stale(retrieved_at):
        note += "這份快照已超過一年。"
    return envelope(
        dataset_id=DATASET_ID,
        endpoint=SEARCH_ENDPOINT,
        retrieved_at=retrieved_at,
        data_at=None,
        update_frequency="yearly",
        data=data,
        note=note,
    )
