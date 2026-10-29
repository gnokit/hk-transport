"""Lands Department Address Lookup Service.

One function for the whole address database. It does not pick the nearest
station or join the result to a transport table.
"""

from __future__ import annotations

from urllib.parse import urlencode

import requests

from hk_transport._result import MtrError, envelope, now_hkt

DATASET_ID = "hk-dpo-als_01-als"
LOOKUP_URL = "https://www.als.gov.hk/lookup"


def _blank(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _street_number(chinese: dict, english: dict, key: str) -> str | None:
    return _blank(chinese.get(key)) or _blank(english.get(key))


def _match(item: dict) -> dict:
    premises = (item.get("Address") or {}).get("PremisesAddress") or {}
    english = premises.get("EngPremisesAddress") or {}
    chinese = premises.get("ChiPremisesAddress") or {}
    english_street = english.get("EngStreet") or {}
    chinese_street = chinese.get("ChiStreet") or {}
    geo = premises.get("GeospatialInformation") or {}
    score = (item.get("ValidationInformation") or {}).get("Score")
    return {
        "building_zh": _blank(chinese.get("BuildingName")),
        "building_en": _blank(english.get("BuildingName")),
        "estate_zh": _blank((chinese.get("ChiEstate") or {}).get("EstateName")),
        "estate_en": _blank((english.get("EngEstate") or {}).get("EstateName")),
        "street_zh": _blank(chinese_street.get("StreetName")),
        "street_en": _blank(english_street.get("StreetName")),
        "number_from": _street_number(chinese_street, english_street, "BuildingNoFrom"),
        "number_to": _street_number(chinese_street, english_street, "BuildingNoTo"),
        "district_zh": _blank((chinese.get("ChiDistrict") or {}).get("DcDistrict")),
        "district_en": _blank((english.get("EngDistrict") or {}).get("DcDistrict")),
        "region_zh": _blank(chinese.get("Region")),
        "region_en": _blank(english.get("Region")),
        "latitude": _blank(geo.get("Latitude")),
        "longitude": _blank(geo.get("Longitude")),
        "northing": _blank(geo.get("Northing")),
        "easting": _blank(geo.get("Easting")),
        "geo_address": _blank(premises.get("GeoAddress")),
        "score": score if isinstance(score, (int, float)) else None,
    }


def address_lookup(query: str, n: int | None = None) -> dict:
    """查一個地點或地址，交還匹配結果同座標。

    提供中英文大廈、屋苑、街道、門牌、地區，以及緯度、經度、北距、東距。
    資料集 `hk-dpo-als_01-als`，地政總署地址查詢服務。
    端點 `https://www.als.gov.hk/lookup`。要帶 `Accept: application/json`。
    舊網址 `als.ogcio.gov.hk` 已停用。

    用法：`address_lookup("元州商場")`。
    市民會問：這個地方在哪？座標是多少？

    查詢沒有數據時間。`score` 是地政總署的匹配分，不是距離。
    服務會為對不上的字串仍交還一些建議，要看分數。這裡不挑選最近的車站。
    """
    params = {"q": query}
    if n is not None:
        params["n"] = str(n)
    endpoint = f"{LOOKUP_URL}?{urlencode(params)}"
    try:
        response = requests.get(
            LOOKUP_URL,
            params=params,
            headers={"Accept": "application/json"},
            timeout=20,
        )
        response.raise_for_status()
        payload = response.json()
    except requests.RequestException as exc:
        raise MtrError(str(exc), dataset_id=DATASET_ID, endpoint=endpoint) from exc
    except ValueError as exc:
        raise MtrError(str(exc), dataset_id=DATASET_ID, endpoint=endpoint) from exc
    if not isinstance(payload, dict):
        raise MtrError("回應不是 JSON 物件", dataset_id=DATASET_ID, endpoint=endpoint)
    suggested = payload.get("SuggestedAddress") or []
    matches = [_match(item) for item in suggested if isinstance(item, dict)]
    return envelope(
        dataset_id=DATASET_ID,
        endpoint=endpoint,
        retrieved_at=now_hkt(),
        data_at=None,
        update_frequency="realtime",
        data=matches,
        note=None if matches else "沒有匹配地址。",
    )
