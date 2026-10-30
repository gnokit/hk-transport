"""HTTP and the 30-day cache for monthly MTR files.

Live calls do not come through here. The cache directory is `.cache/` at the
skill root, or `HK_TRANSPORT_CACHE` when that variable is set.
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timedelta
from pathlib import Path

import requests

from hk_transport._result import HKT, MtrError, now_hkt

_CACHE_TTL = timedelta(days=30)


USER_AGENT = {"User-Agent": "hk-transport"}


def project_root() -> Path:
    for parent in Path(__file__).resolve().parents:
        if (parent / "pyproject.toml").is_file():
            return parent
    raise MtrError(
        "找不到技能目錄（沒有 pyproject.toml）",
        dataset_id="",
        endpoint="",
    )


def cache_dir() -> Path:
    override = os.environ.get("HK_TRANSPORT_CACHE")
    if override:
        return Path(override)
    return project_root() / ".cache"


def _fresh(retrieved_at: str) -> bool:
    fetched = datetime.fromisoformat(retrieved_at)
    if fetched.tzinfo is None:
        fetched = fetched.replace(tzinfo=HKT)
    return datetime.now(HKT) - fetched < _CACHE_TTL


def cached_file(
    url: str,
    *,
    dataset_id: str,
    timeout: float = 30,
    headers: dict | None = None,
) -> tuple[Path, str]:
    """Return the cached body file and when it was downloaded.

    Large feed files are read from this path instead of being loaded into a
    string first. Reuses a copy younger than 30 days.
    """
    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()
    directory = cache_dir()
    body_path = directory / f"{digest}.body"
    meta_path = directory / f"{digest}.json"
    if body_path.is_file() and meta_path.is_file():
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        if meta.get("url") == url and _fresh(meta["retrieved_at"]):
            return body_path, meta["retrieved_at"]
    try:
        response = requests.get(
            url, timeout=timeout, headers={**USER_AGENT, **(headers or {})}
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        raise MtrError(str(exc), dataset_id=dataset_id, endpoint=url) from exc
    text = response.content.decode("utf-8-sig")
    retrieved_at = now_hkt()
    directory.mkdir(parents=True, exist_ok=True)
    temporary = body_path.with_suffix(".body.tmp")
    temporary.write_text(text, encoding="utf-8")
    temporary.replace(body_path)
    meta_path.write_text(
        json.dumps({"url": url, "retrieved_at": retrieved_at}, ensure_ascii=False),
        encoding="utf-8",
    )
    return body_path, retrieved_at


def fetch_text(
    url: str,
    *,
    dataset_id: str,
    timeout: float = 30,
    headers: dict | None = None,
) -> tuple[str, str]:
    """Return the CSV text and when it was downloaded. Reuse a copy younger than 30 days."""
    path, retrieved_at = cached_file(
        url, dataset_id=dataset_id, timeout=timeout, headers=headers
    )
    return path.read_text(encoding="utf-8"), retrieved_at


def fetch_json(
    url: str,
    *,
    dataset_id: str,
    timeout: float = 30,
    cache: bool = True,
    headers: dict | None = None,
) -> tuple[object, str]:
    """Return a JSON payload and when it was retrieved.

    `cache=True` reuses the 30-day copy used by the monthly tables. Live feeds
    pass `cache=False` and are never written to disk.
    """
    if cache:
        text, retrieved_at = fetch_text(
            url, dataset_id=dataset_id, timeout=timeout, headers=headers
        )
    else:
        try:
            response = requests.get(
                url, timeout=timeout, headers={**USER_AGENT, **(headers or {})}
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            raise MtrError(str(exc), dataset_id=dataset_id, endpoint=url) from exc
        text = response.content.decode("utf-8-sig")
        retrieved_at = now_hkt()
    try:
        return json.loads(text), retrieved_at
    except ValueError as exc:
        raise MtrError(str(exc), dataset_id=dataset_id, endpoint=url) from exc
