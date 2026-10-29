"""Transport Department traffic notices.

Two functions, one resource each. Both cover every mode, so later phases
reuse them. Neither call filters for the MTR, and neither is cached.
Line-level MTR status stays on `next_train`.
"""

from __future__ import annotations

import re
from html.parser import HTMLParser
from xml.etree import ElementTree

import requests

from hk_transport._result import MtrError, as_hkt, envelope, now_hkt

NEWS_DATASET = "hk-td-tis_19-special-traffic-news-v2"
NEWS_URL = "https://www.td.gov.hk/tc/special_news/trafficnews.xml"
ARRANGEMENTS_DATASET = "hk-td-tis_22-traffic-notices"
ARRANGEMENTS_URL = (
    "https://www.td.gov.hk/datagovhk_tis/traffic-notices/"
    "Special_Traffic_and_Transport_Arrangement.xml"
)

_BLOCK = {"p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "table"}


class _Text(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag in _BLOCK:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in _BLOCK:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        self.parts.append(data)


def _blank(value: str | None) -> str | None:
    if value is None:
        return None
    text = value.strip()
    return text or None


def _plain(value: str | None) -> str | None:
    text = _blank(value)
    if text is None:
        return None
    parser = _Text()
    parser.feed(text)
    parser.close()
    cleaned = "".join(parser.parts).replace("\xa0", " ")
    cleaned = re.sub(r"[ \t]+\n", "\n", cleaned)
    cleaned = re.sub(r"\n[ \t]+", "\n", cleaned)
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return _blank(cleaned)


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _fields(element: ElementTree.Element) -> dict[str, str]:
    return {_local(child.tag): child.text or "" for child in element}


def _xml(url: str, *, dataset_id: str) -> ElementTree.Element:
    try:
        response = requests.get(url, timeout=30, headers={"User-Agent": "hk-transport"})
        response.raise_for_status()
        payload = response.content
    except requests.RequestException as exc:
        raise MtrError(str(exc), dataset_id=dataset_id, endpoint=url) from exc
    try:
        return ElementTree.fromstring(payload)
    except ElementTree.ParseError as exc:
        raise MtrError(str(exc), dataset_id=dataset_id, endpoint=url) from exc


def _float(value: str | None) -> float | None:
    text = _blank(value)
    if text is None:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _news_item(fields: dict[str, str]) -> dict:
    return {
        "incident_number": _blank(fields.get("INCIDENT_NUMBER")),
        "id": _blank(fields.get("ID")),
        "heading_zh": _blank(fields.get("INCIDENT_HEADING_CN")),
        "heading_en": _blank(fields.get("INCIDENT_HEADING_EN")),
        "detail_zh": _blank(fields.get("INCIDENT_DETAIL_CN")),
        "detail_en": _blank(fields.get("INCIDENT_DETAIL_EN")),
        "location_zh": _blank(fields.get("LOCATION_CN")),
        "location_en": _blank(fields.get("LOCATION_EN")),
        "district_zh": _blank(fields.get("DISTRICT_CN")),
        "district_en": _blank(fields.get("DISTRICT_EN")),
        "direction_zh": _blank(fields.get("DIRECTION_CN")),
        "direction_en": _blank(fields.get("DIRECTION_EN")),
        "announcement_at": as_hkt(_blank(fields.get("ANNOUNCEMENT_DATE"))),
        "status_zh": _blank(fields.get("INCIDENT_STATUS_CN")),
        "status_en": _blank(fields.get("INCIDENT_STATUS_EN")),
        "near_landmark_zh": _blank(fields.get("NEAR_LANDMARK_CN")),
        "near_landmark_en": _blank(fields.get("NEAR_LANDMARK_EN")),
        "between_landmark_zh": _blank(fields.get("BETWEEN_LANDMARK_CN")),
        "between_landmark_en": _blank(fields.get("BETWEEN_LANDMARK_EN")),
        "content_zh": _blank(fields.get("CONTENT_CN")),
        "content_en": _blank(fields.get("CONTENT_EN")),
        "latitude": _float(fields.get("LATITUDE")),
        "longitude": _float(fields.get("LONGITUDE")),
    }


def special_traffic_news() -> dict:
    """交還運輸署現時的特別交通消息。

    資料集 `hk-td-tis_19-special-traffic-news-v2`。
    端點 `https://www.td.gov.hk/tc/special_news/trafficnews.xml`。
    英文網址目前交還同一份檔。繁體中文在 `CONTENT_CN`，英文在 `CONTENT_EN`。
    第一代 `resource.data.one.gov.hk` 不使用。

    用法：`special_traffic_news()`。
    市民會問：而家有什麼特別交通消息？有沒有封路或改道？

    這是全港消息，路面、巴士、渡輪、港鐵都可能出現，查詢時不按關鍵字篩選。
    不快取。港鐵某一線、某一站的車務狀態仍看 `mtr_next_train`，不在這裡重包。
    沒有座標時緯度經度留空。
    """
    root = _xml(NEWS_URL, dataset_id=NEWS_DATASET)
    items = [
        _news_item(_fields(element))
        for element in root
        if _local(element.tag) == "message"
    ]
    announcements = [item["announcement_at"] for item in items if item["announcement_at"]]
    note = "現時沒有特別交通消息。" if not items else None
    return envelope(
        dataset_id=NEWS_DATASET,
        endpoint=NEWS_URL,
        retrieved_at=now_hkt(),
        data_at=max(announcements) if announcements else None,
        update_frequency="realtime",
        data=items,
        note=note,
    )


def _arrangement(fields: dict[str, str]) -> dict:
    return {
        "id": _blank(fields.get("TNID")),
        "type_id": _blank(fields.get("TrafficNoticesTypeID")),
        "district_id": _blank(fields.get("TrafficNoticesDistrictID")),
        "title_zh": _blank(fields.get("Title_TC")),
        "title_en": _blank(fields.get("Title_EN")),
        "title_sc": _blank(fields.get("Title_SC")),
        "start_date": _blank(fields.get("StartEffectiveDate")),
        "content_zh": _plain(fields.get("Content_TC")),
        "content_en": _plain(fields.get("Content_EN")),
        "content_sc": _plain(fields.get("Content_SC")),
    }


def special_traffic_arrangements() -> dict:
    """交還運輸署特別交通及運輸安排。

    資料集 `hk-td-tis_22-traffic-notices` 裡的特別交通及運輸措施。
    端點 `https://www.td.gov.hk/datagovhk_tis/traffic-notices/Special_Traffic_and_Transport_Arrangement.xml`。
    同一資料集還有封路、車速、禁區等其他通告，這裡不讀。

    用法：`special_traffic_arrangements()`。
    市民會問：這個週末或假期有什麼預先公布的交通安排？

    全港安排都交還，不按港鐵篩選，也不快取。生效日期沿用公布的日.月.年。
    內文原是 HTML，交還時去掉標籤。沒有資料時間欄，`data_at` 留空。
    """
    root = _xml(ARRANGEMENTS_URL, dataset_id=ARRANGEMENTS_DATASET)
    items = [
        _arrangement(_fields(element))
        for element in root
        if _local(element.tag) == "Notice"
    ]
    note = "現時沒有特別交通及運輸安排。" if not items else None
    return envelope(
        dataset_id=ARRANGEMENTS_DATASET,
        endpoint=ARRANGEMENTS_URL,
        retrieved_at=now_hkt(),
        data_at=None,
        update_frequency="daily",
        data=items,
        note=note,
    )
