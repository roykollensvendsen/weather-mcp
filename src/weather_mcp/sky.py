"""The sun and the moon on a day, from MET's sunrise 3.0 service, said in a few words.

MET gives each rise and set as a time with its offset, or none on a day it does not
happen, and the moon's phase as degrees from new: 90 is first quarter, 180 full.
"""

from __future__ import annotations

import datetime as dt
import zoneinfo
from typing import Any

SUN = "https://api.met.no/weatherapi/sunrise/3.0/sun"
MOON = "https://api.met.no/weatherapi/sunrise/3.0/moon"
#: Where each sky word is asked.
SKY = {"sunrise": SUN, "sunset": SUN, "sun": SUN, "moon": MOON, "moonrise": MOON, "moonset": MOON}
OSLO = zoneinfo.ZoneInfo("Europe/Oslo")
#: How far either side of new, a quarter or full, in degrees, the moon is called that: about a day.
NEAR = 12.0
#: The four main phases at their degrees, and the moon between each and the next.
MAIN = ((0.0, "new"), (90.0, "first quarter"), (180.0, "full"), (270.0, "last quarter"), (360.0, "new"))
BETWEEN = ("waxing crescent", "waxing gibbous", "waning gibbous", "waning crescent")


def sky_params(date: dt.date) -> dict[str, str]:
    """The day MET is asked about, with the offset Norway's clocks keep that day."""
    noon = dt.datetime.combine(date, dt.time(12), OSLO)
    offset = noon.strftime("%z")
    # RULE: summer is asked with summer time
    return {"date": date.isoformat(), "offset": f"{offset[:3]}:{offset[3:]}"}


def _clock(event: dict[str, Any]) -> str | None:
    time = event.get("time")
    return None if time is None else f"{dt.datetime.fromisoformat(time).astimezone(OSLO):%H:%M}"


def _event(name: str, event: dict[str, Any]) -> str:
    clock = _clock(event)
    # RULE: a day the sun only rises says no sunset
    return f"no {name}" if clock is None else f"{name} at {clock}"


def phase(degrees: float) -> str:
    """The moon's phase in plain words, from MET's degrees."""
    # RULE: the moon phase is said in plain words
    near = next((name for centre, name in MAIN if -NEAR <= degrees - centre < NEAR), None)
    return near or BETWEEN[int(degrees // 90) % len(BETWEEN)]


def _sun(kind: str, said: dict[str, Any]) -> str:
    if said["sunrise"]["time"] is None and said["sunset"]["time"] is None:
        # RULE: the midnight sun says the sun does not set
        up = bool(said["solarmidnight"]["visible"])
        # RULE: the polar night says the sun does not rise
        return "the sun does not set" if up else "the sun does not rise"
    events = {"sunrise": ("sunrise",), "sunset": ("sunset",), "sun": ("sunrise", "sunset")}[kind]
    # RULE: sunrise and sunset come from mets sun answer
    return ", ".join(_event(name, said[name]) for name in events)


def sky_said(kind: str, data: dict[str, Any]) -> str:
    """What MET's sunrise answer says for one sky word, as said after the day and the place."""
    said = data["properties"]
    if SKY[kind] == SUN:
        return _sun(kind, said)
    if kind == "moon":
        return f"the moon is {phase(float(said['moonphase']))}"
    # RULE: moonrise and moonset come from mets moon answer
    return _event(kind, said[kind])
