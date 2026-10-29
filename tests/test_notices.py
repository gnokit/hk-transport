import requests
import pytest

from hk_transport import notices
from hk_transport._result import MtrError

NEWS_XML = """<?xml version="1.0" encoding="UTF-8"?>
<list>
  <message>
    <INCIDENT_NUMBER>IN-26-07869</INCIDENT_NUMBER>
    <INCIDENT_HEADING_EN>Road Incident</INCIDENT_HEADING_EN>
    <INCIDENT_HEADING_CN>道路事故</INCIDENT_HEADING_CN>
    <INCIDENT_DETAIL_EN>Fire</INCIDENT_DETAIL_EN>
    <INCIDENT_DETAIL_CN>火警</INCIDENT_DETAIL_CN>
    <LOCATION_EN>Austin Road</LOCATION_EN>
    <LOCATION_CN>柯士甸道</LOCATION_CN>
    <DISTRICT_EN></DISTRICT_EN>
    <DISTRICT_CN></DISTRICT_CN>
    <DIRECTION_EN>Hung Hom</DIRECTION_EN>
    <DIRECTION_CN>紅磡</DIRECTION_CN>
    <ANNOUNCEMENT_DATE>2026-10-29T11:02:00</ANNOUNCEMENT_DATE>
    <INCIDENT_STATUS_EN>UPDATED</INCIDENT_STATUS_EN>
    <INCIDENT_STATUS_CN>更新情況</INCIDENT_STATUS_CN>
    <NEAR_LANDMARK_EN>Nathan Road</NEAR_LANDMARK_EN>
    <NEAR_LANDMARK_CN>彌敦道</NEAR_LANDMARK_CN>
    <BETWEEN_LANDMARK_EN>Cox&#039;s Road</BETWEEN_LANDMARK_EN>
    <BETWEEN_LANDMARK_CN>覺士道</BETWEEN_LANDMARK_CN>
    <ID>148722</ID>
    <CONTENT_EN>Austin Road is re-opened. </CONTENT_EN>
    <CONTENT_CN>柯士甸道現已解封。</CONTENT_CN>
    <LATITUDE></LATITUDE>
    <LONGITUDE></LONGITUDE>
  </message>
  <message>
    <INCIDENT_NUMBER>IN-26-00002</INCIDENT_NUMBER>
    <INCIDENT_HEADING_EN>Public Transport</INCIDENT_HEADING_EN>
    <INCIDENT_HEADING_CN>公共交通</INCIDENT_HEADING_CN>
    <INCIDENT_DETAIL_EN></INCIDENT_DETAIL_EN>
    <INCIDENT_DETAIL_CN></INCIDENT_DETAIL_CN>
    <LOCATION_EN></LOCATION_EN>
    <LOCATION_CN></LOCATION_CN>
    <ANNOUNCEMENT_DATE>2026-10-29T09:00:00</ANNOUNCEMENT_DATE>
    <INCIDENT_STATUS_EN>NEW</INCIDENT_STATUS_EN>
    <INCIDENT_STATUS_CN>新消息</INCIDENT_STATUS_CN>
    <ID>2</ID>
    <CONTENT_EN>MTR service is delayed.</CONTENT_EN>
    <CONTENT_CN>港鐵服務延誤。</CONTENT_CN>
    <LATITUDE>22.30</LATITUDE>
    <LONGITUDE>114.17</LONGITUDE>
  </message>
</list>
"""

ARRANGEMENT_XML = """<?xml version="1.0" encoding="UTF-8"?>
<List>
  <Notice>
    <TNID>89419</TNID>
    <TrafficNoticesTypeID>1</TrafficNoticesTypeID>
    <TrafficNoticesDistrictID></TrafficNoticesDistrictID>
    <Title_EN>Temporary arrangements on Tai Tong Road</Title_EN>
    <Title_TC>元朗大棠路臨時交通及運輸安排</Title_TC>
    <Title_SC>元朗大棠路临时交通及运输安排</Title_SC>
    <StartEffectiveDate>19.11.2026</StartEffectiveDate>
    <Content_EN>&lt;p&gt;Lane conversion from 9.00 p.m.&lt;/p&gt;</Content_EN>
    <Content_TC>&lt;div&gt;交通通告&lt;/div&gt;&lt;p&gt;每晚9時至翌日上午6時。&lt;/p&gt;</Content_TC>
    <Content_SC>&lt;p&gt;临时安排&lt;/p&gt;</Content_SC>
  </Notice>
</List>
"""


class _Response:
    def __init__(self, text: str, status: int = 200) -> None:
        self.content = text.encode("utf-8")
        self.status_code = status

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(f"status {self.status_code}")


def test_special_traffic_news_keeps_every_notice(monkeypatch):
    def fake_get(url, timeout, headers):
        assert url == notices.NEWS_URL
        assert headers["User-Agent"] == "hk-transport"
        return _Response(NEWS_XML)

    monkeypatch.setattr(notices.requests, "get", fake_get)
    result = notices.special_traffic_news()
    assert result["dataset_id"] == notices.NEWS_DATASET
    assert result["endpoint"] == notices.NEWS_URL
    assert result["update_frequency"] == "realtime"
    assert result["data_at"] == "2026-10-29T11:02:00+08:00"
    assert result["note"] is None
    assert [item["incident_number"] for item in result["data"]] == ["IN-26-07869", "IN-26-00002"]
    first = result["data"][0]
    assert first["heading_zh"] == "道路事故"
    assert first["between_landmark_en"] == "Cox's Road"
    assert first["content_zh"] == "柯士甸道現已解封。"
    assert first["latitude"] is None
    assert first["announcement_at"] == "2026-10-29T11:02:00+08:00"
    second = result["data"][1]
    assert second["content_zh"] == "港鐵服務延誤。"
    assert second["latitude"] == 22.3
    assert second["longitude"] == 114.17


def test_empty_traffic_news_says_there_is_none(monkeypatch):
    monkeypatch.setattr(notices.requests, "get", lambda *args, **kwargs: _Response("<list></list>"))
    result = notices.special_traffic_news()
    assert result["data"] == []
    assert result["data_at"] is None
    assert result["note"] == "現時沒有特別交通消息。"


def test_traffic_news_http_error_names_the_dataset(monkeypatch):
    monkeypatch.setattr(
        notices.requests, "get", lambda *args, **kwargs: _Response("nope", status=500)
    )
    with pytest.raises(MtrError) as caught:
        notices.special_traffic_news()
    assert caught.value.dataset_id == notices.NEWS_DATASET
    assert caught.value.endpoint == notices.NEWS_URL


def test_bad_news_xml_names_the_dataset(monkeypatch):
    monkeypatch.setattr(notices.requests, "get", lambda *args, **kwargs: _Response("<list>"))
    with pytest.raises(MtrError) as caught:
        notices.special_traffic_news()
    assert caught.value.dataset_id == notices.NEWS_DATASET


def test_arrangements_strip_html_and_keep_the_published_date(monkeypatch):
    def fake_get(url, timeout, headers):
        assert url == notices.ARRANGEMENTS_URL
        return _Response(ARRANGEMENT_XML)

    monkeypatch.setattr(notices.requests, "get", fake_get)
    result = notices.special_traffic_arrangements()
    assert result["dataset_id"] == notices.ARRANGEMENTS_DATASET
    assert result["update_frequency"] == "daily"
    assert result["data_at"] is None
    assert result["note"] is None
    item = result["data"][0]
    assert item["id"] == "89419"
    assert item["title_zh"] == "元朗大棠路臨時交通及運輸安排"
    assert item["start_date"] == "19.11.2026"
    assert item["district_id"] is None
    assert "<" not in item["content_zh"]
    assert "每晚9時至翌日上午6時" in item["content_zh"]
    assert "Lane conversion" in item["content_en"]


def test_empty_arrangements_say_there_are_none(monkeypatch):
    monkeypatch.setattr(notices.requests, "get", lambda *args, **kwargs: _Response("<List></List>"))
    result = notices.special_traffic_arrangements()
    assert result["data"] == []
    assert result["note"] == "現時沒有特別交通及運輸安排。"


@pytest.mark.live
def test_live_special_traffic_news():
    result = notices.special_traffic_news()
    assert result["dataset_id"] == notices.NEWS_DATASET
    assert result["endpoint"] == notices.NEWS_URL
    assert isinstance(result["data"], list)
    if result["data"]:
        assert result["data"][0]["incident_number"]
        assert result["data"][0]["content_zh"]


@pytest.mark.live
def test_live_special_traffic_arrangements():
    result = notices.special_traffic_arrangements()
    assert result["dataset_id"] == notices.ARRANGEMENTS_DATASET
    assert result["data"]
    item = result["data"][0]
    assert item["id"]
    assert item["title_zh"]
    assert item["start_date"]
    assert "<div" not in (item["content_zh"] or "")
    assert "<p" not in (item["content_zh"] or "")
