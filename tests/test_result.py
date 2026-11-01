from hk_transport._result import as_hkt


def test_as_hkt_labels_a_naive_timestamp_as_hong_kong_time():
    assert as_hkt("2026-11-01 08:30:00") == "2026-11-01T08:30:00+08:00"
    assert as_hkt("2026-11-01T08:30") == "2026-11-01T08:30:00+08:00"


def test_as_hkt_accepts_slash_dates():
    assert as_hkt("2026/11/01 08:30") == "2026-11-01T08:30:00+08:00"
    assert as_hkt("2026/11/01 08:30:00") == "2026-11-01T08:30:00+08:00"
    assert as_hkt("2026/11/01") == "2026-11-01"


def test_as_hkt_leaves_an_explicit_zone_alone():
    assert as_hkt("2026-11-01T08:30:00+08:00") == "2026-11-01T08:30:00+08:00"
    assert as_hkt("2026-11-01T00:30:00Z") == "2026-11-01T00:30:00Z"


def test_as_hkt_returns_none_or_blank_for_no_value():
    assert as_hkt(None) is None
    assert as_hkt("   ") is None
