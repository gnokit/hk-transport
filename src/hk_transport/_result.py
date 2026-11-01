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
    if "/" in text:
        date, _, time = text.partition(" ")
        if len(date) == 10 and date[4] == "/" and date[7] == "/":
            text = date.replace("/", "-")
            if time:
                text += "T" + time
    else:
        text = text.replace(" ", "T")
    if len(text) == 16:
        return text + ":00+08:00"
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


def _is_live(frequency: str) -> bool:
    """True for an update frequency written as seconds, such as 10s or 60s."""
    return (
        isinstance(frequency, str)
        and frequency.endswith("s")
        and frequency[:-1].isdigit()
    )


def compose(sources: list[dict], data: object, note: str | None = None) -> dict:
    """One envelope over core results. Each source keeps its own timestamp.

    With no sources the envelope keeps every field null: the caller had nothing
    to look at, and saying "monthly" would invent a fact.
    """
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
    live = [source for source in sources if _is_live(source["update_frequency"])]
    if live:
        live_frequencies: list[str] = []
        for source in live:
            if source["update_frequency"] not in live_frequencies:
                live_frequencies.append(source["update_frequency"])
        frequency: str | list[str] = (
            live_frequencies[0] if len(live_frequencies) == 1 else live_frequencies
        )
        data_at: str | None | list[str | None] = (
            live[0]["data_at"]
            if len(live) == 1
            else [source["data_at"] for source in live]
        )
    else:
        data_at = None
        # A file that is yearly or realtime must not be relabelled monthly.
        frequencies: list[str] = []
        for source in sources:
            if source["update_frequency"] not in frequencies:
                frequencies.append(source["update_frequency"])
        frequency = frequencies[0] if len(frequencies) == 1 else frequencies
    return {
        "dataset_id": dataset_ids[0] if len(dataset_ids) == 1 else (dataset_ids or None),
        "endpoint": endpoints[0] if len(endpoints) == 1 else (endpoints or None),
        "retrieved_at": retrieved[0] if len(set(retrieved)) == 1 else (retrieved or None),
        "data_at": data_at,
        "update_frequency": frequency or None,
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
