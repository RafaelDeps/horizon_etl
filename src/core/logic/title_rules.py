"""Rules for titles and years read from Lattes curricula (branch 041).

* ``fix_lost_dash``: the downloaded curricula already hold a literal "?" where
  the source had a dash ("Ifes ? Campus Ibatiba"). A "?" with a space on each
  side between two words becomes an en dash; every other "?" (a real question,
  a "?" used as quotation marks, broken encoding) is kept. Keys ignore
  punctuation, so the fix never changes a key.
* ``plausible_year``: a year between 1950 and next year, or None. The crawler
  gives some conference items the year 0.

Contract: specs/041-dashboard-visible-fixes/contracts/dashboard-fixes.md,
section 4.
"""

import re
from datetime import date
from typing import Any, Optional

_LOST_DASH = re.compile(r"(?<=\w) \? (?=\w)")
FIRST_YEAR = 1950


def fix_lost_dash(title):
    """The title with each lost dash written as " – "."""
    if not title or not isinstance(title, str):
        return title
    return _LOST_DASH.sub(" – ", title)


def plausible_year(value: Any) -> Optional[int]:
    """The year as an int when it is between 1950 and next year, else None."""
    if value is None or isinstance(value, bool):
        return None
    text = str(value).strip()
    if not text.isdigit():
        return None
    year = int(text)
    if FIRST_YEAR <= year <= date.today().year + 1:
        return year
    return None
