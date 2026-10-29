import requests

import pytest

from hk_transport import als
from hk_transport._result import MtrError

UN_CHAU = {
    "SuggestedAddress": [
        {
            "Address": {
                "PremisesAddress": {
                    "EngPremisesAddress": {
                        "BuildingName": "UN CHAU SHOPPING CENTRE",
                        "EngEstate": {"EstateName": "UN CHAU ESTATE"},
                        "EngStreet": {"StreetName": "UN CHAU STREET", "BuildingNoFrom": "303"},
                        "EngDistrict": {"DcDistrict": "SHAM SHUI PO DISTRICT"},
                        "Region": "KLN",
                    },
                    "ChiPremisesAddress": {
                        "Region": "九龍",
                        "ChiDistrict": {"DcDistrict": "深水埗區"},
                        "ChiStreet": {"StreetName": "元州街", "BuildingNoFrom": "303"},
                        "ChiEstate": {"EstateName": "元州邨"},
                        "BuildingName": "元州商場",
                    },
                    "GeoAddress": "3401722137T20050430",
                    "GeospatialInformation": {
                        "Northing": "822137",
                        "Easting": "834017",
                        "Latitude": "22.3383",
                        "Longitude": "114.15502",
                    },
                }
            },
            "ValidationInformation": {"Score": 70.0},
        }
    ]
}


def test_address_lookup_parses_building_and_coordinates(monkeypatch):
    seen = {}

    def fake_get(url, params, headers, timeout):
        seen["url"] = url
        seen["params"] = params
        seen["headers"] = headers
        seen["timeout"] = timeout
        response = requests.Response()
        response.status_code = 200
        response._content = __import__("json").dumps(UN_CHAU).encode()
        return response

    monkeypatch.setattr(als.requests, "get", fake_get)
    result = als.address_lookup("元州商場")
    match = result["data"][0]
    assert seen["url"] == als.LOOKUP_URL
    assert seen["params"] == {"q": "元州商場"}
    assert seen["headers"]["Accept"] == "application/json"
    assert result["dataset_id"] == "hk-dpo-als_01-als"
    assert result["endpoint"] == "https://www.als.gov.hk/lookup?q=%E5%85%83%E5%B7%9E%E5%95%86%E5%A0%B4"
    assert result["retrieved_at"].endswith("+08:00")
    assert result["data_at"] is None
    assert result["update_frequency"] == "realtime"
    assert match["building_zh"] == "元州商場"
    assert match["building_en"] == "UN CHAU SHOPPING CENTRE"
    assert match["street_zh"] == "元州街"
    assert match["number_from"] == "303"
    assert match["district_zh"] == "深水埗區"
    assert match["latitude"] == "22.3383"
    assert match["longitude"] == "114.15502"
    assert match["score"] == 70.0


def test_address_lookup_can_limit_results(monkeypatch):
    seen = {}

    def fake_get(url, params, headers, timeout):
        seen["params"] = params
        response = requests.Response()
        response.status_code = 200
        response._content = b'{"SuggestedAddress":[]}'
        return response

    monkeypatch.setattr(als.requests, "get", fake_get)
    result = als.address_lookup("金鐘", n=3)
    assert seen["params"] == {"q": "金鐘", "n": "3"}
    assert result["data"] == []
    assert result["note"] == "沒有匹配地址。"


def test_address_lookup_http_error_names_the_dataset(monkeypatch):
    def fake_get(url, params, headers, timeout):
        raise requests.ConnectionError("down")

    monkeypatch.setattr(als.requests, "get", fake_get)
    with pytest.raises(MtrError) as caught:
        als.address_lookup("元州商場")
    assert caught.value.dataset_id == "hk-dpo-als_01-als"
    assert "als.gov.hk/lookup" in caught.value.endpoint


@pytest.mark.live
def test_live_un_chau_shopping_centre():
    result = als.address_lookup("元州商場", n=1)
    match = result["data"][0]
    assert match["building_zh"] == "元州商場"
    assert match["latitude"]
    assert match["longitude"]
    assert result["dataset_id"] == "hk-dpo-als_01-als"
    assert result["retrieved_at"].endswith("+08:00")
