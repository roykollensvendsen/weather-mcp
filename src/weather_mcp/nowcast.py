"""What MET's radar sees over the next two hours, as one short sentence for a voice.

The nowcast is MET Norway's nowcast 2.0 complete, a step every five minutes. It covers the
Nordic area only, and it gives a rain rate only where the radar sees well.
"""

from __future__ import annotations

import datetime as dt
import logging
import zoneinfo
from typing import Any

NOWCAST = "https://api.met.no/weatherapi/nowcast/2.0/complete"
OSLO = zoneinfo.ZoneInfo("Europe/Oslo")
#: A rate below this, in millimetres an hour, is a trace the radar sees and nobody feels.
TRACE = 0.1
#: A reach of this many minutes or more is said as two hours, as MET names it. A nowcast
#: a few minutes old reaches a little short of that, and "105 minutes" helps nobody.
# RULE: a reach near two hours is said as two hours
TWO_HOURS = 100
#: The fewest minutes ahead worth a sentence: one radar step.
STEP = 5
#: How many steps in a row a change must last to be said; one alone is speckle.
SETTLED = 2
#: Rain sooner than this many minutes away is said by how soon, then the time.
HOUR = 60

log = logging.getLogger(__name__)


def called(sky: str) -> str:
    """What falls, by the sky's own word for it."""
    # RULE: the radars rain is called what the sky says falls
    return next((word.title() for word in ("snow", "sleet") if word in sky), "Rain")


def _unrated(*, seen: bool, rated: bool, fresh: bool) -> None:
    """Warn when a seeing radar gives steps but no rain rate, so a renamed field shows."""
    # RULE: a seeing radar with no rain rate is logged
    # RULE: a missing rain rate is logged once for each answer from met
    if fresh and seen and not rated:
        log.warning("MET's nowcast sees but gives no precipitation_rate")


def _ahead(data: dict[str, Any], now: dt.datetime, *, fresh: bool) -> list[tuple[dt.datetime, float]]:
    """The radar's steps from the one under way, each with its rain rate; `fresh` is a new answer."""
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
    _unrated(seen=bool(steps), rated=bool(rated), fresh=fresh)
    # RULE: the step under way counts as now
    start = max((time for time, _ in rated if time <= now), default=now)
    # RULE: past radar steps are left out
    return [(time, rate) for time, rate in rated if time >= start]


def _reach(minutes: int) -> str:
    # RULE: the radars reach is said as it is
    return "two hours" if minutes >= TWO_HOURS else f"{minutes // STEP * STEP} minutes"


def _changes(change: dt.datetime, now: dt.datetime, falls: str, *, wet: bool) -> str:
    at = f"{change.astimezone(OSLO):%H:%M}"
    # RULE: rain falling now says when it stops
    if wet:
        return f" {falls} until about {at}."
    soon = (change - now).total_seconds() / 60
    # RULE: how soon is rounded to the nearest five minutes
    # RULE: how soon is never said as less than five minutes
    rounded = max(int((soon + STEP / 2) // STEP) * STEP, STEP)
    # RULE: rain within the hour says how soon first
    if soon < HOUR:
        return f" {falls} in about {rounded} minutes, around {at}."
    # RULE: rain on the radar says when it starts
    return f" {falls} from about {at}."


def radar_sentence(data: dict[str, Any], now: dt.datetime, falls: str, *, fresh: bool = True) -> str:
    """A sentence led by a space, such as " Rain from about 13:25.", or "" with no radar."""
    ahead = _ahead(data, now, fresh=fresh)
    minutes = int((ahead[-1][0] - now).total_seconds() // 60) if ahead else 0
    # RULE: a radar with no steps ahead says nothing
    if minutes < STEP:
        return ""
    # RULE: a trace below a tenth of a millimetre is dry
    wet = [rate >= TRACE for _, rate in ahead]
    # RULE: a single step of speckle is not a change
    last = len(wet) - SETTLED + 1
    change = next((ahead[n][0] for n in range(last) if wet[0] not in wet[n : n + SETTLED]), None)
    if change is None:
        # RULE: rain all through says so
        # RULE: no rain on the radar says dry
        return f" {falls if wet[0] else 'Dry'} for the next {_reach(minutes)}."
    return _changes(change, now, falls, wet=wet[0])
