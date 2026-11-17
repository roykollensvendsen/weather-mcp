"""Which day a spoken word means, and how a day is said back.

The plugin works the day out itself, from today's date in Oslo, so the voice model only
passes on what the owner said. Norwegian and English words are both understood.
"""

from __future__ import annotations

import datetime as dt
import re

#: Days named outright, by how many days ahead of today each is.
NAMED = {
    "today": 0,
    "i dag": 0,
    "idag": 0,
    "tomorrow": 1,
    "i morgen": 1,
    "imorgen": 1,
    "the day after tomorrow": 2,
    "day after tomorrow": 2,
    "i overmorgen": 2,
    "overmorgen": 2,
    "overimorgen": 2,
}
#: Each weekday's words, Monday first, as Python numbers them; "ø" may come as "o".
WEEKDAYS = {
    word: number
    for number, words in enumerate(
        (
            ("monday", "mandag"),
            ("tuesday", "tirsdag"),
            ("wednesday", "onsdag"),
            ("thursday", "torsdag"),
            ("friday", "fredag"),
            ("saturday", "lørdag", "lordag"),
            ("sunday", "søndag", "sondag"),
        )
    )
    for word in words
}
#: How each weekday is said back.
NAMES = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
#: Words before a weekday that change nothing: "på fredag", "on Friday", "this Friday".
LEADS = ("på ", "on ", "this ")
#: Words before a weekday that pass over today: "neste lørdag" said on a Saturday is a week on.
NEXT = ("next ", "neste ")
#: A date as 20.11, 20.11. or 20.11.2026.
DATE = re.compile(r"^(\d{1,2})\.(\d{1,2})\.?(\d{4})?$")
#: How many days back a date without a year may lie and still be this year's.
RECENT = 30
#: Days in a week: from this far ahead, a weekday's name alone could mean two days.
WEEK = 7


def which_day(said: str, today: dt.date) -> dt.date | None:
    """The date `said` names, counting from `today`, or None when it names no day."""
    words = " ".join(said.lower().split())
    if words in NAMED:
        return today + dt.timedelta(days=NAMED[words])
    return _weekday(words, today) or _date(words, today)


def _weekday(words: str, today: dt.date) -> dt.date | None:
    skip = False
    for lead in NEXT:
        if words.startswith(lead):
            words, skip = words.removeprefix(lead), True
    for lead in LEADS:
        words = words.removeprefix(lead)
    if words not in WEEKDAYS:
        # RULE: a word that names no day means none
        return None
    # RULE: a weekday said on that day is today
    ahead = (WEEKDAYS[words] - today.weekday()) % WEEK
    if skip and ahead == 0:
        # RULE: next with a weekday skips today
        ahead = WEEK
    return today + dt.timedelta(days=ahead)


def _date(words: str, today: dt.date) -> dt.date | None:
    try:
        return dt.date.fromisoformat(words)
    except ValueError:
        pass
    parts = DATE.match(words)
    if parts is None:
        return None
    day, month, year = int(parts[1]), int(parts[2]), parts[3]
    try:
        when = dt.date(int(year) if year else today.year, month, day)
        if year is None and when < today - dt.timedelta(days=RECENT):
            # RULE: a date long past this year means next year
            when = when.replace(year=today.year + 1)
    except ValueError:  # no such day, such as 31.02, or 29.02 in a year without one
        return None
    return when


def label(day: dt.date, today: dt.date) -> str:
    """How `day` is said: today, tomorrow, its weekday, and its date too once a week away."""
    ahead = (day - today).days
    if ahead == 0:
        return "Today"
    if ahead == 1:
        return "Tomorrow"
    name = NAMES[day.weekday()]
    # RULE: a day is said by its name and by its date once a week away
    return name if ahead < WEEK else f"{name} {day:%d.%m}"
