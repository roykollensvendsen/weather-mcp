"""What MET's radar sees over the next two hours, as one short sentence for a voice.

The nowcast is MET Norway's nowcast 2.0 complete, a step every five minutes. It covers the
Nordic area only, and it gives a rain rate only where the radar sees well.
"""

from __future__ import annotations

import datetime as dt
import zoneinfo
from typing import Any

NOWCAST = "https://api.met.no/weatherapi/nowcast/2.0/complete"
OSLO = zoneinfo.ZoneInfo("Europe/Oslo")
#: A rate below this, in millimetres an hour, is a trace the radar sees and nobody feels.
TRACE = 0.1
#: A reach of this many minutes or more is said as two hours, as MET names it.
TWO_HOURS = 110
#: The fewest minutes ahead worth a sentence: one radar step.
STEP = 5
#: How many steps in a row a change must last to be said; one alone is speckle.
SETTLED = 2


def called(sky: str) -> str:
    """What falls, by the sky's own word for it."""
    # RULE: the radars rain is called what the sky says falls
    return next((word.title() for word in ("snow", "sleet") if word in sky), "Rain")


def _ahead(data: dict[str, Any], now: dt.datetime) -> list[tuple[dt.datetime, float]]:
    """The radar's steps from the one under way, each with its rain rate."""
    # RULE: a radar that cannot see says nothing
    if data["properties"]["meta"].get("radar_coverage") != "ok":
        return []
    steps = [
        (
            dt.datetime.fromisoformat(entry["time"]),
            entry["data"]["instant"]["details"].get("precipitation_rate"),
        )
        for entry in data["properties"]["timeseries"]
    ]
    rated = [(time, float(rate)) for time, rate in steps if rate is not None]
    # RULE: the step under way counts as now
    start = max((time for time, _ in rated if time <= now), default=now)
    # RULE: past radar steps are left out
    return [(time, rate) for time, rate in rated if time >= start]


def _reach(minutes: int) -> str:
    # RULE: the radars reach is said as it is
    return "two hours" if minutes >= TWO_HOURS else f"{minutes // STEP * STEP} minutes"


def radar_sentence(data: dict[str, Any], now: dt.datetime, falls: str) -> str:
    """A sentence led by a space, such as " Rain from about 13:25.", or "" with no radar."""
    ahead = _ahead(data, now)
    minutes = int((ahead[-1][0] - now).total_seconds() // 60) if ahead else 0
    # RULE: a radar with no steps ahead says nothing
    if minutes < STEP:
        return ""
    # RULE: a trace below a tenth of a millimetre is dry
    wet = [rate >= TRACE for _, rate in ahead]
    # RULE: a single step of speckle is not a change
    change = next((ahead[n][0] for n in range(len(wet)) if wet[0] not in wet[n : n + SETTLED]), None)
    if change is None:
        # RULE: rain all through says so
        # RULE: no rain on the radar says dry
        return f" {falls if wet[0] else 'Dry'} for the next {_reach(minutes)}."
    at = f"{change.astimezone(OSLO):%H:%M}"
    # RULE: rain falling now says when it stops
    # RULE: rain on the radar says when it starts
    return f" {falls} until about {at}." if wet[0] else f" {falls} from about {at}."
