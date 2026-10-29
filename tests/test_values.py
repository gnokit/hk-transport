from hk_transport import als, mtr_core, notices
from hk_transport._values import blank, number


def test_blank_treats_whitespace_and_dashes_as_no_value():
    assert blank(None) is None
    assert blank("") is None
    assert blank("   ") is None
    assert blank("-") is None
    assert blank("—") is None
    assert blank(" A ") == "A"


def test_number_reads_a_cell_or_returns_none():
    assert number("22.3") == 22.3
    assert number(" 2 ") == 2.0
    assert number("-") is None
    assert number("not a number") is None
    assert number(None) is None


def test_every_module_reads_cells_the_same_way():
    assert mtr_core.blank is blank
    assert als.blank is blank
    assert notices.blank is blank
