"""Result envelope shared by the MTR core and the use-case layer."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

HKT = timezone(timedelta(hours=8))

NO_ALERT = "這次回應沒有特別安排"


class MtrError(Exception):
    """A download or parse failed. The dataset and endpoint are the ones we called."""

    def __init__(self, message: str, *, dataset_id: str, endpoint: str) -> None:
        super().__init__(message)
        self.dataset_id = dataset_id
        self.endpoint = endpoint


def now_hkt() -> str:
    return datetime.now(HKT).replace(microsecond=0).isoformat()


def as_hkt(value: str | None) -> str | None:
    """Label a naive API timestamp as Hong Kong time without shifting the clock."""
    if value is None:
        return None
    text = value.strip()
    if not text:
        return None
    if text.endswith("Z") or "+" in text:
        return text
    text = text.replace(" ", "T")
    if len(text) == 19:
        return text + "+08:00"
    return text


def envelope(
    *,
    dataset_id: str | list[str],
    endpoint: str | list[str],
    retrieved_at: str | list[str],
    data_at: str | None | list[str | None],
    update_frequency: str,
    data: object,
    note: str | None = None,
) -> dict:
    return {
        "dataset_id": dataset_id,
        "endpoint": endpoint,
        "retrieved_at": retrieved_at,
        "data_at": data_at,
        "update_frequency": update_frequency,
        "data": data,
        "note": note,
    }


def compose(sources: list[dict], data: object, note: str | None = None) -> dict:
    """One envelope over core results. Each source keeps its own timestamp."""
    dataset_ids: list[str] = []
    endpoints: list[str] = []
    retrieved: list[str] = []
    for source in sources:
        if source["dataset_id"] not in dataset_ids:
            dataset_ids.append(source["dataset_id"])
        endpoint = source["endpoint"]
        items = endpoint if isinstance(endpoint, list) else [endpoint]
        for item in items:
            if item not in endpoints:
                endpoints.append(item)
        retrieved_at = source["retrieved_at"]
        if isinstance(retrieved_at, list):
            retrieved.extend(retrieved_at)
        else:
            retrieved.append(retrieved_at)
    live = [source for source in sources if source["update_frequency"] == "10s"]
    if not live:
        data_at: str | None | list[str | None] = None
        frequency = "monthly"
    elif len(live) == 1:
        data_at = live[0]["data_at"]
        frequency = "10s"
    else:
        data_at = [source["data_at"] for source in live]
        frequency = "10s"
    return {
        "dataset_id": dataset_ids[0] if len(dataset_ids) == 1 else dataset_ids,
        "endpoint": endpoints[0] if len(endpoints) == 1 else endpoints,
        "retrieved_at": retrieved[0] if len(set(retrieved)) == 1 else retrieved,
        "data_at": data_at,
        "update_frequency": frequency,
        "sources": [
            {
                "dataset_id": source["dataset_id"],
                "endpoint": source["endpoint"],
                "retrieved_at": source["retrieved_at"],
                "data_at": source["data_at"],
                "update_frequency": source["update_frequency"],
            }
            for source in sources
        ],
        "data": data,
        "note": note,
    }
