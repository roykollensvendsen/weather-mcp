"""Clock times as the owner says them, in Norwegian or English, and the Oslo hour they mean.

A bare hour is read on a twenty-four hour clock, so "3" is three at night; every answer says
the time back, which makes a misreading heard at once.
"""

from __future__ import annotations

import datetime as dt
import re
import zoneinfo

from weather_mcp.days import TRAILING

OSLO = zoneinfo.ZoneInfo("Europe/Oslo")
#: An hour as said: "15", "15:00", "15.00", "kl. 15", "klokka 15", "at 15", "3 pm".
TIME = re.compile(
    r"^(?:(?:kl|klokka|klokken|at)\.? ?)?(?P<hour>\d{1,2})(?:[:.](?P<minute>\d{2}))?"
    r" ?(?P<half>[ap]\.?m)?\.?$"
)
#: Hours in a day, and in each half of it on a twelve-hour clock.
DAY_HOURS = 24
HALF_DAY = 12
MINUTES = 60


def which_hour(said: str) -> int | None:
    """The hour of the day `said` names, 0 to 23, or None when it names none. Minutes are cut."""
    parts = TIME.match(" ".join(said.lower().rstrip(TRAILING).split()))
    if parts is None:
        return None
    # RULE: an hour has no more than sixty minutes
    if int(parts["minute"] or 0) >= MINUTES:
        return None
    hour = int(parts["hour"])
    if parts["half"]:
        # RULE: a twelve hour clock has no hour past twelve
        if not 1 <= hour <= HALF_DAY:
            return None
        # RULE: am and pm hours are read on a twelve hour clock
        hour = hour % HALF_DAY + (HALF_DAY if parts["half"].startswith("p") else 0)
    # RULE: an hour past the last of the day means none
    return hour if hour < DAY_HOURS else None


def at_hour(day: dt.date, hour: int) -> dt.datetime:
    """`hour` on `day` in Oslo: the first of an hour said twice, the next for one skipped."""
    # RULE: an hour said twice in autumn means the first
    wall = dt.datetime(day.year, day.month, day.day, hour, tzinfo=OSLO)
    # RULE: an hour skipped in spring means the next
    return wall.astimezone(dt.UTC).astimezone(OSLO)
