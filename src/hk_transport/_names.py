"""Spelling variants that appear in published Hong Kong names.

The MTR file publishes 茘枝角 (with 茘). People commonly type 荔枝角, so the
answer layer normalises it before matching. Keep the table small and explain
each entry; do not turn it into a fuzzy matcher.
"""

from __future__ import annotations

STATION_ALIASES = {"荔枝角": "茘枝角"}


def station_name(value: str) -> str:
    """Return the published station spelling for a common variant."""
    text = value.strip()
    return STATION_ALIASES.get(text, text)
