import pytest

from hk_transport.mtr_core import clear_cache


@pytest.fixture(autouse=True)
def isolated_cache(tmp_path, monkeypatch):
    monkeypatch.setenv("HK_TRANSPORT_CACHE", str(tmp_path))
    clear_cache()
    yield
    clear_cache()
