"""Reading one published cell.

A cell that holds only whitespace, or only a dash, is the publisher saying
"no value". It is not the string "-", and it is not zero. Every module reads
cells through these two functions so the answer is the same everywhere.
"""

from __future__ import annotations

# Characters publishers use to mean "nothing here".
_NO_VALUE = {"-", "—", "–"}


def blank(value: object) -> str | None:
    """The trimmed text, or None when the cell holds no value."""
    if value is None:
        return None
    text = str(value).strip()
    if text in _NO_VALUE:
        return None
    return text or None


def number(value: object) -> float | None:
    """The cell as a number, or None when it is missing or not a number."""
    text = blank(value)
    if text is None:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def clean_breaks(value: object) -> str | None:
    """Text with the publisher's line breaks flattened, or None when empty.

    The Transport Department writes a two-name stop as "A/<br>B"; keeping that
    as one readable line is better than leaking markup into an answer.
    """
    text = blank(value)
    if text is None:
        return None
    return text.replace("/<br>", "/").replace("<br>", " ").strip() or None
