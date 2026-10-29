import json
from datetime import datetime, timedelta

import pytest

from hk_transport._http import cache_dir, fetch_text
from hk_transport._result import HKT, MtrError


class _Response:
    def __init__(self, text, status=200):
        self.content = text.encode("utf-8")
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise __import__("requests").HTTPError(f"status {self.status_code}")


def test_cache_reuses_a_copy_younger_than_30_days(monkeypatch):
    calls = []

    def fake_get(url, timeout, headers=None):
        calls.append(url)
        return _Response("line,name\nA,金鐘\n")

    monkeypatch.setattr("hk_transport._http.requests.get", fake_get)
    first, fetched = fetch_text("https://example.test/a.csv", dataset_id="dataset")
    second, fetched_again = fetch_text("https://example.test/a.csv", dataset_id="dataset")

    assert first == second == "line,name\nA,金鐘\n"
    assert fetched == fetched_again
    assert calls == ["https://example.test/a.csv"]
    stored = list(cache_dir().glob("*.body"))
    assert len(stored) == 1


def test_cache_refreshes_after_30_days(monkeypatch):
    calls = []

    def fake_get(url, timeout, headers=None):
        calls.append("hit")
        return _Response("new")

    monkeypatch.setattr("hk_transport._http.requests.get", fake_get)
    fetch_text("https://example.test/old.csv", dataset_id="dataset")
    meta = next(cache_dir().glob("*.json"))
    payload = json.loads(meta.read_text(encoding="utf-8"))
    payload["retrieved_at"] = (datetime.now(HKT) - timedelta(days=31)).isoformat()
    meta.write_text(json.dumps(payload), encoding="utf-8")

    text, _fetched = fetch_text("https://example.test/old.csv", dataset_id="dataset")

    assert text == "new"
    assert calls == ["hit", "hit"]


def test_http_error_names_the_dataset(monkeypatch):
    def fake_get(url, timeout, headers=None):
        return _Response("nope", status=500)

    monkeypatch.setattr("hk_transport._http.requests.get", fake_get)
    with pytest.raises(MtrError) as caught:
        fetch_text("https://example.test/missing.csv", dataset_id="mtr-data")
    assert caught.value.dataset_id == "mtr-data"
    assert caught.value.endpoint == "https://example.test/missing.csv"
